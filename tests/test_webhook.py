from __future__ import annotations

import hashlib
import hmac
import pytest
from src.webhook import (
    verify_webhook_signature,
    extract_issue_from_webhook,
    is_issue_labeled_event,
    labeled_name,
    extract_pull_request_from_webhook,
    extract_issue_comment_approval,
)
from src.config import settings


# ---------------------------------------------------------------------------
# verify_webhook_signature
# ---------------------------------------------------------------------------

class TestVerifyWebhookSignature:
    def test_valid_signature(self):
        original = settings.github_webhook_secret
        settings.github_webhook_secret = "test-secret"
        try:
            payload = b'{"action": "opened"}'
            sig = "sha256=" + hmac.new(b"test-secret", payload, hashlib.sha256).hexdigest()
            assert verify_webhook_signature(payload, sig) is True
        finally:
            settings.github_webhook_secret = original

    def test_invalid_signature(self):
        original = settings.github_webhook_secret
        settings.github_webhook_secret = "test-secret"
        try:
            assert verify_webhook_signature(b"payload", "sha256=invalid") is False
        finally:
            settings.github_webhook_secret = original

    def test_no_secret_configured(self):
        original = settings.github_webhook_secret
        settings.github_webhook_secret = ""
        try:
            assert verify_webhook_signature(b"anything", "") is True
        finally:
            settings.github_webhook_secret = original

    def test_empty_signature_with_secret(self):
        original = settings.github_webhook_secret
        settings.github_webhook_secret = "test-secret"
        try:
            assert verify_webhook_signature(b"payload", "") is False
        finally:
            settings.github_webhook_secret = original


# ---------------------------------------------------------------------------
# extract_issue_from_webhook
# ---------------------------------------------------------------------------

class TestExtractIssueFromWebhook:
    def test_opened_action(self):
        issue = {"number": 1, "title": "Bug"}
        payload = {"action": "opened", "issue": issue}
        assert extract_issue_from_webhook(payload) == issue

    def test_labeled_trigger_label(self):
        issue = {"number": 2, "title": "Fix"}
        payload = {
            "action": "labeled",
            "issue": issue,
            "label": {"name": settings.trigger_label},
        }
        assert extract_issue_from_webhook(payload) == issue

    def test_labeled_plan_label(self):
        issue = {"number": 3, "title": "Plan"}
        payload = {
            "action": "labeled",
            "issue": issue,
            "label": {"name": settings.plan_label},
        }
        assert extract_issue_from_webhook(payload) == issue

    def test_labeled_irrelevant_label(self):
        payload = {
            "action": "labeled",
            "issue": {"number": 4},
            "label": {"name": "wontfix"},
        }
        assert extract_issue_from_webhook(payload) is None

    def test_closed_action_ignored(self):
        payload = {"action": "closed", "issue": {"number": 5}}
        assert extract_issue_from_webhook(payload) is None

    def test_no_issue_key(self):
        assert extract_issue_from_webhook({"action": "opened"}) is None


# ---------------------------------------------------------------------------
# is_issue_labeled_event / labeled_name
# ---------------------------------------------------------------------------

class TestIsIssueLabeledEvent:
    def test_true(self):
        assert is_issue_labeled_event({"action": "labeled"}) is True

    def test_false(self):
        assert is_issue_labeled_event({"action": "opened"}) is False


class TestLabeledName:
    def test_returns_label_name(self):
        assert labeled_name({"label": {"name": "devin:fix"}}) == "devin:fix"

    def test_missing_label(self):
        assert labeled_name({}) == ""


# ---------------------------------------------------------------------------
# extract_pull_request_from_webhook
# ---------------------------------------------------------------------------

class TestExtractPullRequestFromWebhook:
    def test_opened(self):
        pr = {"number": 10}
        payload = {"action": "opened", "pull_request": pr}
        assert extract_pull_request_from_webhook(payload) == pr

    def test_synchronize(self):
        pr = {"number": 11}
        payload = {"action": "synchronize", "pull_request": pr}
        assert extract_pull_request_from_webhook(payload) == pr

    def test_reopened(self):
        pr = {"number": 12}
        payload = {"action": "reopened", "pull_request": pr}
        assert extract_pull_request_from_webhook(payload) == pr

    def test_closed_ignored(self):
        payload = {"action": "closed", "pull_request": {"number": 13}}
        assert extract_pull_request_from_webhook(payload) is None


# ---------------------------------------------------------------------------
# extract_issue_comment_approval
# ---------------------------------------------------------------------------

class TestExtractIssueCommentApproval:
    def test_run_that_plan(self):
        issue = {"number": 20}
        payload = {
            "action": "created",
            "issue": issue,
            "comment": {"body": "run that plan"},
        }
        assert extract_issue_comment_approval(payload) == issue

    def test_case_insensitive(self):
        issue = {"number": 21}
        payload = {
            "action": "created",
            "issue": issue,
            "comment": {"body": "Run That Plan"},
        }
        assert extract_issue_comment_approval(payload) == issue

    def test_wrong_body(self):
        payload = {
            "action": "created",
            "issue": {"number": 22},
            "comment": {"body": "looks good to me"},
        }
        assert extract_issue_comment_approval(payload) is None

    def test_edited_action_ignored(self):
        payload = {
            "action": "edited",
            "issue": {"number": 23},
            "comment": {"body": "run that plan"},
        }
        assert extract_issue_comment_approval(payload) is None

    def test_pr_comment_ignored(self):
        payload = {
            "action": "created",
            "issue": {"number": 24, "pull_request": {"url": "..."}},
            "comment": {"body": "run that plan"},
        }
        assert extract_issue_comment_approval(payload) is None
