from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from src import github_client, orchestrator, tracker


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GitHub Actions entrypoints for Superset Devin automation")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("issue-governance", help="Handle issue opened/labeled/comment approval events")
    subparsers.add_parser("pr-safety", help="Handle pull request safety scans")
    subparsers.add_parser("scheduled-recovery", help="Run scheduled recovery and write metrics summary")

    process_parser = subparsers.add_parser("process-issue", help="Process one issue without hosting the API")
    process_parser.add_argument("issue_number", type=int)
    process_parser.add_argument(
        "--action",
        choices=("fix", "plan", "implement_plan"),
        default="fix",
    )

    classify_parser = subparsers.add_parser("classify-issue", help="Classify one issue without hosting the API")
    classify_parser.add_argument("issue_number", type=int)

    args = parser.parse_args(argv)
    tracker.init_db()

    if args.command == "issue-governance":
        _print_json(_handle_issue_governance())
        return 0
    if args.command == "pr-safety":
        result = _handle_pr_safety()
        _print_json(result)
        return 1 if _pr_safety_blocked(result) else 0
    if args.command == "scheduled-recovery":
        result = _handle_scheduled_recovery()
        _print_json(result)
        return 0
    if args.command == "process-issue":
        action = None if args.action == "fix" else args.action
        issue = github_client.get_issue(args.issue_number)
        _print_json(orchestrator.process_issue(issue, "cli_manual", forced_action=action))
        return 0
    if args.command == "classify-issue":
        issue = github_client.get_issue(args.issue_number)
        _print_json(orchestrator.classify_issue_event(issue, "cli_manual"))
        return 0

    return 2


def _handle_issue_governance() -> dict[str, Any]:
    event = _github_event()
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")

    if event_name == "workflow_dispatch":
        inputs = event.get("inputs", {})
        if "issue_number" not in inputs:
            raise RuntimeError(
                "workflow_dispatch event missing required 'issue_number' input"
            )
        try:
            issue_number = int(inputs["issue_number"])
        except (ValueError, TypeError) as exc:
            raise RuntimeError(
                f"Invalid issue_number input '{inputs['issue_number']}': must be an integer"
            ) from exc
        action = inputs.get("action", "fix")
        issue = github_client.get_issue(issue_number)
        if action == "classify":
            return orchestrator.classify_issue_event(issue, "github_actions_manual_classify")
        if action == "plan":
            return orchestrator.process_issue(issue, "github_actions_manual_plan", forced_action="plan")
        if action == "implement_plan":
            return orchestrator.process_issue(
                issue,
                "github_actions_manual_plan_approval",
                forced_action="implement_plan",
            )
        return orchestrator.process_issue(issue, "github_actions_manual_fix")

    return orchestrator.handle_github_event(event_name, event)


def _handle_pr_safety() -> dict[str, Any]:
    event = _github_event()
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")

    if event_name == "workflow_dispatch":
        results = []
        for pr in github_client.list_open_pull_requests():
            results.append(orchestrator.scan_pr_safety(pr, "github_actions_manual_pr_safety_all"))
        return {
            "status": "completed",
            "mode": "all_open_pull_requests",
            "pull_requests_scanned": len(results),
            "blocked_prs": sum(1 for result in results if result["scan"]["blocked"]),
            "results": results,
        }

    pr = event.get("pull_request")
    if not pr:
        raise RuntimeError(
            f"Expected 'pull_request' key in event payload for event '{event_name}', "
            f"but it was missing. Available keys: {sorted(event.keys())}"
        )
    return orchestrator.scan_pr_safety(pr, "github_actions_pr")


def _pr_safety_blocked(result: dict[str, Any]) -> bool:
    if "scan" in result:
        return bool(result["scan"]["blocked"])
    return bool(result.get("blocked_prs", 0))


def _handle_scheduled_recovery() -> dict[str, Any]:
    summary = orchestrator.recover_scheduled_work()
    metrics = tracker.get_metrics()
    _write_actions_summary(metrics)
    return {"summary": summary, "metrics": metrics}


def _github_event() -> dict[str, Any]:
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise RuntimeError(
            f"GITHUB_EVENT_PATH is set to '{path}' but the file does not exist"
        )
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"GITHUB_EVENT_PATH file '{path}' contains invalid JSON: {exc}"
        ) from exc


def _write_actions_summary(metrics: dict[str, Any]) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    lines = [
        "# Devin Automation Scheduled Report",
        "",
        f"- Jobs: {metrics['total_jobs']}",
        f"- Issues classified: {metrics['issues_classified']}",
        f"- Devin sessions started: {metrics['devin_sessions_started']}",
        f"- PRs blocked by safety scans: {metrics['prs_blocked_by_safety_scans']}",
        f"- Plans waiting for approval: {metrics['plan_workflows_waiting_for_approval']}",
        f"- Latest job status: {metrics['latest_job_status']}",
        "",
    ]
    with open(summary_path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def _print_json(data: dict[str, Any]) -> None:
    print(json.dumps(data, indent=2, default=str))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
