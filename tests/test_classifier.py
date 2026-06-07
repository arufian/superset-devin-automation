from __future__ import annotations

import pytest
from src.classifier import (
    IssueClassification,
    classify_issue,
    classification_labels,
    _infer_priority,
    _infer_complexity,
    _matches,
)


# ---------------------------------------------------------------------------
# _matches helper
# ---------------------------------------------------------------------------

class TestMatches:
    def test_returns_first_matching_term(self):
        assert _matches("fix the typo in readme", ("typo", "readme")) == "typo"

    def test_returns_none_when_no_match(self):
        assert _matches("hello world", ("foo", "bar")) is None

    def test_empty_terms(self):
        assert _matches("anything", ()) is None

    def test_empty_text(self):
        assert _matches("", ("foo",)) is None


# ---------------------------------------------------------------------------
# _infer_priority
# ---------------------------------------------------------------------------

class TestInferPriority:
    def test_high_security_keyword(self):
        pri, reason = _infer_priority("there is a security vulnerability here")
        assert pri == "priority:high"
        assert "security" in reason.lower()

    def test_high_rce(self):
        pri, _ = _infer_priority("possible rce in serializer")
        assert pri == "priority:high"

    def test_medium_bug(self):
        pri, reason = _infer_priority("this is a bug in the chart component")
        assert pri == "priority:medium"
        assert "bug" in reason.lower()

    def test_medium_regression(self):
        pri, _ = _infer_priority("regression after latest merge")
        assert pri == "priority:medium"

    def test_low_no_signals(self):
        pri, reason = _infer_priority("add a new feature for dashboards")
        assert pri == "priority:low"
        assert "no production" in reason.lower()


# ---------------------------------------------------------------------------
# _infer_complexity
# ---------------------------------------------------------------------------

class TestInferComplexity:
    def test_very_complex_migration(self):
        comp, reason = _infer_complexity("needs a database migration")
        assert comp == "complexity:very-complex"
        assert "migration" in reason.lower()

    def test_very_complex_refactor(self):
        comp, _ = _infer_complexity("large scale refactor of the query engine")
        assert comp == "complexity:very-complex"

    def test_simple_docs(self):
        comp, reason = _infer_complexity("fix the documentation typo")
        assert comp == "complexity:simple"
        assert "documentation" in reason.lower() or "typo" in reason.lower()

    def test_simple_typo(self):
        comp, _ = _infer_complexity("typo in README")
        assert comp == "complexity:simple"

    def test_medium_default(self):
        comp, reason = _infer_complexity("improve dashboard loading speed")
        assert comp == "complexity:medium"
        assert "code inspection" in reason.lower()


# ---------------------------------------------------------------------------
# classify_issue (integration of the above)
# ---------------------------------------------------------------------------

class TestClassifyIssue:
    def test_label_override_priority(self):
        issue = {
            "title": "Some issue",
            "body": "nothing special",
            "labels": [{"name": "priority:high"}],
        }
        result = classify_issue(issue)
        assert result.priority == "priority:high"
        assert "label present" in result.priority_reason.lower()

    def test_label_override_complexity(self):
        issue = {
            "title": "Some issue",
            "body": "nothing special",
            "labels": [{"name": "complexity:simple"}],
        }
        result = classify_issue(issue)
        assert result.complexity == "complexity:simple"
        assert "label present" in result.complexity_reason.lower()

    def test_infers_from_text_when_no_labels(self):
        issue = {
            "title": "SQL injection vulnerability",
            "body": "Critical security flaw found",
            "labels": [],
        }
        result = classify_issue(issue)
        assert result.priority == "priority:high"

    def test_missing_body_is_tolerated(self):
        issue = {"title": "Fix typo", "labels": []}
        result = classify_issue(issue)
        assert result.complexity == "complexity:simple"

    def test_none_body_is_tolerated(self):
        issue = {"title": "Fix typo", "body": None, "labels": []}
        result = classify_issue(issue)
        assert isinstance(result, IssueClassification)

    def test_as_dict(self):
        result = IssueClassification(
            priority="priority:low",
            complexity="complexity:medium",
            priority_reason="r1",
            complexity_reason="r2",
        )
        d = result.as_dict()
        assert d["priority"] == "priority:low"
        assert d["complexity_reason"] == "r2"


# ---------------------------------------------------------------------------
# classification_labels
# ---------------------------------------------------------------------------

class TestClassificationLabels:
    def test_returns_priority_and_complexity(self):
        c = IssueClassification(
            priority="priority:medium",
            complexity="complexity:simple",
            priority_reason="",
            complexity_reason="",
        )
        labels = classification_labels(c)
        assert labels == ["priority:medium", "complexity:simple"]
