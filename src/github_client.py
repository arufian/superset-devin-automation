from __future__ import annotations

import logging
from typing import Any

import httpx

from src.config import settings

logger = logging.getLogger(__name__)


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": "application/vnd.github+json",
    }


def _is_user_owned_token() -> bool:
    token = settings.github_token
    return token.startswith(("github_pat_", "ghp_", "gho_", "ghu_"))


def _ensure_visible_write_allowed(action: str) -> None:
    if settings.allow_user_token_writes or not _is_user_owned_token():
        return

    raise RuntimeError(
        f"Refusing to {action} with a user-owned GitHub token. "
        "Use GitHub Actions' github.token or a GitHub App installation token so visible writes "
        "do not appear from a personal account. Set ALLOW_USER_TOKEN_WRITES=true only for "
        "intentional local/manual runs."
    )


def _api_url(path: str) -> str:
    return f"https://api.github.com/repos/{settings.github_repo}/{path}"


def _raise_for_status(resp: httpx.Response, action: str) -> None:
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = resp.text[:300].replace("\n", " ")
        message = f"GitHub API {resp.status_code} during {action} for {settings.github_repo}: {detail}"
        if resp.status_code == 403:
            message += (
                " Check GH_PAT repository access and permissions. "
                "For cross-repo automation it needs Issues read/write on the target repo."
            )
        raise RuntimeError(message) from exc


def _request(
    method: str,
    path: str,
    action: str,
    *,
    json: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    headers_override: dict[str, str] | None = None,
    timeout: int = 30,
    ignore_status: int | None = None,
) -> httpx.Response:
    url = _api_url(path)
    hdrs = headers_override or _headers()
    with httpx.Client(timeout=timeout) as client:
        resp = client.request(method, url, json=json, params=params, headers=hdrs)
        if ignore_status is not None and resp.status_code == ignore_status:
            return resp
        _raise_for_status(resp, action)
        return resp


def get_issue(issue_number: int) -> dict[str, Any]:
    if settings.simulation_mode:
        return _simulate_issue(issue_number)

    return _request("GET", f"issues/{issue_number}", f"get issue #{issue_number}").json()


def comment_on_issue(issue_number: int, body: str) -> dict[str, Any]:
    if settings.simulation_mode:
        logger.info("[SIM] Would comment on issue #%d: %s", issue_number, body[:100])
        return {"id": 0, "body": body, "html_url": f"https://github.com/{settings.github_repo}/issues/{issue_number}#sim"}

    _ensure_visible_write_allowed(f"comment on issue/PR #{issue_number}")
    return _request(
        "POST", f"issues/{issue_number}/comments",
        f"comment on issue/PR #{issue_number}",
        json={"body": body},
    ).json()


def list_issues_with_label(label: str, state: str = "open") -> list[dict[str, Any]]:
    if settings.simulation_mode:
        issue = _simulate_issue(1)
        issue["labels"] = [{"name": label}]
        return [issue]

    return _request(
        "GET", "issues", f"list issues with label {label}",
        params={"labels": label, "state": state, "per_page": 50},
    ).json()


def add_labels(issue_number: int, labels: list[str]) -> None:
    labels = [label for label in labels if label]
    if not labels:
        return

    if settings.simulation_mode:
        logger.info("[SIM] Would add labels %s to issue #%d", labels, issue_number)
        return

    _ensure_visible_write_allowed(f"add labels to issue/PR #{issue_number}")
    _request(
        "POST", f"issues/{issue_number}/labels",
        f"add labels to issue/PR #{issue_number}",
        json={"labels": labels},
    )


def add_label(issue_number: int, label: str) -> None:
    add_labels(issue_number, [label])


def remove_label(issue_number: int, label: str) -> None:
    if settings.simulation_mode:
        logger.info("[SIM] Would remove label '%s' from issue #%d", label, issue_number)
        return

    _ensure_visible_write_allowed(f"remove label from issue/PR #{issue_number}")
    _request(
        "DELETE", f"issues/{issue_number}/labels/{label}",
        f"remove label from issue/PR #{issue_number}",
        ignore_status=404,
    )


def create_issue(title: str, body: str, labels: list[str] | None = None) -> dict[str, Any]:
    if settings.simulation_mode:
        logger.info("[SIM] Would create issue: %s", title)
        return {
            "number": 999,
            "title": title,
            "body": body,
            "labels": [{"name": label} for label in labels or []],
            "html_url": f"https://github.com/{settings.github_repo}/issues/999#sim",
        }

    _ensure_visible_write_allowed("create issue")
    payload: dict[str, Any] = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels
    return _request("POST", "issues", "create issue", json=payload).json()


def get_pull_request_diff(pr_number: int) -> str:
    if settings.simulation_mode:
        return (
            "diff --git a/superset/example.py b/superset/example.py\n"
            "@@ -1,2 +1,2 @@\n"
            "+print('safe simulated diff')\n"
        )

    headers = _headers()
    headers["Accept"] = "application/vnd.github.v3.diff"
    return _request(
        "GET", f"pulls/{pr_number}", f"get PR #{pr_number} diff",
        headers_override=headers,
    ).text


def get_pull_request(pr_number: int) -> dict[str, Any]:
    if settings.simulation_mode:
        return {
            "number": pr_number,
            "title": f"Simulated PR #{pr_number}",
            "html_url": f"https://github.com/{settings.github_repo}/pull/{pr_number}#sim",
        }

    return _request("GET", f"pulls/{pr_number}", f"get PR #{pr_number}").json()


def list_open_pull_requests() -> list[dict[str, Any]]:
    if settings.simulation_mode:
        return []

    pull_requests: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = _request(
            "GET", "pulls", "list open PRs",
            params={"state": "open", "per_page": 100, "page": page},
        ).json()
        pull_requests.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return pull_requests


def list_open_issues(per_page: int = 50) -> list[dict[str, Any]]:
    if settings.simulation_mode:
        return [_simulate_issue(1)]

    resp = _request(
        "GET", "issues", "list open issues",
        params={"state": "open", "per_page": per_page},
    )
    return [issue for issue in resp.json() if "pull_request" not in issue]


def _simulate_issue(issue_number: int) -> dict[str, Any]:
    return {
        "number": issue_number,
        "title": "Replace deprecated datetime.utcnow() in utils/dates.py",
        "body": "Small maintenance issue: replace deprecated datetime.utcnow() and add test coverage.",
        "labels": [{"name": settings.scan_label}],
        "html_url": f"https://github.com/{settings.github_repo}/issues/{issue_number}#sim",
        "assignee": None,
    }
