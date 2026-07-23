# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Observation Packet schema.

An ObservationPacket is the structured record of what an operator or agent
actually saw while doing a unit of work — kept deliberately separate from
what they concluded about it.

There is no field-level spec for this object yet; this draft is derived from
the Observation Discipline pass conditions in docs/evaluation-strategy.md:

* observations are separated from inferences  -> two distinct fields
* confidence is stated                        -> required field, no default
* missing evidence is stated                  -> required field, no default
* unsupported claims are absent               -> inferences carry confidence

DRAFT STATUS: field set open for review before Phase 2 depends on it.
"""

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class Confidence(str, Enum):
    """How sure the observer is about their inference."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


def _utcnow() -> datetime:
    """Return the current UTC time. Wrapped so every timestamp is timezone-aware."""
    return datetime.now(timezone.utc)


class ObservationPacket(BaseModel):
    """One disciplined observation recorded during a run.

    The core rule: `observation` holds only what was directly seen or
    measured; `inference` holds what the observer concluded from it. Blending
    the two is how unsupported claims sneak into handoffs.
    """

    id: str = Field(description="Unique identifier for this observation packet.")
    run_id: str = Field(description="The run during which this observation was made.")
    capsule_id: str = Field(description="The capsule this observation is about.")
    observer: str = Field(
        description="Human or agent identifier that made the observation."
    )
    observed_at: datetime = Field(
        default_factory=_utcnow, description="When the observation was made (UTC)."
    )
    observation: str = Field(
        min_length=1,
        description=(
            "What was directly seen, measured, or produced. Facts only — no "
            "interpretation. ('The draft is 1450 words and cites 3 sources.')"
        ),
    )
    inference: str = Field(
        default="",
        description=(
            "What the observer concludes from the observation, kept separate "
            "from it. ('The draft is probably ready for editor review.') "
            "Empty is valid: not every observation needs a conclusion."
        ),
    )
    confidence: Confidence = Field(
        description=(
            "Stated confidence in the inference. Required — an unstated "
            "confidence is how unsupported claims are born."
        )
    )
    missing_evidence: str = Field(
        description=(
            "What evidence is absent or could not be obtained. Required — "
            "write 'none' explicitly if nothing is missing. Silence about "
            "gaps is itself a gap."
        )
    )
    artifacts: list[str] = Field(
        default_factory=list,
        description="Paths to files that support or embody this observation.",
    )
    recommended_next_step: str = Field(
        default="",
        description="What the observer suggests doing next, if anything.",
    )
