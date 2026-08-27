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
from typing import Optional

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


class ExecutionStatus(str, Enum):
    """Whether the evaluation machinery ran, kept separate from what it found.

    This distinction is the whole reason the enum exists. "The runner crashed"
    and "the output was judged and failed" look identical if both collapse to
    'fail', and treating the first as evidence about the work would let a dead
    API key manufacture a governance verdict.

    COMPLETED         — the evaluation ran; ``overall`` carries the verdict.
    EXECUTION_FAILED  — the harness broke. ``overall`` is meaningless; the
                        evaluated work is neither proven nor disproven.
    NOT_EXECUTED      — nothing was attempted (e.g. the backend is unavailable).
    """

    COMPLETED = "completed"
    EXECUTION_FAILED = "execution_failed"
    NOT_EXECUTED = "not_executed"


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

    # ---------------------------------------------------------- externally executed
    #
    # Populated when an execution backend produced this result instead of the
    # in-process checks (see src/governance/smevals_adapter.py). Every field is
    # optional with a default, so results recorded before these existed still
    # load, and the ledger needs no migration — eval_results stores a
    # result_json blob alongside its indexed columns.

    execution_status: ExecutionStatus = Field(
        default=ExecutionStatus.COMPLETED,
        description=(
            "Whether the evaluation machinery ran at all. When this is not "
            "'completed', ``overall`` says nothing about the evaluated work — "
            "read this field before drawing any conclusion from the verdict."
        ),
    )
    executed_by: str = Field(
        default="",
        description=(
            "Name of the backend that produced this result, e.g. 'smevals'. "
            "Empty means the runtime's own in-process checks produced it."
        ),
    )
    executor_version: str = Field(
        default="",
        description=(
            "Version of that backend, recorded per result. External evaluation "
            "tools move; a result that cannot say what produced it cannot be "
            "compared against a later one."
        ),
    )
    external_run_ref: str = Field(
        default="",
        description=(
            "Reference to the backend's own run record — a path or id. The "
            "runtime stores the reference, never a copy: duplicating the "
            "artifact would create a second source of truth."
        ),
    )
    score: Optional[float] = Field(
        default=None,
        description=(
            "Numeric score, when the backend produced one. Advisory only: a "
            "score never authorizes promotion, and the runtime makes no "
            "decision from it."
        ),
    )
    artifact_paths: list[str] = Field(
        default_factory=list,
        description="Paths to evidence produced by the run — output, stderr, grade files.",
    )
    non_conformance_candidates: list[str] = Field(
        default_factory=list,
        description=(
            "Findings a human might choose to record as non-conformance. "
            "Candidates only — nothing here files a NonConformanceRecord, "
            "because a failed check is evidence, not a governance breach."
        ),
    )
    requires_human_review: bool = Field(
        default=False,
        description=(
            "Set when this result needs a person to look at it before it is "
            "used as evidence — a failed verdict, or a harness failure that "
            "left the question unanswered."
        ),
    )

    @property
    def is_evidence(self) -> bool:
        """Whether this result says anything about the evaluated work.

        False when the harness failed or never ran: in those cases the verdict
        describes our infrastructure, not the workflow, and must not be cited
        as evidence for or against it.
        """
        return self.execution_status is ExecutionStatus.COMPLETED

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
