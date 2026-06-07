from __future__ import annotations

import pytest
from src.policy import PolicyDecision, decide, _matrix_rationale


class TestDecide:
    def test_forced_plan(self):
        d = decide("high", "very-complex", forced_action="plan")
        assert d.action == "plan"
        assert d.devin_mode == "plan_only"
        assert d.approval_required_before_implementation is True
        assert d.auto_merge_candidate is False

    def test_forced_implement_plan(self):
        d = decide("high", "very-complex", forced_action="implement_plan")
        assert d.action == "implement_plan"
        assert d.devin_mode == "implementation_after_approval"
        assert d.approval_required_before_implementation is False
        assert d.human_review_required is True

    def test_high_very_complex_auto_plan(self):
        d = decide("high", "very-complex")
        assert d.action == "plan"
        assert d.devin_mode == "plan_only"
        assert d.approval_required_before_implementation is True

    def test_low_simple_auto_merge_candidate(self):
        d = decide("low", "simple")
        assert d.auto_merge_candidate is True
        assert d.action == "fix_pr"
        assert d.human_review_required is False

    def test_low_medium_auto_merge_candidate(self):
        d = decide("low", "medium")
        assert d.auto_merge_candidate is True

    def test_medium_simple_no_review_required(self):
        d = decide("medium", "simple")
        assert d.human_review_required is False
        assert d.action == "fix_pr"

    def test_medium_medium_review_required(self):
        d = decide("medium", "medium")
        assert d.human_review_required is True
        assert d.action == "fix_pr_human_review"

    def test_medium_very_complex_review_required(self):
        d = decide("medium", "very-complex")
        assert d.human_review_required is True
        assert d.action == "fix_pr_human_review"

    def test_high_simple_review_required(self):
        d = decide("high", "simple")
        assert d.human_review_required is True
        assert d.auto_merge_candidate is False

    def test_high_medium_review_required(self):
        d = decide("high", "medium")
        assert d.human_review_required is True
        assert d.auto_merge_candidate is False


class TestPolicyDecisionAsDict:
    def test_as_dict_contains_all_fields(self):
        d = decide("low", "simple")
        data = d.as_dict()
        assert "action" in data
        assert "devin_mode" in data
        assert "human_review_required" in data
        assert "auto_merge_candidate" in data
        assert "auto_merge_enabled" in data
        assert "approval_required_before_implementation" in data
        assert "rationale" in data


class TestMatrixRationale:
    def test_auto_merge_candidate_rationale(self):
        r = _matrix_rationale("low", "simple", False, True)
        assert "auto-merge" in r.lower()

    def test_review_required_rationale(self):
        r = _matrix_rationale("high", "medium", True, False)
        assert "human review" in r.lower()

    def test_default_rationale(self):
        r = _matrix_rationale("medium", "simple", False, False)
        assert "focused pr" in r.lower()
