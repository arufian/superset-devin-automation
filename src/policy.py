from __future__ import annotations

from dataclasses import asdict, dataclass

from src.config import settings


@dataclass(frozen=True)
class PolicyDecision:
    action: str
    devin_mode: str
    human_review_required: bool
    auto_merge_candidate: bool
    auto_merge_enabled: bool
    approval_required_before_implementation: bool
    rationale: str

    def as_dict(self) -> dict[str, str | bool]:
        return asdict(self)


def decide(
    priority: str,
    complexity: str,
    *,
    forced_action: str | None = None,
) -> PolicyDecision:
    if forced_action == "plan":
        return PolicyDecision(
            action="plan",
            devin_mode="plan_only",
            human_review_required=True,
            auto_merge_candidate=False,
            auto_merge_enabled=False,
            approval_required_before_implementation=True,
            rationale="`devin:plan` label requested plan-first workflow.",
        )

    if forced_action == "implement_plan":
        return PolicyDecision(
            action="implement_plan",
            devin_mode="implementation_after_approval",
            human_review_required=True,
            auto_merge_candidate=False,
            auto_merge_enabled=False,
            approval_required_before_implementation=False,
            rationale="Human approved prior plan with `run that plan`.",
        )

    if priority == "high" and complexity == "very-complex":
        return PolicyDecision(
            action="plan",
            devin_mode="plan_only",
            human_review_required=True,
            auto_merge_candidate=False,
            auto_merge_enabled=False,
            approval_required_before_implementation=True,
            rationale="High-priority, very-complex work requires plan approval before implementation.",
        )

    auto_merge_candidate = priority == "low" and complexity in {"simple", "medium"}
    review_required = priority == "high" or complexity in {"medium", "very-complex"}

    if priority == "medium" and complexity == "simple":
        review_required = False

    action = "fix_pr"
    if review_required:
        action = "fix_pr_human_review"

    return PolicyDecision(
        action=action,
        devin_mode="focused_fix",
        human_review_required=review_required,
        auto_merge_candidate=auto_merge_candidate,
        auto_merge_enabled=bool(settings.auto_merge_enabled and auto_merge_candidate),
        approval_required_before_implementation=False,
        rationale=_matrix_rationale(priority, complexity, review_required, auto_merge_candidate),
    )


def _matrix_rationale(
    priority: str,
    complexity: str,
    review_required: bool,
    auto_merge_candidate: bool,
) -> str:
    if auto_merge_candidate:
        return "Low-priority simple/medium work may be auto-merge candidate when safety checks pass and auto-merge is enabled."
    if review_required:
        return "Policy matrix requires human review for this priority/complexity pair."
    return "Policy matrix allows Devin to create focused PR; human review recommended."
