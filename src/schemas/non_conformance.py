# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Non-Conformance Record schema.

A NonConformanceRecord is the structured, queryable account of one governance
breach. The append-only ledger already logs *that* something non-conforming
happened; this record captures *what kind*, so repeated failures become
visible patterns that drive process changes (docs/evaluation-strategy.md:
"repeated failures trigger non-conformance review").
"""

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class NonConformanceKind(str, Enum):
    """The known ways work can leave the governed path.

    NO_VALID_PATH    — an attempted transition does not exist in the brief.
    MISSING_EVIDENCE — a valid transition was attempted without its required
                       evidence.
    REVIEW_REJECTED  — a human reviewer rejected the work at a review gate.
    OTHER            — anything else; the note must explain.
    """

    NO_VALID_PATH = "no_valid_path"
    MISSING_EVIDENCE = "missing_evidence"
    REVIEW_REJECTED = "review_rejected"
    OTHER = "other"


class ResolutionStatus(str, Enum):
    """Whether anyone has dealt with this non-conformance yet."""

    OPEN = "open"
    RESOLVED = "resolved"


def _utcnow() -> datetime:
    """Return the current UTC time. Wrapped so every timestamp is timezone-aware."""
    return datetime.now(timezone.utc)


class NonConformanceRecord(BaseModel):
    """One structured account of work leaving the governed path."""

    id: str = Field(description="Unique identifier for this record.")
    workflow_id: str = Field(description="The workflow in which the breach occurred.")
    capsule_id: str = Field(description="The capsule that hit the non-conformance.")
    run_id: str = Field(
        default="", description="The run during which it occurred, if run-tracked."
    )
    kind: NonConformanceKind = Field(
        description="Which known failure mode this was. Use OTHER only with an explanatory note."
    )
    from_state: str = Field(
        description="The state the capsule was in when the breach occurred."
    )
    attempted_state: str = Field(
        default="",
        description="The state the move was aiming for, when the breach was an attempted transition.",
    )
    note: str = Field(
        min_length=1,
        description="Plain-language account of what happened. Never empty — an unexplained breach cannot drive a process change.",
    )
    occurred_at: datetime = Field(
        default_factory=_utcnow, description="When the breach occurred (UTC)."
    )
    resolution_status: ResolutionStatus = Field(
        default=ResolutionStatus.OPEN,
        description="Open until a human closes it with a resolution note.",
    )
    resolution_note: str = Field(
        default="",
        description="What was changed or decided to close this record (e.g. 'added missing transition to brief').",
    )
