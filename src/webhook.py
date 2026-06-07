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

    if action == "labeled":
        label = payload.get("label", {})
        if label.get("name") == settings.trigger_label:
            return issue

    return None


def is_issue_labeled_event(payload: dict[str, Any]) -> bool:
    return payload.get("action") == "labeled"
