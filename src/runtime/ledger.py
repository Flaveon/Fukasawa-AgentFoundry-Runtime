# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Run Ledger — the append-only audit trail.

Every state transition, conforming or not, is recorded here. No record is
ever updated or deleted; the ledger enforces this with SQLite triggers, so
even code with a direct database handle cannot quietly rewrite history.

The same SQLite file also holds the current snapshot of workflows and
capsules so `fukasawa status` and `fukasawa review` work across separate
CLI invocations. Snapshots may be updated; ledger events may not.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import sqlite_utils

from src.schemas.eval_case import EvalResult
from src.schemas.non_conformance import (
    NonConformanceRecord,
    ResolutionStatus,
)
from src.schemas.observation_packet import ObservationPacket
from src.schemas.process_capsule import CapsuleStatus, ProcessCapsule
from src.schemas.runtime_state import RuntimeState
from src.schemas.workflow_brief import WorkflowBrief

#: Default database location: the current working directory.
DEFAULT_DB_PATH = "fukasawa.db"

_APPEND_ONLY_TRIGGERS = [
    """
    CREATE TRIGGER IF NOT EXISTS ledger_no_update
    BEFORE UPDATE ON ledger
    BEGIN SELECT RAISE(ABORT, 'ledger is append-only: updates are forbidden'); END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS ledger_no_delete
    BEFORE DELETE ON ledger
    BEGIN SELECT RAISE(ABORT, 'ledger is append-only: deletes are forbidden'); END;
    """,
    # Governance decisions are history too: a promotion, once made, is never
    # rewritten — a wrong promotion is corrected by a demotion event on top.
    """
    CREATE TRIGGER IF NOT EXISTS promotions_no_update
    BEFORE UPDATE ON promotions
    BEGIN SELECT RAISE(ABORT, 'promotions are append-only: updates are forbidden'); END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS promotions_no_delete
    BEFORE DELETE ON promotions
    BEGIN SELECT RAISE(ABORT, 'promotions are append-only: deletes are forbidden'); END;
    """,
]


