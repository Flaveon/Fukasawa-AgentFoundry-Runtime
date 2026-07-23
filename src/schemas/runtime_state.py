# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Runtime State schema.

RuntimeState is the durable record of where a workflow run stands. It exists
so state never lives only in chat history: any session — human or agent —
can pick up a run by reading this record.

Source doctrine: specs/runtime-state-contract.md. The contract's rules are
enforced here as validators, not left as prose:

* A blocked run must include blocked_reason and next_action.
* A human-review run must include the gate's reason.
* Completion requires at least one passing verification check.
* Every artifact must have a path.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.schemas.workflow_brief import TaskDepth

#: Version of this schema, recorded in every persisted state.
SCHEMA_VERSION = "0.1"


class RunStatus(str, Enum):
    """Where a run stands in its lifecycle.

    PENDING      — created, nothing has executed yet.
    RUNNING      — actively advancing through workflow states.
    BLOCKED      — paused with a stated reason and a stated next action.
    HUMAN_REVIEW — waiting at a human review gate.
    COMPLETE     — finished; at least one verification check passed.
    FAILED       — halted by non-conformance or rejection.
    """

    PENDING = "pending"
    RUNNING = "running"
    BLOCKED = "blocked"
    HUMAN_REVIEW = "human_review"
    COMPLETE = "complete"
    FAILED = "failed"


class CheckResult(str, Enum):
    """Outcome of a single verification check."""

    PASS = "pass"
    FAIL = "fail"
    SKIPPED = "skipped"


class GateStatus(str, Enum):
    """Status of the human review gate attached to a run."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    NOT_REQUIRED = "not_required"


class InputArtifact(BaseModel):
    """A file or resource the run starts from."""

    path: str = Field(min_length=1, description="Filesystem path to the artifact. Never empty.")
    kind: str = Field(default="", description="What kind of artifact this is (e.g. 'draft', 'brief').")
    required: bool = Field(
        default=False, description="Whether the run cannot proceed without this artifact."
    )


class OutputArtifact(BaseModel):
    """A file or resource the run produced."""

    path: str = Field(min_length=1, description="Filesystem path to the artifact. Never empty.")
    kind: str = Field(default="", description="What kind of artifact this is (e.g. 'article', 'report').")
    produced_by: str = Field(
        default="", description="Human or agent identifier that produced this artifact."
    )


class CompletedCheck(BaseModel):
    """One verification check performed during the run."""

    check: str = Field(min_length=1, description="Plain-language name of what was verified.")
    result: CheckResult = Field(description="Whether the check passed, failed, or was skipped.")
    evidence: str = Field(
        default="", description="What was produced or inspected to support the result."
    )


class HumanGate(BaseModel):
    """The human review gate state attached to a run."""

    required: bool = Field(
        default=False, description="Whether this run must pass a human review gate."
    )
    reason: str = Field(
        default="",
        description="Why human review is required. Mandatory when the run is in human_review.",
    )
    status: GateStatus = Field(
        default=GateStatus.NOT_REQUIRED, description="Current decision state of the gate."
    )
    reviewer: str = Field(default="", description="Who reviewed (or will review) this gate.")
    reviewed_at: Optional[datetime] = Field(
        default=None, description="When the review decision was made (UTC)."
    )


def _utcnow() -> datetime:
    """Return the current UTC time. Wrapped so every timestamp is timezone-aware."""
    return datetime.now(timezone.utc)


class RuntimeState(BaseModel):
    """The durable record of where a workflow run stands."""

    # Re-validate the contract rules on every field assignment, not just at
    # construction — a run mutated into 'blocked' without a reason must fail
    # at the moment of mutation, not when someone later tries to load it.
    model_config = ConfigDict(validate_assignment=True)

    schema_version: str = Field(
        default=SCHEMA_VERSION, description="Version of the RuntimeState schema."
    )
    run_id: str = Field(description="Unique identifier for this run.")
    workflow_id: str = Field(description="Id of the WorkflowBrief this run executes.")
    workflow_name: str = Field(description="Human-readable workflow title.")
    capsule_id: str = Field(
        description="The process capsule this run is advancing. One run drives one capsule."
    )
    created_at: datetime = Field(
        default_factory=_utcnow, description="When this run was created (UTC)."
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        description="Touched on every state transition. Stale means abandoned.",
    )
    operator: str = Field(description="The human operating this run.")
    status: RunStatus = Field(
        default=RunStatus.PENDING, description="Where this run stands in its lifecycle."
    )
    phase: str = Field(
        default="", description="Optional label for the project phase this run belongs to."
    )
    current_state: str = Field(
        description="The capsule's current workflow state (the contract's 'current_node')."
    )
    task_depth: TaskDepth = Field(
        description="Effective task depth of the workflow being run."
    )
    inputs: list[InputArtifact] = Field(
        default_factory=list, description="Artifacts the run started from."
    )
    outputs: list[OutputArtifact] = Field(
        default_factory=list, description="Artifacts the run has produced so far."
    )
    completed_checks: list[CompletedCheck] = Field(
        default_factory=list, description="Verification checks performed during the run."
    )
    human_gate: HumanGate = Field(
        default_factory=HumanGate, description="Human review gate state for this run."
    )
    blocked_reason: str = Field(
        default="", description="Why the run is blocked. Mandatory when status is blocked."
    )
    next_action: str = Field(
        default="",
        description="The single next thing to do. Mandatory when status is blocked.",
    )
    trace_path: str = Field(
        default="", description="Where the run's full ledger history lives (SQLite path)."
    )
    non_conformance_path: str = Field(
        default="",
        description="Pointer to the non-conformance record(s) for this run, if any.",
    )

    @model_validator(mode="after")
    def _enforce_contract_rules(self) -> "RuntimeState":
        """Enforce the runtime-state contract's rules at validation time.

        These rules are the difference between a status label and a usable
        handoff: a blocked run that doesn't say why, or what to do next, is
        not actually resumable by anyone else.
        """
        if self.status is RunStatus.BLOCKED:
            if not self.blocked_reason.strip():
                raise ValueError("a blocked run must include blocked_reason")
            if not self.next_action.strip():
                raise ValueError("a blocked run must include next_action")
        if self.status is RunStatus.HUMAN_REVIEW and not self.human_gate.reason.strip():
            raise ValueError("a run in human_review must include human_gate.reason")
        if self.status is RunStatus.COMPLETE:
            passing = [c for c in self.completed_checks if c.result is CheckResult.PASS]
            if not passing:
                raise ValueError(
                    "completion requires at least one verification check with result 'pass'"
                )
        return self

    def touch(self) -> None:
        """Update the updated_at timestamp. Call on every transition."""
        self.updated_at = _utcnow()
