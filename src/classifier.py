from __future__ import annotations

from dataclasses import dataclass
from typing import Any


PRIORITIES = ("priority:low", "priority:medium", "priority:high")
COMPLEXITIES = ("complexity:simple", "complexity:medium", "complexity:very-complex")


@dataclass(frozen=True)
class IssueClassification:
    priority: str
    complexity: str
    priority_reason: str
    complexity_reason: str

    def as_dict(self) -> dict[str, str]:
        return {
            "priority": self.priority,
            "complexity": self.complexity,
            "priority_reason": self.priority_reason,
            "complexity_reason": self.complexity_reason,
        }


def classify_issue(issue_data: dict[str, Any]) -> IssueClassification:
    labels = {label["name"] for label in issue_data.get("labels", [])}
    title = issue_data.get("title", "") or ""
    body = issue_data.get("body", "") or ""
    text = f"{title}\n{body}".lower()

    priority_override = next((label for label in labels if label in PRIORITIES), None)
    complexity_override = next((label for label in labels if label in COMPLEXITIES), None)

    if priority_override:
        priority = priority_override
        priority_reason = f"Existing `{priority_override}` label present."
    else:
        priority, priority_reason = _infer_priority(text)

    if complexity_override:
        complexity = complexity_override
        complexity_reason = f"Existing `{complexity_override}` label present."
    else:
        complexity, complexity_reason = _infer_complexity(text)

    return IssueClassification(
        priority=priority,
        complexity=complexity,
        priority_reason=priority_reason,
        complexity_reason=complexity_reason,
    )


def classification_labels(classification: IssueClassification) -> list[str]:
    return [classification.priority, classification.complexity]


def _infer_priority(text: str) -> tuple[str, str]:
    high_terms = (
        "security",
        "vulnerability",
        "cve",
        "rce",
        "sql injection",
        "data loss",
        "outage",
        "production down",
        "critical",
        "blocker",
        "p0",
        "p1",
        "authentication bypass",
        "privilege escalation",
    )
    medium_terms = (
        "bug",
        "regression",
        "failing test",
        "broken",
        "incorrect",
        "performance",
        "timeout",
        "dependency",
        "deprecation",
        "flaky",
        "missing test",
        "type error",
    )

    matched_high = _matches(text, high_terms)
    if matched_high:
        return "priority:high", f"High-impact keyword matched: `{matched_high}`."

    matched_medium = _matches(text, medium_terms)
    if matched_medium:
        return "priority:medium", f"Engineering-risk keyword matched: `{matched_medium}`."

    return "priority:low", "No production, security, or regression signal found."


def _infer_complexity(text: str) -> tuple[str, str]:
    very_complex_terms = (
        "architecture",
        "migration",
        "database migration",
        "auth",
        "authentication",
        "authorization",
        "query engine",
        "scheduler",
        "celery",
        "distributed",
        "refactor",
        "breaking change",
        "cross-cutting",
        "multiple modules",
    )
    simple_terms = (
        "docs",
        "documentation",
        "typo",
        "copy",
        "readme",
        "add test",
        "unit test",
        "deprecated",
        "datetime.utcnow",
        "type hint",
        "lint",
        "format",
    )

    matched_very_complex = _matches(text, very_complex_terms)
    if matched_very_complex:
        return "complexity:very-complex", f"Broad or risky area matched: `{matched_very_complex}`."

    matched_simple = _matches(text, simple_terms)
    if matched_simple:
        return "complexity:simple", f"Small-scope keyword matched: `{matched_simple}`."

    return "complexity:medium", "Issue likely needs code inspection but no broad-risk signal was found."


def _matches(text: str, terms: tuple[str, ...]) -> str | None:
    return next((term for term in terms if term in text), None)
