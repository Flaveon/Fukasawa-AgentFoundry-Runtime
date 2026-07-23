# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Process Capsule schema.

A ProcessCapsule is a single executable unit of work moving through a
workflow. The WorkflowBrief says what is allowed; the capsule records what
actually happened to one concrete piece of work — who holds it, what state
it is in, and what evidence was produced along the way.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class CapsuleStatus(str, Enum):
    """Lifecycle status of a process capsule.

    PENDING          — created, no work has started yet.
    IN_PROGRESS      — actively moving through workflow states.
    AWAITING_REVIEW  — paused at a human review gate; a person must decide.
    COMPLETE         — reached a terminal state; completion criteria satisfied.
    NON_CONFORMANCE  — an attempted move had no valid path or was rejected
                       by a reviewer. The capsule is frozen for investigation.
    """

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    COMPLETE = "COMPLETE"
    NON_CONFORMANCE = "NON_CONFORMANCE"


def _utcnow() -> datetime:
    """Return the current UTC time. Wrapped so every timestamp is timezone-aware."""
    return datetime.now(timezone.utc)


class ProcessCapsule(BaseModel):
    """One unit of work traveling through a governed workflow."""

    id: str = Field(description="Unique identifier for this capsule.")
    workflow_id: str = Field(
        description="The id of the WorkflowBrief this capsule executes under."
    )
    state: str = Field(
        description="Current state, always one of the brief's declared states."
    )
    assigned_to: str = Field(
        description="Human or agent identifier currently responsible for this capsule."
    )
    inputs: dict = Field(
        default_factory=dict,
        description="Data the capsule started with.",
    )
    outputs: dict = Field(
        default_factory=dict,
        description="Data produced by the work. Populated on completion.",
    )
    evidence: str = Field(
        default="",
        description=(
            "What was produced to satisfy the most recent transition's "
            "evidence requirement."
        ),
    )
    status: CapsuleStatus = Field(
        default=CapsuleStatus.PENDING,
        description="Lifecycle status of this capsule.",
    )
    created_at: datetime = Field(
        default_factory=_utcnow,
        description="When this capsule was created (UTC).",
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        description="When this capsule reached COMPLETE (UTC). Empty until then.",
    )
    non_conformance_note: Optional[str] = Field(
        default=None,
        description=(
            "Why this capsule entered NON_CONFORMANCE — the attempted move, "
            "the missing evidence, or the reviewer's rejection reason."
        ),
    )
