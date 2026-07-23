# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Workflow state machine.

The WorkflowRuntime enforces the brief. It never invents behavior: every
allowed move comes from the brief's transition list, every refused move is
recorded, and every state change lands in the append-only ledger.

Two distinct failure modes are handled differently on purpose:

* An attempted move with **no valid path** (the target state is not reachable
  from the current state) freezes the capsule in NON_CONFORMANCE — the work
  has left the governed path and a human must investigate via the brief's
  exception_path.
* An attempted move on a valid path but **without required evidence** is
  refused and logged as a non-conforming event, but the capsule stays in its
  current state — the operator can gather the evidence and try again.
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src.runtime.ledger import RunLedger
from src.schemas.process_capsule import CapsuleStatus, ProcessCapsule
from src.schemas.workflow_brief import Transition, WorkflowBrief


class NonConformanceError(Exception):
    """Raised when an attempted transition violates the workflow brief."""


class WorkflowRuntime:
    """Loads briefs, creates capsules, and advances them through valid transitions."""

    def __init__(self, ledger: RunLedger) -> None:
        """Bind this runtime to a ledger. All history goes through it."""
        self.ledger = ledger

    # ------------------------------------------------------------------ loading

    @staticmethod
    def load_brief(path: str | Path) -> WorkflowBrief:
        """Load and validate a WorkflowBrief from a YAML file.

        Validation errors here mean the brief itself is malformed — fix the
        YAML, not the runtime.
        """
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        return WorkflowBrief.model_validate(raw)

    # ----------------------------------------------------------------- capsules

    def start(
        self,
        brief: WorkflowBrief,
        assigned_to: str | None = None,
        inputs: dict | None = None,
    ) -> ProcessCapsule:
        """Register the workflow and create a capsule in its initial state.

        The capsule's creation is itself a ledger event, so the audit trail
        covers the full life of the work, not just its movements.
        """
        self.ledger.save_workflow(brief)
        capsule = ProcessCapsule(
            id=f"{brief.id}-{uuid.uuid4().hex[:8]}",
            workflow_id=brief.id,
            state=brief.initial_state,
            assigned_to=assigned_to or brief.owner,
            inputs=inputs or {},
        )
        self.ledger.save_capsule(capsule)
        self.ledger.record_event(
            capsule_id=capsule.id,
            workflow_id=brief.id,
            from_state=None,
            to_state=brief.initial_state,
            owner=capsule.assigned_to,
            evidence="",
            conforming=True,
            note="capsule created",
        )
        return capsule

    def valid_transitions(
        self, brief: WorkflowBrief, capsule: ProcessCapsule
    ) -> list[Transition]:
        """Return the transitions available from the capsule's current state."""
        return brief.transitions_from(capsule.state)

    # ---------------------------------------------------------------- advancing

    def advance(
        self,
        brief: WorkflowBrief,
        capsule: ProcessCapsule,
        to_state: str,
        evidence: str = "",
    ) -> ProcessCapsule:
        """Attempt to move a capsule to a new state.

        Enforces the brief:
        * The move must match a declared transition — otherwise the capsule
          is frozen in NON_CONFORMANCE and NonConformanceError is raised.
        * If the transition declares evidence_required, non-empty evidence
          must be supplied — otherwise the attempt is logged as
          non-conforming, the capsule stays put, and NonConformanceError is
          raised.

        On success the move is recorded in the ledger and the capsule
        snapshot is updated. A state with no outgoing transitions is
        terminal: reaching it marks the capsule COMPLETE.
        """
        transition = next(
            (
                t
                for t in brief.transitions_from(capsule.state)
                if t.to_state == to_state
            ),
            None,
        )

        if transition is None:
            # No valid path: the work has left the governed workflow.
            note = (
                f"no valid transition from '{capsule.state}' to '{to_state}'. "
                f"Exception path: {brief.exception_path}"
            )
            capsule.status = CapsuleStatus.NON_CONFORMANCE
            capsule.non_conformance_note = note
            self.ledger.save_capsule(capsule)
            self.ledger.record_event(
                capsule_id=capsule.id,
                workflow_id=brief.id,
                from_state=capsule.state,
                to_state=to_state,
                owner=capsule.assigned_to,
                evidence=evidence,
                conforming=False,
                note=note,
            )
            raise NonConformanceError(note)

        if transition.evidence_required and not evidence.strip():
            # Valid path, missing evidence: refuse the move but leave the
            # capsule where it is so the operator can supply evidence and retry.
            note = (
                f"transition '{capsule.state}' -> '{to_state}' refused: "
                f"required evidence missing ({transition.evidence_required})"
            )
            self.ledger.record_event(
                capsule_id=capsule.id,
                workflow_id=brief.id,
                from_state=capsule.state,
                to_state=to_state,
                owner=transition.owner,
                evidence="",
                conforming=False,
                note=note,
            )
            raise NonConformanceError(note)

        # Conforming move: record it, then update the snapshot.
        from_state = capsule.state
        capsule.state = to_state
        capsule.evidence = evidence
        if brief.transitions_from(to_state):
            capsule.status = CapsuleStatus.IN_PROGRESS
        else:
            capsule.status = CapsuleStatus.COMPLETE
            capsule.completed_at = datetime.now(timezone.utc)
        self.ledger.save_capsule(capsule)
        self.ledger.record_event(
            capsule_id=capsule.id,
            workflow_id=brief.id,
            from_state=from_state,
            to_state=to_state,
            owner=transition.owner,
            evidence=evidence,
            conforming=True,
            note="",
        )
        return capsule

    # ------------------------------------------------------------ review results

    def mark_non_conformance(
        self, brief: WorkflowBrief, capsule: ProcessCapsule, note: str
    ) -> ProcessCapsule:
        """Freeze a capsule in NON_CONFORMANCE (e.g. a reviewer typed REJECT)."""
        capsule.status = CapsuleStatus.NON_CONFORMANCE
        capsule.non_conformance_note = note
        self.ledger.save_capsule(capsule)
        self.ledger.record_event(
            capsule_id=capsule.id,
            workflow_id=brief.id,
            from_state=capsule.state,
            to_state=capsule.state,
            owner=capsule.assigned_to,
            evidence=capsule.evidence,
            conforming=False,
            note=note,
        )
        return capsule

    def flag(
        self, brief: WorkflowBrief, capsule: ProcessCapsule, note: str
    ) -> None:
        """Record a FLAG from a reviewer: noted for later review, work continues.

        A flag is a conforming event — it does not block progress — but it is
        permanent in the ledger so 'later review' actually has something to find.
        """
        self.ledger.record_event(
            capsule_id=capsule.id,
            workflow_id=brief.id,
            from_state=capsule.state,
            to_state=capsule.state,
            owner=capsule.assigned_to,
            evidence=capsule.evidence,
            conforming=True,
            note=f"FLAGGED: {note}",
        )
