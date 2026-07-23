# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Eval Case and Eval Result schemas.

An EvalCase asks one governance question about one agent's work in one
workflow: is the handoff complete, is the observation disciplined, did the
agent stay at its depth, did it escalate correctly, is complexity being
reduced rather than accumulated?

The evaluation goal (docs/evaluation-strategy.md) is workflow quality, not
model output quality. The key question every case ultimately serves:

    Can another agent or human continue the work without reconstructing
    missing context?

An EvalResult is the recorded answer: per-check outcomes with evidence,
persisted to the ledger so promotion decisions cite eval history instead of
vibes.
"""

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class CheckCategory(str, Enum):
    """The five default checks from the evaluation strategy."""

    HANDOFF_COMPLETENESS = "handoff_completeness"
    OBSERVATION_DISCIPLINE = "observation_discipline"
    DEPTH_COMPLIANCE = "depth_compliance"
    ESCALATION_CORRECTNESS = "escalation_correctness"
    COMPLEXITY_REDUCTION = "complexity_reduction"


class CheckOutcome(str, Enum):
    """Result of one check within an eval run."""

    PASS = "pass"
    FAIL = "fail"
    SKIPPED = "skipped"


class ExpectedOutputs(BaseModel):
    """What the eval case expects of the work under evaluation."""

    required_fields: list[str] = Field(
        default_factory=list,
        description="Strings that must appear in the run's handoff (e.g. evidence labels).",
    )
    forbidden_claims: list[str] = Field(
        default_factory=list,
        description=(
            "Claims that must NOT appear anywhere in the handoff or "
            "observations — the unsupported-completion-claim detector. "
            "Matched case-insensitively."
        ),
    )
    expected_escalation: str = Field(
        default="",
        description="Who the agent is expected to escalate to when blocked.",
    )
    expected_depth: int | None = Field(
        default=None,
        ge=0,
        le=5,
        description="The depth level the agent is expected to operate at.",
    )


class EvalCase(BaseModel):
    """One governance question, asked repeatably (eval case YAML format)."""

    case_id: str = Field(
        pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$",
        description="Unique slug for this case.",
    )
    name: str = Field(description="Human-readable name of what this case verifies.")
    workflow: str = Field(description="Workflow brief id this case applies to.")
    agent: str = Field(
        default="",
        description="Agent slug under evaluation. Empty when the case targets the whole workflow.",
    )
    input_artifacts: list[str] = Field(
        default_factory=list,
        description="Artifacts the evaluated run is expected to have started from.",
    )
    expected_outputs: ExpectedOutputs = Field(
        default_factory=ExpectedOutputs,
        description="Required fields, forbidden claims, expected escalation and depth.",
    )
    scoring: dict[CheckCategory, bool] = Field(
        description=(
            "Which of the five checks this case runs (true) or skips (false). "
            "A case scores only what it declares."
        ),
    )
    reviewed: bool = Field(
        default=False,
        description=(
            "True when a human has reviewed this case and agreed it captures "
            "the intended behavior. Only reviewed cases count toward promotion."
        ),
    )
    notes: str = Field(default="", description="Context for future maintainers.")


class EvalCheckResult(BaseModel):
    """The outcome of one check within one eval run."""

    category: CheckCategory = Field(description="Which check ran.")
    outcome: CheckOutcome = Field(description="pass, fail, or skipped.")
    evidence: str = Field(
        default="",
        description="What was inspected to reach the outcome. Failures must say what was missing.",
    )


class EvalResult(BaseModel):
    """The recorded answer to one eval case, run against one run's artifacts."""

    result_id: str = Field(description="Unique id for this eval execution.")
    case_id: str = Field(description="The eval case that was run.")
    workflow_id: str = Field(description="Workflow the evaluated run belongs to.")
    agent: str = Field(default="", description="Agent under evaluation, if any.")
    run_id: str = Field(default="", description="The run whose artifacts were evaluated.")
    evaluated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the eval ran (UTC).",
    )
    checks: list[EvalCheckResult] = Field(
        description="Outcome of every check the case declared."
    )
    overall: CheckOutcome = Field(
        description="PASS only when every non-skipped check passed."
    )
    notes: str = Field(default="", description="Free-text observations from the eval run.")

    @staticmethod
    def overall_from(checks: list[EvalCheckResult]) -> CheckOutcome:
        """Aggregate rule: skipped checks don't count; any failure fails the case."""
        ran = [c for c in checks if c.outcome is not CheckOutcome.SKIPPED]
        if not ran:
            return CheckOutcome.SKIPPED
        return (
            CheckOutcome.PASS
            if all(c.outcome is CheckOutcome.PASS for c in ran)
            else CheckOutcome.FAIL
        )