class RunLedger:
    """Durable run history and state store backed by a local SQLite file."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        """Open (or create) the ledger database and ensure its tables exist."""
        self.db_path = Path(db_path)
        self.db = sqlite_utils.Database(self.db_path)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create tables and append-only triggers if they do not exist yet."""
        if "ledger" not in self.db.table_names():
            self.db["ledger"].create(
                {
                    "event_id": int,
                    "capsule_id": str,
                    "workflow_id": str,
                    "from_state": str,
                    "to_state": str,
                    "owner": str,
                    "evidence": str,
                    "timestamp": str,
                    "conforming": int,  # 1 = conforming event, 0 = non-conformance
                    "note": str,
                },
                pk="event_id",
            )
        if "workflows" not in self.db.table_names():
            self.db["workflows"].create(
                {"id": str, "title": str, "owner": str, "brief_json": str},
                pk="id",
            )
        if "runs" not in self.db.table_names():
            self.db["runs"].create(
                {
                    "run_id": str,
                    "workflow_id": str,
                    "capsule_id": str,
                    "operator": str,
                    "status": str,
                    "updated_at": str,
                    "state_json": str,  # full RuntimeState, schema-validated on load
                },
                pk="run_id",
            )
        if "observations" not in self.db.table_names():
            self.db["observations"].create(
                {
                    "id": str,
                    "run_id": str,
                    "capsule_id": str,
                    "observer": str,
                    "observed_at": str,
                    "packet_json": str,  # full ObservationPacket
                },
                pk="id",
            )
        if "non_conformance_records" not in self.db.table_names():
            self.db["non_conformance_records"].create(
                {
                    "id": str,
                    "workflow_id": str,
                    "capsule_id": str,
                    "run_id": str,
                    "kind": str,
                    "resolution_status": str,
                    "occurred_at": str,
                    "record_json": str,  # full NonConformanceRecord
                },
                pk="id",
            )
        if "eval_results" not in self.db.table_names():
            self.db["eval_results"].create(
                {
                    "result_id": str,
                    "case_id": str,
                    "workflow_id": str,
                    "agent": str,
                    "run_id": str,
                    "overall": str,
                    "evaluated_at": str,
                    "result_json": str,  # full EvalResult
                },
                pk="result_id",
            )
        if "promotions" not in self.db.table_names():
            # Created BEFORE the trigger loop above runs, so the append-only
            # triggers attach on first startup.
            self.db["promotions"].create(
                {
                    "promotion_id": int,
                    "agent": str,
                    "workflow_id": str,
                    "from_maturity": str,
                    "to_maturity": str,
                    "reviewed_by": str,
                    "rationale": str,
                    "evidence": str,
                    "promoted_at": str,
                },
                pk="promotion_id",
            )
        if "capsules" not in self.db.table_names():
            self.db["capsules"].create(
                {
                    "id": str,
                    "workflow_id": str,
                    "state": str,
                    "assigned_to": str,
                    "inputs": str,
                    "outputs": str,
                    "evidence": str,
                    "status": str,
                    "created_at": str,
                    "completed_at": str,
                    "non_conformance_note": str,
                },
                pk="id",
            )
        # Triggers attach last, after every table they reference exists.
        for trigger_sql in _APPEND_ONLY_TRIGGERS:
            self.db.execute(trigger_sql)

    # ------------------------------------------------------------------ ledger

    def record_event(
        self,
        capsule_id: str,
        workflow_id: str,
        from_state: Optional[str],
        to_state: str,
        owner: str,
        evidence: str,
        conforming: bool,
        note: str = "",
    ) -> None:
        """Append one immutable event to the audit trail.

        Called for every state change and every refused attempt. There is
        deliberately no corresponding update or delete method.
        """
        self.db["ledger"].insert(
            {
                "capsule_id": capsule_id,
                "workflow_id": workflow_id,
                "from_state": from_state or "",
                "to_state": to_state,
                "owner": owner,
                "evidence": evidence,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "conforming": 1 if conforming else 0,
                "note": note,
            }
        )

    def history(self, workflow_id: str) -> list[dict]:
        """Return every ledger event for a workflow, oldest first."""
        return list(
            self.db["ledger"].rows_where(
                "workflow_id = ?", [workflow_id], order_by="event_id"
            )
        )

    # --------------------------------------------------------------- snapshots

    def save_workflow(self, brief: WorkflowBrief) -> None:
        """Store (or refresh) the workflow brief snapshot for later CLI calls."""
        self.db["workflows"].upsert(
            {
                "id": brief.id,
                "title": brief.title,
                "owner": brief.owner,
                "brief_json": brief.model_dump_json(),
            },
            pk="id",
        )

    def load_workflow(self, workflow_id: str) -> WorkflowBrief:
        """Load a stored workflow brief by id. Raises KeyError if unknown."""
        row = self.db["workflows"].get(workflow_id)
        return WorkflowBrief.model_validate_json(row["brief_json"])

    def save_capsule(self, capsule: ProcessCapsule) -> None:
        """Store (or refresh) the current snapshot of a capsule."""
        self.db["capsules"].upsert(
            {
                "id": capsule.id,
                "workflow_id": capsule.workflow_id,
                "state": capsule.state,
                "assigned_to": capsule.assigned_to,
                "inputs": json.dumps(capsule.inputs),
                "outputs": json.dumps(capsule.outputs),
                "evidence": capsule.evidence,
                "status": capsule.status.value,
                "created_at": capsule.created_at.isoformat(),
                "completed_at": (
                    capsule.completed_at.isoformat() if capsule.completed_at else ""
                ),
                "non_conformance_note": capsule.non_conformance_note or "",
            },
            pk="id",
        )

    def load_capsule(self, capsule_id: str) -> ProcessCapsule:
        """Load a capsule snapshot by id. Raises KeyError if unknown."""
        row = self.db["capsules"].get(capsule_id)
        return ProcessCapsule(
            id=row["id"],
            workflow_id=row["workflow_id"],
            state=row["state"],
            assigned_to=row["assigned_to"],
            inputs=json.loads(row["inputs"] or "{}"),
            outputs=json.loads(row["outputs"] or "{}"),
            evidence=row["evidence"],
            status=CapsuleStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            completed_at=(
                datetime.fromisoformat(row["completed_at"])
                if row["completed_at"]
                else None
            ),
            non_conformance_note=row["non_conformance_note"] or None,
        )

    def capsules_for(self, workflow_id: str) -> list[ProcessCapsule]:
        """Return every capsule snapshot belonging to a workflow."""
        rows = self.db["capsules"].rows_where("workflow_id = ?", [workflow_id])
        return [self.load_capsule(row["id"]) for row in rows]

    def non_conforming_capsules(self) -> list[ProcessCapsule]:
        """Return every capsule currently in NON_CONFORMANCE, across all workflows."""
        rows = self.db["capsules"].rows_where(
            "status = ?", [CapsuleStatus.NON_CONFORMANCE.value]
        )
        return [self.load_capsule(row["id"]) for row in rows]

    # -------------------------------------------------------------------- runs

    def save_run(self, state: RuntimeState) -> None:
        """Store (or refresh) the durable RuntimeState snapshot of a run."""
        self.db["runs"].upsert(
            {
                "run_id": state.run_id,
                "workflow_id": state.workflow_id,
                "capsule_id": state.capsule_id,
                "operator": state.operator,
                "status": state.status.value,
                "updated_at": state.updated_at.isoformat(),
                "state_json": state.model_dump_json(),
            },
            pk="run_id",
        )

    def load_run(self, run_id: str) -> RuntimeState:
        """Load a run's RuntimeState by id, re-validating the contract rules.

        Raises KeyError if unknown. Validation on load means a hand-edited
        or corrupted state file fails loudly instead of resuming quietly.
        """
        row = self.db["runs"].get(run_id)
        return RuntimeState.model_validate_json(row["state_json"])

    def list_runs(self, workflow_id: Optional[str] = None) -> list[RuntimeState]:
        """Return every run, newest first, optionally filtered by workflow."""
        if workflow_id:
            rows = self.db["runs"].rows_where(
                "workflow_id = ?", [workflow_id], order_by="updated_at desc"
            )
        else:
            rows = self.db["runs"].rows_where(order_by="updated_at desc")
        return [RuntimeState.model_validate_json(r["state_json"]) for r in rows]

    # ------------------------------------------------------------ observations

    def save_observation(self, packet: ObservationPacket) -> None:
        """Store one observation packet. Observations are never overwritten."""
        self.db["observations"].insert(
            {
                "id": packet.id,
                "run_id": packet.run_id,
                "capsule_id": packet.capsule_id,
                "observer": packet.observer,
                "observed_at": packet.observed_at.isoformat(),
                "packet_json": packet.model_dump_json(),
            }
        )

    def observations_for(self, run_id: str) -> list[ObservationPacket]:
        """Return every observation packet recorded during a run, oldest first."""
        rows = self.db["observations"].rows_where(
            "run_id = ?", [run_id], order_by="observed_at"
        )
        return [ObservationPacket.model_validate_json(r["packet_json"]) for r in rows]

    # ------------------------------------------------------------ eval results

    def save_eval_result(self, result: EvalResult) -> None:
        """Store one eval execution. Results are inserted, never revised —
        a re-run is a new result, and history shows the trend."""
        self.db["eval_results"].insert(
            {
                "result_id": result.result_id,
                "case_id": result.case_id,
                "workflow_id": result.workflow_id,
                "agent": result.agent,
                "run_id": result.run_id,
                "overall": result.overall.value,
                "evaluated_at": result.evaluated_at.isoformat(),
                "result_json": result.model_dump_json(),
            }
        )

    def eval_results_for(
        self, agent: str = "", workflow_id: str = ""
    ) -> list[EvalResult]:
        """Return eval results filtered by agent and/or workflow, newest first."""
        clauses, params = [], []
        if agent:
            clauses.append("agent = ?")
            params.append(agent)
        if workflow_id:
            clauses.append("workflow_id = ?")
            params.append(workflow_id)
        where = " and ".join(clauses) if clauses else "1=1"
        rows = self.db["eval_results"].rows_where(
            where, params, order_by="evaluated_at desc"
        )
        return [EvalResult.model_validate_json(r["result_json"]) for r in rows]

    # -------------------------------------------------------------- promotions

    def record_promotion(
        self,
        agent: str,
        workflow_id: str,
        from_maturity: str,
        to_maturity: str,
        reviewed_by: str,
        rationale: str,
        evidence: str,
    ) -> None:
        """Append one governance decision to the immutable promotion history."""
        self.db["promotions"].insert(
            {
                "agent": agent,
                "workflow_id": workflow_id,
                "from_maturity": from_maturity,
                "to_maturity": to_maturity,
                "reviewed_by": reviewed_by,
                "rationale": rationale,
                "evidence": evidence,
                "promoted_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    def promotions_for(self, agent: str) -> list[dict]:
        """Return the promotion history for an agent, oldest first."""
        return list(
            self.db["promotions"].rows_where(
                "agent = ?", [agent], order_by="promotion_id"
            )
        )

    # --------------------------------------------------- non-conformance records

    def save_non_conformance_record(self, record: NonConformanceRecord) -> None:
        """Store (or refresh) a structured non-conformance record.

        Upsert is allowed here — unlike ledger events — because a record's
        resolution_status legitimately changes when a human closes it.
        The underlying events remain immutable in the ledger.
        """
        self.db["non_conformance_records"].upsert(
            {
                "id": record.id,
                "workflow_id": record.workflow_id,
                "capsule_id": record.capsule_id,
                "run_id": record.run_id,
                "kind": record.kind.value,
                "resolution_status": record.resolution_status.value,
                "occurred_at": record.occurred_at.isoformat(),
                "record_json": record.model_dump_json(),
            },
            pk="id",
        )

    def non_conformance_records(
        self, open_only: bool = False
    ) -> list[NonConformanceRecord]:
        """Return non-conformance records, newest first, optionally open ones only."""
        if open_only:
            rows = self.db["non_conformance_records"].rows_where(
                "resolution_status = ?",
                [ResolutionStatus.OPEN.value],
                order_by="occurred_at desc",
            )
        else:
            rows = self.db["non_conformance_records"].rows_where(
                order_by="occurred_at desc"
            )
        return [
            NonConformanceRecord.model_validate_json(r["record_json"]) for r in rows
        ]
