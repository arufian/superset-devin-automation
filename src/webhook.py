from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

from src.config import settings

logger = logging.getLogger(__name__)


def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    if not settings.github_webhook_secret:
        logger.warning("No webhook secret configured, skipping signature verification")
        return True

    if not signature:
        return False

    expected = "sha256=" + hmac.new(
        settings.github_webhook_secret.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


def extract_issue_from_webhook(payload: dict[str, Any]) -> dict[str, Any] | None:
    action = payload.get("action")
    issue = payload.get("issue")

    if not issue:
        return None

    if action == "opened":
        return issue

    if action == "labeled":
        label = payload.get("label", {})
        if label.get("name") in {settings.trigger_label, settings.plan_label, settings.scan_label}:
            return issue

    return None


def is_issue_labeled_event(payload: dict[str, Any]) -> bool:
    return payload.get("action") == "labeled"


def labeled_name(payload: dict[str, Any]) -> str:
    return payload.get("label", {}).get("name", "")


def extract_pull_request_from_webhook(payload: dict[str, Any]) -> dict[str, Any] | None:
    if payload.get("action") not in {"opened", "synchronize", "reopened"}:
        return None
    return payload.get("pull_request")


def extract_issue_comment_approval(payload: dict[str, Any]) -> dict[str, Any] | None:
    if payload.get("action") != "created":
        return None

    issue = payload.get("issue") or {}
    if issue.get("pull_request"):
        return None

    comment = payload.get("comment") or {}
    body = (comment.get("body") or "").strip().lower()
    if body == "run that plan":
        return issue

    return None
