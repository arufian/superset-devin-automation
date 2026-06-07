from __future__ import annotations

import logging
from typing import Any

from src.config import settings
from src import tracker, devin_client, github_client

logger = logging.getLogger(__name__)


def process_issue(issue_data: dict[str, Any], trigger_type: str) -> dict[str, Any]:
    issue_number = issue_data["number"]
    issue_title = issue_data["title"]
    issue_body = issue_data.get("body", "") or ""
    issue_url = issue_data["html_url"]

    existing = tracker.get_job_by_issue(issue_number)
    if existing and existing["status"] in ("pending", "running", "dispatched"):
        logger.info("Issue #%d already has active job %d, skipping", issue_number, existing["id"])
        return existing

    job = tracker.create_job(
        issue_number=issue_number,
        issue_url=issue_url,
        issue_title=issue_title,
        trigger_type=trigger_type,
        metadata={
            "labels": [l["name"] for l in issue_data.get("labels", [])],
            "assignee": issue_data.get("assignee", {}).get("login") if issue_data.get("assignee") else None,
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
        )

        session = devin_client.create_session(
            prompt=prompt,
            title=f"Fix superset#{issue_number}: {issue_title}",
            tags=["superset-automation", f"issue-{issue_number}"],
        )

        session_id = session["session_id"]
        session_url = session["url"]

        tracker.update_job(
            job["id"],
            status="dispatched",
            devin_session_id=session_id,
            devin_session_url=session_url,
            devin_status=session.get("status"),
            devin_status_detail=session.get("status_detail"),
        )

        comment_body = (
            f"## Devin Automation Dispatched\n\n"
            f"A Devin session has been created to work on this issue.\n\n"
            f"- **Session URL**: {session_url}\n"
            f"- **Session ID**: `{session_id}`\n"
            f"- **Trigger**: `{trigger_type}`\n\n"
            f"Devin will analyze the issue, create a branch, and submit a PR if the fix is straightforward. "
            f"If it cannot safely proceed, it will report back here.\n\n"
            f"---\n*Automated by superset-devin-automation*"
        )

        if settings.simulation_mode:
            comment_body = f"[SIMULATION MODE]\n\n{comment_body}"

        github_client.comment_on_issue(issue_number, comment_body)
        logger.info("Commented on issue #%d with session info", issue_number)

        return tracker.get_job(job["id"])

    except Exception as e:
        logger.error("Failed to process issue #%d: %s", issue_number, e, exc_info=True)
        tracker.update_job(
            job["id"],
            status="failed",
            error_message=str(e),
        )
        github_client.comment_on_issue(
            issue_number,
            f"## Devin Automation Failed\n\n"
            f"The automation encountered an error while dispatching this issue to Devin.\n\n"
            f"**Error**: `{e}`\n\n"
            f"This issue will need manual attention.\n\n"
            f"---\n*Automated by superset-devin-automation*",
        )
        return tracker.get_job(job["id"])


def sync_session_status(job: dict[str, Any]) -> dict[str, Any] | None:
    if not job.get("devin_session_id"):
        return None

    try:
        session = devin_client.get_session(job["devin_session_id"])
        new_status = session.get("status", "unknown")
        new_detail = session.get("status_detail")

        updates: dict[str, Any] = {
            "devin_status": new_status,
            "devin_status_detail": new_detail,
        }

        if new_status == "exit":
            if new_detail == "finished":
                updates["status"] = "completed"
            else:
                updates["status"] = "devin_exited"
        elif new_status == "error":
            updates["status"] = "failed"
            updates["error_message"] = f"Devin error: {new_detail}"
        elif new_status in ("running", "claimed"):
            updates["status"] = "running"

        prs = session.get("pull_requests", [])
        if prs:
            meta = job.get("metadata", "{}")
            import json
            meta_dict = json.loads(meta) if isinstance(meta, str) else meta
            meta_dict["pull_requests"] = prs
            updates["metadata"] = meta_dict

        return tracker.update_job(job["id"], **updates)

    except Exception as e:
        logger.error("Failed to sync session for job %d: %s", job["id"], e)
        return None


def scan_ready_issues() -> list[dict[str, Any]]:
    logger.info("Scanning for issues labeled '%s'", settings.scan_label)
    issues = github_client.list_issues_with_label(settings.scan_label)
    results = []
    for issue in issues:
        result = process_issue(issue, trigger_type="scheduled_scan")
        results.append(result)
    logger.info("Scan complete: %d issues processed", len(results))
    return results
