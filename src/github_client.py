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


def _api_url(path: str) -> str:
    return f"https://api.github.com/repos/{settings.github_repo}/{path}"


def get_issue(issue_number: int) -> dict[str, Any]:
    url = _api_url(f"issues/{issue_number}")
    with httpx.Client(timeout=30) as client:
        resp = client.get(url, headers=_headers())
        resp.raise_for_status()
        return resp.json()


def comment_on_issue(issue_number: int, body: str) -> dict[str, Any]:
    if settings.simulation_mode:
        logger.info("[SIM] Would comment on issue #%d: %s", issue_number, body[:100])
        return {"id": 0, "body": body, "html_url": f"https://github.com/{settings.github_repo}/issues/{issue_number}#sim"}

    url = _api_url(f"issues/{issue_number}/comments")
    with httpx.Client(timeout=30) as client:
        resp = client.post(url, json={"body": body}, headers=_headers())
        resp.raise_for_status()
        return resp.json()


def list_issues_with_label(label: str, state: str = "open") -> list[dict[str, Any]]:
    url = _api_url(f"issues?labels={label}&state={state}&per_page=50")
    with httpx.Client(timeout=30) as client:
        resp = client.get(url, headers=_headers())
        resp.raise_for_status()
        return resp.json()


def add_label(issue_number: int, label: str) -> None:
    if settings.simulation_mode:
        logger.info("[SIM] Would add label '%s' to issue #%d", label, issue_number)
        return

    url = _api_url(f"issues/{issue_number}/labels")
    with httpx.Client(timeout=30) as client:
        resp = client.post(url, json={"labels": [label]}, headers=_headers())
        resp.raise_for_status()


def remove_label(issue_number: int, label: str) -> None:
    if settings.simulation_mode:
        logger.info("[SIM] Would remove label '%s' from issue #%d", label, issue_number)
        return

    url = _api_url(f"issues/{issue_number}/labels/{label}")
    with httpx.Client(timeout=30) as client:
        resp = client.delete(url, headers=_headers())
        if resp.status_code != 404:
            resp.raise_for_status()
