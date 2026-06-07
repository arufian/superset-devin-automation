from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from src.config import settings
from src import classifier, devin_client, github_client, policy, safety, tracker, webhook

logger = logging.getLogger(__name__)


def classify_issue_event(
    issue_data: dict[str, Any],
    trigger_type: str,
    *,
    post_comment: bool = True,
) -> dict[str, Any]:
    issue_number = issue_data["number"]
    issue_title = issue_data["title"]
    issue_url = issue_data["html_url"]

    result = classifier.classify_issue(issue_data)
    labels = classifier.classification_labels(result)

    record = tracker.create_classification(
        issue_number=issue_number,
        issue_url=issue_url,
        issue_title=issue_title,
        priority=result.priority,
        complexity=result.complexity,
        priority_reason=result.priority_reason,
        complexity_reason=result.complexity_reason,
        trigger_type=trigger_type,
    )

    labels_applied = _try_add_labels(issue_number, labels, "classification")
    comment_posted = False

    if post_comment:
        comment_posted = _try_comment_on_issue(
            issue_number,
            _classification_comment(result, trigger_type),
            "classification",
        )

    logger.info(
        "Classified issue #%d as %s / %s",
        issue_number,
        result.priority,
        result.complexity,
    )
    return {
        "classification": result.as_dict(),
        "labels": labels,
        "labels_applied": labels_applied,
        "comment_posted": comment_posted,
        "record": record,
    }


def process_issue(
    issue_data: dict[str, Any],
    trigger_type: str,
    forced_action: str | None = None,
) -> dict[str, Any]:
    issue_number = issue_data["number"]
    issue_title = issue_data["title"]
    issue_body = issue_data.get("body", "") or ""
    issue_url = issue_data["html_url"]

    existing = tracker.get_job_by_issue(issue_number)
    if forced_action == "implement_plan" and existing and existing["status"] == "plan_dispatched":
        tracker.update_job(existing["id"], status="plan_approved")

    if (
        existing
        and existing["status"] in ("pending", "running", "dispatched", "dispatching", "plan_dispatched")
        and forced_action != "implement_plan"
    ):
        logger.info("Issue #%d already has active job %d, skipping", issue_number, existing["id"])
        return existing

    classification_result = classify_issue_event(issue_data, trigger_type, post_comment=False)
    classification = classification_result["classification"]

    if not forced_action and settings.plan_label in _label_names(issue_data):
        forced_action = "plan"

    decision = policy.decide(
        priority=classification["priority"].split(":", 1)[1],
        complexity=classification["complexity"].split(":", 1)[1],
        forced_action=forced_action,
    )
    policy_data = decision.as_dict()

    job = tracker.create_job(
        issue_number=issue_number,
        issue_url=issue_url,
        issue_title=issue_title,
        trigger_type=trigger_type,
        metadata={
            "labels": sorted(_label_names(issue_data)),
            "assignee": issue_data.get("assignee", {}).get("login") if issue_data.get("assignee") else None,
            "classification": classification,
            "policy": policy_data,
        },
    )
    logger.info("Created job %d for issue #%d", job["id"], issue_number)

    try:
        tracker.update_job(job["id"], status="dispatching")

        repo_url = f"https://github.com/{settings.github_repo}"
        prompt = devin_client.build_prompt(
            repo_url=repo_url,
            issue_number=issue_number,
            issue_title=issue_title,
            issue_body=issue_body,
            issue_url=issue_url,
            classification=classification,
            policy=policy_data,
        )

        session = devin_client.create_session(
            prompt=prompt,
            title=f"{decision.action} superset#{issue_number}: {issue_title}",
            tags=[
                "superset-automation",
                f"issue-{issue_number}",
                classification["priority"].replace(":", "-"),
                classification["complexity"].replace(":", "-"),
                decision.action.replace("_", "-"),
            ],
        )

        session_id = session["session_id"]
        session_url = session["url"]
        status = "plan_dispatched" if decision.devin_mode == "plan_only" else "dispatched"

        tracker.update_job(
            job["id"],
            status=status,
            devin_session_id=session_id,
            devin_session_url=session_url,
            devin_status=session.get("status"),
            devin_status_detail=session.get("status_detail"),
        )

        comment_posted = _try_comment_on_issue(
            issue_number,
            _dispatch_comment(
                classification=classification,
                policy_data=policy_data,
                session_id=session_id,
                session_url=session_url,
                trigger_type=trigger_type,
            ),
            "dispatch",
        )
        if not comment_posted:
            tracker.update_job(
                job["id"],
                error_message="Devin session dispatched, but GitHub comment failed. Check GH_PAT issue write access.",
            )
        else:
            logger.info("Commented on issue #%d with session info", issue_number)

        return tracker.get_job(job["id"])

    except Exception as e:
        logger.error("Failed to process issue #%d: %s", issue_number, e, exc_info=True)
        tracker.update_job(
            job["id"],
            status="failed",
            error_message=str(e),
        )
        _try_comment_on_issue(
            issue_number,
            f"## Devin Automation Failed\n\n"
            f"The automation encountered an error while dispatching this issue to Devin.\n\n"
            f"**Error**: `{e}`\n\n"
            f"This issue will need manual attention.\n\n"
            f"---\n*Automated by superset-devin-automation*",
            "failure",
        )
        return tracker.get_job(job["id"])


