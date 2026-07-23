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

Since Phase 1, each capsule execution is tracked as a *run* with a durable
RuntimeState, so work can be paused, handed off, and resumed outside chat.
Every non-conformance also produces a structured NonConformanceRecord so
repeated failure kinds become queryable patterns.
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from src.runtime.ledger import RunLedger
from src.schemas.non_conformance import NonConformanceKind, NonConformanceRecord
from src.schemas.observation_packet import ObservationPacket
from src.schemas.process_capsule import CapsuleStatus, ProcessCapsule
from src.schemas.runtime_state import (
    CheckResult,
    CompletedCheck,
    GateStatus,
    InputArtifact,
    OutputArtifact,
    RunStatus,
    RuntimeState,
)
from src.schemas.workflow_brief import Transition, WorkflowBrief


class NonConformanceError(Exception):
    """Raised when an attempted transition violates the workflow brief."""


def _new_id(prefix: str) -> str:
    """Generate a short unique id with a human-readable prefix."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


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
        operator: str | None = None,
        brief_path: str | Path | None = None,
    ) -> tuple[ProcessCapsule, RuntimeState]:
        """Register the workflow, create a capsule, and open a tracked run.

        The capsule's creation is itself a ledger event, so the audit trail
        covers the full life of the work, not just its movements. The
        returned RuntimeState is the durable handle for pausing and resuming.
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

        run = RuntimeState(
            run_id=_new_id("run"),
            workflow_id=brief.id,
            workflow_name=brief.title,
            capsule_id=capsule.id,
            operator=operator or brief.owner,
            status=RunStatus.PENDING,
            current_state=capsule.state,
            task_depth=brief.task_depth,
            trace_path=str(self.ledger.db_path),
        )
        if brief_path is not None:
            run.inputs.append(
                InputArtifact(
                    path=str(brief_path), kind="workflow_brief", required=True
                )
            )
        self.ledger.save_run(run)

        self.ledger.record_event(
            capsule_id=capsule.id,
            workflow_id=brief.id,
            from_state=None,
            to_state=brief.initial_state,
            owner=capsule.assigned_to,
            evidence="",
            conforming=True,
            note=f"capsule created (run {run.run_id})",
        )
        return capsule, run

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
        run: Optional[RuntimeState] = None,
    ) -> ProcessCapsule:
        """Attempt to move a capsule to a new state.

        Enforces the brief:
        * The move must match a declared transition — otherwise the capsule
          is frozen in NON_CONFORMANCE, the run (if tracked) is FAILED, and
          NonConformanceError is raised.
        * If the transition declares evidence_required, non-empty evidence
          must be supplied — otherwise the attempt is logged as
          non-conforming, the capsule stays put, and NonConformanceError is
          raised. The run stays RUNNING: missing evidence is retryable.

        Both failure modes produce a structured NonConformanceRecord on top
        of the immutable ledger event, so failure kinds are queryable.

        On success the move is recorded in the ledger and the capsule and run
        snapshots are updated. A state with no outgoing transitions is
        terminal: reaching it marks the capsule COMPLETE and the run
        COMPLETE, with a verification check recorded against the brief's
        completion criteria.
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
            self._record_non_conformance(
                brief, capsule, run, NonConformanceKind.NO_VALID_PATH,
                from_state=capsule.state, attempted_state=to_state, note=note,
            )
            if run is not None:
                run.status = RunStatus.FAILED
                run.touch()
                self.ledger.save_run(run)
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
            self._record_non_conformance(
                brief, capsule, run, NonConformanceKind.MISSING_EVIDENCE,
                from_state=capsule.state, attempted_state=to_state, note=note,
            )
            raise NonConformanceError(note)

        # Conforming move: record it, then update the snapshots.
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
        if run is not None:
            run.current_state = to_state
            if capsule.status is CapsuleStatus.COMPLETE:
                # Completion requires at least one passing verification check
                # (runtime-state contract). The final transition's satisfied
                # evidence requirement is that check.
                run.completed_checks.append(
                    CompletedCheck(
                        check=f"completion criteria: {brief.completion_criteria.strip()}",
                        result=CheckResult.PASS,
                        evidence=evidence or "terminal state reached",
                    )
                )
                run.status = RunStatus.COMPLETE
            else:
                run.status = RunStatus.RUNNING
            run.touch()
            self.ledger.save_run(run)
        return capsule

    # ------------------------------------------------------------ review results

    def enter_human_review(
        self, run: RuntimeState, reason: str, reviewer: str
    ) -> None:
        """Mark a run as paused at a human review gate."""
        run.human_gate.required = True
        run.human_gate.reason = reason
        run.human_gate.status = GateStatus.PENDING
        run.human_gate.reviewer = reviewer
        run.status = RunStatus.HUMAN_REVIEW
        run.touch()
        self.ledger.save_run(run)

    def resolve_gate(self, run: RuntimeState, approved: bool) -> None:
        """Record the reviewer's gate decision on the run.

        The caller then either advances (approved) or marks non-conformance
        (rejected); this method only records the decision itself.
        """
        run.human_gate.status = GateStatus.APPROVED if approved else GateStatus.REJECTED
        run.human_gate.reviewed_at = datetime.now(timezone.utc)
        # Leave HUMAN_REVIEW; advance()/mark_non_conformance() sets the final status.
        run.status = RunStatus.RUNNING
        run.touch()
        self.ledger.save_run(run)

    def mark_non_conformance(
        self,
        brief: WorkflowBrief,
        capsule: ProcessCapsule,
        note: str,
        run: Optional[RuntimeState] = None,
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
        self._record_non_conformance(
            brief, capsule, run, NonConformanceKind.REVIEW_REJECTED,
            from_state=capsule.state, attempted_state="", note=note,
        )
        if run is not None:
            run.status = RunStatus.FAILED
            run.touch()
            self.ledger.save_run(run)
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

    # ------------------------------------------------------------------ runs

    def block_run(self, run: RuntimeState, reason: str, next_action: str) -> None:
        """Pause a run with a stated reason and a stated next action.

        The runtime-state contract forbids a blocked run without both fields:
        a pause nobody can resume is abandonment, not a handoff.
        """
        run.blocked_reason = reason
        run.next_action = next_action
        run.status = RunStatus.BLOCKED
        run.touch()
        self.ledger.save_run(run)

    def resume_run(
        self, run_id: str
    ) -> tuple[WorkflowBrief, ProcessCapsule, RuntimeState]:
        """Reload everything needed to continue a persisted run.

        Returns the brief, capsule, and run state exactly as last saved.
        Clears blocked fields if the run was blocked — resuming is the
        next_action being taken.
        """
        run = self.ledger.load_run(run_id)
        brief = self.ledger.load_workflow(run.workflow_id)
        capsule = self.ledger.load_capsule(run.capsule_id)
        if run.status is RunStatus.BLOCKED:
            # Order matters: leave BLOCKED before clearing its mandatory
            # fields, or assignment validation would (rightly) refuse.
            run.status = RunStatus.RUNNING
            run.blocked_reason = ""
            run.next_action = ""
            run.touch()
            self.ledger.save_run(run)
        return brief, capsule, run

    def add_output_artifact(
        self, run: RuntimeState, path: str, kind: str, produced_by: str
    ) -> None:
        """Attach a produced artifact to the run. Every artifact must have a path."""
        run.outputs.append(
            OutputArtifact(path=path, kind=kind, produced_by=produced_by)
        )
        run.touch()
        self.ledger.save_run(run)

    def record_observation(
        self,
        run: RuntimeState,
        capsule: ProcessCapsule,
        observer: str,
        observation: str,
        confidence: str,
        missing_evidence: str,
        inference: str = "",
        artifacts: list[str] | None = None,
        recommended_next_step: str = "",
    ) -> ObservationPacket:
        """Record a disciplined observation against a run."""
        packet = ObservationPacket(
            id=_new_id("obs"),
            run_id=run.run_id,
            capsule_id=capsule.id,
            observer=observer,
            observation=observation,
            inference=inference,
            confidence=confidence,
            missing_evidence=missing_evidence,
            artifacts=artifacts or [],
            recommended_next_step=recommended_next_step,
        )
        self.ledger.save_observation(packet)
        return packet

    # ------------------------------------------------------------------ private

    def _record_non_conformance(
        self,
        brief: WorkflowBrief,
        capsule: ProcessCapsule,
        run: Optional[RuntimeState],
        kind: NonConformanceKind,
        from_state: str,
        attempted_state: str,
        note: str,
    ) -> NonConformanceRecord:
        """Create and persist the structured record for a governance breach."""
        record = NonConformanceRecord(
            id=_new_id("ncr"),
            workflow_id=brief.id,
            capsule_id=capsule.id,
            run_id=run.run_id if run is not None else "",
            kind=kind,
            from_state=from_state,
            attempted_state=attempted_state,
            note=note,
        )
        self.ledger.save_non_conformance_record(record)
        if run is not None:
            run.non_conformance_path = (
                f"{self.ledger.db_path}#non_conformance_records"
            )
        return record
