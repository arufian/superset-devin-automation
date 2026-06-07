from __future__ import annotations

import logging
from typing import Any

import httpx

from src.config import settings

logger = logging.getLogger(__name__)


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.devin_api_key}",
        "Content-Type": "application/json",
    }


def _base_url() -> str:
    return f"{settings.devin_base_url}/v3/organizations/{settings.devin_org_id}"


def build_prompt(
    repo_url: str,
    issue_number: int,
    issue_title: str,
    issue_body: str,
    issue_url: str,
) -> str:
    return f"""You are assigned to fix a GitHub issue in the Superset fork repository.

## Repository
{repo_url}

## Issue #{issue_number}: {issue_title}
URL: {issue_url}

### Issue Description
{issue_body}

## Instructions
1. Clone the repository and check out a new branch named `devin/fix-issue-{issue_number}`
2. Analyze the issue and implement a focused, minimal fix
3. Run existing tests to ensure nothing breaks
4. Create a pull request targeting the `master` branch
5. If you cannot safely proceed (e.g., ambiguous requirements, risky changes), report why in a comment on the issue instead of making changes

## Constraints
- Keep changes small and reviewable
- Do not make unrelated changes
- Follow existing code conventions
- Include tests for any code changes
"""


def create_session(
    prompt: str,
    title: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    if settings.simulation_mode:
        return _simulate_session(title or "Simulated Session")

    url = f"{_base_url()}/sessions"
    payload: dict[str, Any] = {
        "prompt": prompt,
        "tags": tags or ["superset-automation"],
    }
    if title:
        payload["title"] = title

    logger.info("Creating Devin session: %s", url)
    with httpx.Client(timeout=60) as client:
        resp = client.post(url, json=payload, headers=_headers())
        resp.raise_for_status()
        data = resp.json()
        logger.info("Session created: %s", data.get("session_id"))
        return data


def get_session(session_id: str) -> dict[str, Any]:
    if settings.simulation_mode:
        return {
            "session_id": session_id,
            "url": f"https://app.devin.ai/sessions/{session_id}",
            "status": "running",
            "status_detail": "working",
            "tags": ["superset-automation"],
            "org_id": settings.devin_org_id or "org-simulated",
            "created_at": 0,
            "updated_at": 0,
            "acus_consumed": 0.0,
            "pull_requests": [],
        }

    url = f"{_base_url()}/sessions/{session_id}"
    with httpx.Client(timeout=30) as client:
        resp = client.get(url, headers=_headers())
        resp.raise_for_status()
        return resp.json()


def _simulate_session(title: str) -> dict[str, Any]:
    import time
    sim_id = f"sim-{int(time.time())}"
    return {
        "session_id": sim_id,
        "url": f"https://app.devin.ai/sessions/{sim_id}",
        "status": "running",
        "status_detail": "working",
        "title": title,
        "tags": ["superset-automation", "simulated"],
        "org_id": settings.devin_org_id or "org-simulated",
        "created_at": int(time.time()),
        "updated_at": int(time.time()),
        "acus_consumed": 0.0,
        "pull_requests": [],
    }