def sync_session_status(job: dict[str, Any]) -> dict[str, Any] | None:
    if not job.get("devin_session_id"):
        return None

    try:
        session = devin_client.get_session(job["devin_session_id"])
        new_status = session.get("status", "unknown")
        new_detail = session.get("status_detail")
        meta_dict = _job_metadata(job)
        devin_mode = meta_dict.get("policy", {}).get("devin_mode")

        updates: dict[str, Any] = {
            "devin_status": new_status,
            "devin_status_detail": new_detail,
        }

        if new_status == "exit":
            if new_detail == "finished":
                updates["status"] = "plan_dispatched" if devin_mode == "plan_only" else "completed"
            else:
                updates["status"] = "devin_exited"
        elif new_status == "error":
            updates["status"] = "failed"
            updates["error_message"] = f"Devin error: {new_detail}"
        elif new_status in ("running", "claimed"):
            updates["status"] = "running"

        prs = session.get("pull_requests", [])
        if prs:
            meta_dict["pull_requests"] = prs
            updates["metadata"] = meta_dict

        return tracker.update_job(job["id"], **updates)

    except Exception as e:
        logger.error("Failed to sync session for job %d: %s", job["id"], e, exc_info=True)
        tracker.update_job(
            job["id"],
            error_message=f"Session sync failed: {e}",
        )
        return None


def scan_ready_issues() -> list[dict[str, Any]]:
    logger.info("Scanning for issues labeled '%s'", settings.scan_label)
    issues = github_client.list_issues_with_label(settings.scan_label)
    results = []
    for issue in issues:
        try:
            result = process_issue(issue, trigger_type="scheduled_scan")
        except Exception as e:
            logger.error("Scheduled scan failed for issue #%s: %s", issue.get("number"), e, exc_info=True)
            result = {
                "issue_number": issue.get("number"),
                "status": "failed",
                "error_message": str(e),
            }
        results.append(result)
    logger.info("Scan complete: %d issues processed", len(results))
    return results


def scan_pr_safety(
    pr_data: dict[str, Any],
    trigger_type: str,
    diff_text: str | None = None,
) -> dict[str, Any]:
    pr_number = pr_data["number"]
    pr_title = pr_data.get("title", "")
    pr_url = pr_data.get("html_url", "")
    diff_text = diff_text if diff_text is not None else github_client.get_pull_request_diff(pr_number)
    scan = safety.scan_diff(diff_text)
    scan_data = scan.as_dict()

    event = tracker.create_safety_event(
        pr_number=pr_number,
        pr_url=pr_url,
        pr_title=pr_title,
        trigger_type=trigger_type,
        blocked=scan.blocked,
        prompt_injection_count=scan.prompt_injection_count,
        malicious_code_count=scan.malicious_code_count,
        findings=scan_data["findings"],
    )

    if scan.blocked:
        _try_add_labels(pr_number, [settings.safety_block_label, "devin:auto-merge-blocked"], "pr_safety")
        _try_comment_on_issue(pr_number, _safety_block_comment(scan_data), "pr_safety")
        security_issue = _try_create_issue(
            title=f"Security review needed for PR #{pr_number}: {pr_title}",
            body=_security_issue_body(pr_data, scan_data),
            labels=[settings.safety_block_label, "devin:security-review"],
            context="pr_safety",
        )
        if not security_issue:
            logger.error(
                "Failed to create security review issue for PR #%d — "
                "safety findings may go unnoticed without manual follow-up",
                pr_number,
            )
        logger.warning("PR #%d blocked by safety scan", pr_number)
    else:
        logger.info("PR #%d safety scan passed", pr_number)

    return {"event": event, "scan": scan_data}


