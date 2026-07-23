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

from src.schemas.process_capsule import CapsuleStatus, ProcessCapsule
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
        for trigger_sql in _APPEND_ONLY_TRIGGERS:
            self.db.execute(trigger_sql)
        if "workflows" not in self.db.table_names():
            self.db["workflows"].create(
                {"id": str, "title": str, "owner": str, "brief_json": str},
                pk="id",
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
