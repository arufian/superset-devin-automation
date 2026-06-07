from __future__ import annotations

import pytest
from src.devin_client import build_prompt, _expected_output_for_mode


class TestExpectedOutputForMode:
    def test_plan_only(self):
        result = _expected_output_for_mode("plan_only")
        assert "plan" in result.lower()
        assert "pr" not in result.lower()

    def test_implementation_after_approval(self):
        result = _expected_output_for_mode("implementation_after_approval")
        assert "pr" in result.lower()
        assert "approved plan" in result.lower()

    def test_focused_fix(self):
        result = _expected_output_for_mode("focused_fix")
        assert "fix" in result.lower()

    def test_unknown_mode_defaults_to_focused(self):
        result = _expected_output_for_mode("anything_else")
        assert "fix" in result.lower()


class TestBuildPrompt:
    def test_contains_issue_info(self):
        prompt = build_prompt(
            repo_url="https://github.com/test/repo",
            issue_number=42,
            issue_title="Fix the bug",
            issue_body="Something is broken",
            issue_url="https://github.com/test/repo/issues/42",
        )
        assert "Issue #42" in prompt
        assert "Fix the bug" in prompt
        assert "Something is broken" in prompt
        assert "https://github.com/test/repo" in prompt

    def test_includes_classification(self):
        prompt = build_prompt(
            repo_url="url",
            issue_number=1,
            issue_title="title",
            issue_body="body",
            issue_url="issue_url",
            classification={"priority": "high", "complexity": "simple", "priority_reason": "sec", "complexity_reason": "small"},
        )
        assert "high" in prompt
        assert "simple" in prompt

    def test_includes_policy(self):
        prompt = build_prompt(
            repo_url="url",
            issue_number=1,
            issue_title="title",
            issue_body="body",
            issue_url="issue_url",
            policy={"action": "plan", "devin_mode": "plan_only", "human_review_required": True},
        )
        assert "plan" in prompt

    def test_defaults_without_classification_or_policy(self):
        prompt = build_prompt(
            repo_url="url",
            issue_number=1,
            issue_title="t",
            issue_body="b",
            issue_url="u",
        )
        assert "unknown" in prompt
        assert "focused_fix" in prompt

    def test_contains_constraints(self):
        prompt = build_prompt(
            repo_url="url",
            issue_number=1,
            issue_title="t",
            issue_body="b",
            issue_url="u",
        )
        assert "Constraints" in prompt
        assert "Do not merge the PR yourself" in prompt