def handle_github_event(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if event_type == "issues":
        issue = webhook.extract_issue_from_webhook(payload)
        if not issue:
            return {"status": "ignored", "event": event_type}

        action = payload.get("action")
        label = webhook.labeled_name(payload)

        if action == "opened":
            result = classify_issue_event(issue, "webhook_issue_opened")
            return {"status": "classified", "issue": issue["number"], "result": result}

        if action == "labeled" and label == settings.plan_label:
            result = process_issue(issue, "webhook_plan_label", forced_action="plan")
            return {"status": "dispatched", "issue": issue["number"], "job": result}

        if action == "labeled" and label in {settings.trigger_label, settings.scan_label}:
            result = process_issue(issue, "webhook_label")
            return {"status": "dispatched", "issue": issue["number"], "job": result}

    if event_type == "issue_comment":
        issue = webhook.extract_issue_comment_approval(payload)
        if issue:
            result = process_issue(issue, "webhook_plan_approval", forced_action="implement_plan")
            return {"status": "dispatched", "issue": issue["number"], "job": result}

    if event_type == "pull_request":
        pr = webhook.extract_pull_request_from_webhook(payload)
        if pr:
            result = scan_pr_safety(pr, "webhook_pull_request")
            return {
                "status": "blocked" if result["scan"]["blocked"] else "passed",
                "pull_request": pr["number"],
                "result": result,
            }

    return {"status": "ignored", "event": event_type}


def recover_scheduled_work() -> dict[str, Any]:
    ready_results = scan_ready_issues()

    synced = []
    marked_stale = []
    for job in tracker.list_active_jobs():
        synced_job = sync_session_status(job)
        if synced_job:
            synced.append(synced_job)
        stale_job = _mark_stale_if_needed(synced_job or job)
        if stale_job:
            marked_stale.append(stale_job)

    classified = []
    classification_errors: list[dict[str, Any]] = []
    for issue in github_client.list_open_issues():
        if tracker.get_latest_classification(issue["number"]):
            continue
        try:
            classified.append(classify_issue_event(issue, "scheduled_unprocessed_issue", post_comment=True))
        except Exception as e:
            logger.error("Scheduled classification failed for issue #%s: %s", issue.get("number"), e, exc_info=True)
            classification_errors.append({"issue_number": issue.get("number"), "error": str(e)})

    pr_scans = []
    pr_scan_errors: list[dict[str, Any]] = []
    for pr in github_client.list_open_pull_requests():
        try:
            pr_scans.append(scan_pr_safety(pr, "scheduled_pr_scan"))
        except Exception as e:
            logger.error("Scheduled PR scan failed for PR #%s: %s", pr.get("number"), e, exc_info=True)
            pr_scan_errors.append({"pr_number": pr.get("number"), "error": str(e)})

    return {
        "ready_issues_processed": len(ready_results),
        "sessions_synced": len(synced),
        "stale_jobs_marked": len(marked_stale),
        "unprocessed_issues_classified": len(classified),
        "classification_errors": classification_errors,
        "open_prs_scanned": len(pr_scans),
        "pr_scan_errors": pr_scan_errors,
        "blocked_prs": sum(1 for result in pr_scans if result["scan"]["blocked"]),
    }


def _mark_stale_if_needed(job: dict[str, Any]) -> dict[str, Any] | None:
    if job["status"] not in {"dispatched", "running"}:
        return None

    updated_at = datetime.fromisoformat(job["updated_at"])
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.stale_job_hours)
    if updated_at > cutoff:
        return None

    _try_comment_on_issue(
        job["issue_number"],
        "## Devin Automation Status\n\n"
        f"Job `{job['id']}` has not updated in {settings.stale_job_hours} hours. "
        "Automation marked it stale for human follow-up.\n\n"
        "---\n*Automated by superset-devin-automation*",
        "stale_job",
    )
    return tracker.update_job(job["id"], status="stale", error_message="Session stale")


def _try_add_labels(issue_number: int, labels: list[str], context: str) -> bool:
    try:
        github_client.add_labels(issue_number, labels)
        return True
    except Exception as e:
        logger.warning(
            "GitHub label write failed for issue/PR #%d during %s: %s",
            issue_number,
            context,
            e,
        )
        return False


def _try_comment_on_issue(issue_number: int, body: str, context: str) -> bool:
    try:
        github_client.comment_on_issue(issue_number, body)
        return True
    except Exception as e:
        logger.warning(
            "GitHub comment write failed for issue/PR #%d during %s: %s",
            issue_number,
            context,
            e,
        )
        return False


def _try_create_issue(title: str, body: str, labels: list[str], context: str) -> dict[str, Any] | None:
    try:
        return github_client.create_issue(title=title, body=body, labels=labels)
    except Exception as e:
        logger.warning("GitHub issue create failed during %s: %s", context, e)
        return None


def _classification_comment(result: classifier.IssueClassification, trigger_type: str) -> str:
    return (
        "## Devin Governance Classification\n\n"
        f"- **Priority**: `{result.priority}` - {result.priority_reason}\n"
        f"- **Complexity**: `{result.complexity}` - {result.complexity_reason}\n"
        f"- **Trigger**: `{trigger_type}`\n\n"
        "These labels drive Devin routing and human-review gates.\n\n"
        "---\n*Automated by superset-devin-automation*"
    )


def _dispatch_comment(
    classification: dict[str, Any],
    policy_data: dict[str, Any],
    session_id: str,
    session_url: str,
    trigger_type: str,
) -> str:
    mode_note = "Devin will create a plan first and wait for `run that plan` approval."
    if policy_data["devin_mode"] != "plan_only":
        mode_note = "Devin will create a focused PR or report why it cannot safely proceed."

    sim_prefix = "[SIMULATION MODE]\n\n" if settings.simulation_mode else ""

    return (
        f"{sim_prefix}## Devin Automation Dispatched\n\n"
        "### Classification\n"
        f"- **Priority**: `{classification['priority']}` - {classification['priority_reason']}\n"
        f"- **Complexity**: `{classification['complexity']}` - {classification['complexity_reason']}\n\n"
        "### Policy\n"
        f"- **Action**: `{policy_data['action']}`\n"
        f"- **Human review required**: `{policy_data['human_review_required']}`\n"
        f"- **Auto-merge candidate**: `{policy_data['auto_merge_candidate']}`\n"
        f"- **Auto-merge enabled**: `{policy_data['auto_merge_enabled']}`\n"
        f"- **Reason**: {policy_data['rationale']}\n\n"
        "### Devin Session\n"
        f"- **Session URL**: {session_url}\n"
        f"- **Session ID**: `{session_id}`\n"
        f"- **Trigger**: `{trigger_type}`\n\n"
        f"{mode_note}\n\n"
        "---\n*Automated by superset-devin-automation*"
    )


def _safety_block_comment(scan_data: dict[str, Any]) -> str:
    finding_lines = _finding_lines(scan_data["findings"])
    return (
        "## PR Safety Scan Blocked Auto-Merge\n\n"
        f"- **Prompt-injection findings**: `{scan_data['prompt_injection_count']}`\n"
        f"- **Malicious-code findings**: `{scan_data['malicious_code_count']}`\n\n"
        f"{finding_lines}\n\n"
        "A security review issue was created. Auto-merge should remain blocked until this PR is reviewed.\n\n"
        "---\n*Automated by superset-devin-automation*"
    )


def _security_issue_body(pr_data: dict[str, Any], scan_data: dict[str, Any]) -> str:
    return (
        "## Suspicious PR Content Detected\n\n"
        f"- **PR**: {pr_data.get('html_url', '')}\n"
        f"- **Prompt-injection findings**: `{scan_data['prompt_injection_count']}`\n"
        f"- **Malicious-code findings**: `{scan_data['malicious_code_count']}`\n\n"
        f"{_finding_lines(scan_data['findings'])}\n\n"
        "Review the diff before allowing auto-merge or Devin remediation.\n\n"
        "---\n*Automated by superset-devin-automation*"
    )


def _finding_lines(findings: list[dict[str, Any]]) -> str:
    if not findings:
        return "No findings."

    lines = ["### Findings"]
    for finding in findings[:10]:
        location = finding["file_path"]
        if finding.get("line_number"):
            location = f"{location}:{finding['line_number']}"
        lines.append(
            f"- `{finding['severity']}` `{finding['category']}` `{finding['rule']}` at `{location}`: "
            f"`{finding['excerpt']}`"
        )
    if len(findings) > 10:
        lines.append(f"- ...and {len(findings) - 10} more findings.")
    return "\n".join(lines)


def _label_names(issue_data: dict[str, Any]) -> set[str]:
    return {label["name"] for label in issue_data.get("labels", [])}


def _job_metadata(job: dict[str, Any]) -> dict[str, Any]:
    raw_meta = job.get("metadata") or "{}"
    if isinstance(raw_meta, dict):
        return raw_meta
    try:
        return json.loads(raw_meta)
    except json.JSONDecodeError:
        return {}
