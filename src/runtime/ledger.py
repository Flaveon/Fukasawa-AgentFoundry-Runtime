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
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import sqlite_utils

from src.schemas.cooperation import CooperationAssessment, CooperativeWorkflow
from src.schemas.eval_case import EvalResult
from src.schemas.findings import RiskAcceptance, ValidationReport
from src.schemas.graph import GraphRunState
from src.schemas.human_workflow import AccountableWorkflow, HumanWorkflowDraft
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


def _new_id(prefix: str) -> str:
    """Generate a short unique storage id with a readable prefix."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"

#: Tables that record history rather than current state. Nothing in them is
#: ever rewritten: a wrong entry is corrected by a later entry on top, never by
#: editing the record of what was believed at the time.
#:
#: Workflow drafts are deliberately absent — a draft is a working document that
#: people edit, and forbidding that would make capture impossible. Everything
#: *derived* from a draft (a validation report, an accepted risk, a promotion,
#: a promoted artifact) is immutable, because those are the evidence a decision
#: was made on.
_APPEND_ONLY_TABLES = (
    "ledger",
    "promotions",
    "validation_reports",
    "risk_acceptances",
    "workflow_promotions",
    "accountable_workflows",
    "cooperation_assessments",
    "cooperative_workflows",
)

_APPEND_ONLY_TRIGGERS = [
    f"""
    CREATE TRIGGER IF NOT EXISTS {table}_no_{verb}
    BEFORE {verb.upper()} ON {table}
    BEGIN SELECT RAISE(ABORT, '{table} is append-only: {verb}s are forbidden'); END;
    """
    for table in _APPEND_ONLY_TABLES
    for verb in ("update", "delete")
]

_TABLE_SCHEMAS = {
    "ledger": (
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
        "event_id",
    ),
    "workflows": (
        {"id": str, "title": str, "owner": str, "brief_json": str},
        "id",
    ),
    "runs": (
        {
            "run_id": str,
            "workflow_id": str,
            "capsule_id": str,
            "operator": str,
            "status": str,
            "updated_at": str,
            "state_json": str,  # full RuntimeState, schema-validated on load
        },
        "run_id",
    ),
    "observations": (
        {
            "id": str,
            "run_id": str,
            "capsule_id": str,
            "observer": str,
            "observed_at": str,
            "packet_json": str,  # full ObservationPacket
        },
        "id",
    ),
    "non_conformance_records": (
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
        "id",
    ),
    "graph_runs": (
        {
            "graph_run_id": str,
            "graph_id": str,
            "workflow_id": str,
            "run_id": str,
            "status": str,
            "current_node": str,
            "updated_at": str,
            "state_json": str,  # full GraphRunState checkpoint
        },
        "graph_run_id",
    ),
    "eval_results": (
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
        "result_id",
    ),
    "promotions": (
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
        "promotion_id",
    ),
    "capsules": (
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
        "id",
    ),
    # ------------------------------------------- human & cooperative workflow
    #
    # A draft is a working document: editable, keyed by workflow and version.
    # Everything below it is evidence and therefore append-only.
    "workflow_drafts": (
        {
            "workflow_id": str,
            "version": str,
            "name": str,
            "maturity": str,
            "updated_at": str,
            "draft_json": str,  # full HumanWorkflowDraft
        },
        ("workflow_id", "version"),
    ),
    # The report a promotion decision was made on, kept so the decision can be
    # audited against the exact findings and rule set version that produced it.
    "validation_reports": (
        {
            "report_id": str,
            "workflow_id": str,
            "workflow_version": str,
            "rule_set_version": str,
            "blocking_open": int,  # unresolved blocking findings at evaluation time
            "evaluated_at": str,
            "report_json": str,  # full ValidationReport
        },
        "report_id",
    ),
    # A human consciously accepting a non-blocking finding. Actor, timestamp
    # and rationale are all mandatory in the contract; this is where they live.
    "risk_acceptances": (
        {
            "acceptance_id": str,
            "workflow_id": str,
            "finding_id": str,
            "rule_id": str,
            "rule_version": str,
            "accepted_by": str,
            "accepted_at": str,
            "rationale": str,
        },
        "acceptance_id",
    ),
    # Every maturity transition, successful or refused. A refused promotion is
    # as much a part of the record as a granted one.
    "workflow_promotions": (
        {
            "promotion_id": str,
            "workflow_id": str,
            "from_maturity": str,
            "to_maturity": str,
            "granted": int,  # 1 = promotion happened, 0 = refused
            "promoted_by": str,
            "promoted_at": str,
            "rule_set_version": str,
            "schema_version": str,
            "report_id": str,  # the evidence cited
            "detail": str,  # refusal reason, or what was produced
        },
        "promotion_id",
    ),
    # The promoted artifact itself. Every promotion produces a row, and earlier
    # ones stay readable because an audit needs what was approved at the time.
    #
    # Keyed by maturity as well as version: a workflow climbs several steps at
    # the same draft version, and each step is its own artifact. Keying on
    # version alone would make the second promotion look like a duplicate of
    # the first.
    "accountable_workflows": (
        {
            "workflow_id": str,
            "version": str,
            "maturity": str,
            "promoted_by": str,
            "promoted_at": str,
            "artifact_json": str,  # full AccountableWorkflow
        },
        ("workflow_id", "version", "maturity"),
    ),
    # Stage-4 evidence: what was recommended for each step, and what a human
    # decided instead. Append-only with a surrogate key rather than keyed on
    # assessment_id, because `apply_override` returns a copy carrying the SAME
    # assessment_id — an override is a later row on top of the original, not an
    # edit of it. `load_cooperation_assessments` therefore returns the newest
    # row per step, and the earlier ones remain readable as the record of what
    # the table recommended before a person overruled it.
    "cooperation_assessments": (
        {
            "record_id": str,
            "workflow_id": str,
            "step_id": str,
            "assessment_id": str,
            "recommended_executor": str,
            "effective_executor": str,
            "safety_floor": str,
            "overridden": int,  # 1 = a human replaced the recommendation
            "recorded_at": str,
            "assessment_json": str,  # full CooperationAssessment
        },
        "record_id",
    ),
    # Stage-5 artifact. Append-only for the same reason: approving a built
    # workflow is a decision, so it lands as a new row and the unapproved build
    # it supersedes stays visible. An audit needs to see that the assignments
    # existed before anyone signed them.
    "cooperative_workflows": (
        {
            "record_id": str,
            "workflow_id": str,
            "version": str,
            "source_workflow_version": str,
            "approved": int,  # 1 = a named human approved the assignments
            "approved_by": str,
            "recorded_at": str,
            "artifact_json": str,  # full CooperativeWorkflow
        },
        "record_id",
    ),
}


class RunLedger:
    """Durable run history and state store backed by a local SQLite file."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        """Open (or create) the ledger database and ensure its tables exist."""
        self.db_path = Path(db_path)
        self.db = sqlite_utils.Database(self.db_path)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create tables and append-only triggers if they do not exist yet."""
        existing = self.db.table_names()
        for table_name, (columns, pk) in _TABLE_SCHEMAS.items():
            if table_name not in existing:
                self.db[table_name].create(columns, pk=pk)

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

    def _row_to_capsule(self, row: dict) -> ProcessCapsule:
        """Convert a database row into a ProcessCapsule instance."""
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

    def load_capsule(self, capsule_id: str) -> ProcessCapsule:
        """Load a capsule snapshot by id. Raises KeyError if unknown."""
        row = self.db["capsules"].get(capsule_id)
        return self._row_to_capsule(row)

    def capsules_for(self, workflow_id: str) -> list[ProcessCapsule]:
        """Return every capsule snapshot belonging to a workflow."""
        rows = self.db["capsules"].rows_where("workflow_id = ?", [workflow_id])
        return [self._row_to_capsule(row) for row in rows]

    def non_conforming_capsules(self) -> list[ProcessCapsule]:
        """Return every capsule currently in NON_CONFORMANCE, across all workflows."""
        rows = self.db["capsules"].rows_where(
            "status = ?", [CapsuleStatus.NON_CONFORMANCE.value]
        )
        return [self._row_to_capsule(row) for row in rows]

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

    # -------------------------------------------------------------- graph runs

    def save_graph_run(self, state: GraphRunState) -> None:
        """Checkpoint a graph run. Called after every node execution."""
        self.db["graph_runs"].upsert(
            {
                "graph_run_id": state.graph_run_id,
                "graph_id": state.graph_id,
                "workflow_id": state.workflow_id,
                "run_id": state.run_id,
                "status": state.status.value,
                "current_node": state.current_node,
                "updated_at": state.updated_at.isoformat(),
                "state_json": state.model_dump_json(),
            },
            pk="graph_run_id",
        )

    def load_graph_run(self, graph_run_id: str) -> GraphRunState:
        """Load a graph run checkpoint. Raises KeyError if unknown."""
        row = self.db["graph_runs"].get(graph_run_id)
        return GraphRunState.model_validate_json(row["state_json"])

    def list_graph_runs(self) -> list[GraphRunState]:
        """Return every graph run, newest first."""
        rows = self.db["graph_runs"].rows_where(order_by="updated_at desc")
        return [GraphRunState.model_validate_json(r["state_json"]) for r in rows]

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

    # ------------------------------------------ human & cooperative workflow

    def save_workflow_draft(self, draft: HumanWorkflowDraft) -> None:
        """Store or update an observed workflow draft.

        Drafts are the one mutable thing in this group: a draft is a working
        document people edit as they learn more, and refusing to save an
        incomplete one would make honest capture impossible. Everything derived
        from a draft is append-only.
        """
        self.db["workflow_drafts"].upsert(
            {
                "workflow_id": draft.workflow_id,
                "version": draft.version,
                "name": draft.name,
                "maturity": draft.maturity.value,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "draft_json": draft.model_dump_json(),
            },
            pk=("workflow_id", "version"),
        )

    def load_workflow_draft(
        self, workflow_id: str, version: str = ""
    ) -> HumanWorkflowDraft:
        """Load a draft. Without a version, returns the most recently updated.

        Raises KeyError when no draft matches, so a caller cannot mistake a
        missing workflow for an empty one. Both branches raise the same type:
        the version-pinned lookup used to leak sqlite_utils' NotFoundError,
        which reached the CLI as a traceback instead of a message.
        """
        if version:
            try:
                row = self.db["workflow_drafts"].get((workflow_id, version))
            except sqlite_utils.db.NotFoundError:
                raise KeyError(
                    f"no draft stored for workflow '{workflow_id}' version '{version}'"
                ) from None
            return HumanWorkflowDraft.model_validate_json(row["draft_json"])
        rows = list(
            self.db["workflow_drafts"].rows_where(
                "workflow_id = ?", [workflow_id], order_by="updated_at desc"
            )
        )
        if not rows:
            raise KeyError(f"no draft stored for workflow '{workflow_id}'")
        return HumanWorkflowDraft.model_validate_json(rows[0]["draft_json"])

    def list_workflow_drafts(self) -> list[HumanWorkflowDraft]:
        """Every stored draft, most recently updated first."""
        return [
            HumanWorkflowDraft.model_validate_json(r["draft_json"])
            for r in self.db["workflow_drafts"].rows_where(order_by="updated_at desc")
        ]

    def save_validation_report(self, report: ValidationReport) -> str:
        """Record a validation report and return its storage id.

        The id is generated here rather than carried on the contract: it is a
        handle for citing this evaluation from a promotion, not part of what a
        report *is*.
        """
        report_id = _new_id("vr")
        self.db["validation_reports"].insert(
            {
                "report_id": report_id,
                "workflow_id": report.workflow_id,
                "workflow_version": report.workflow_version,
                "rule_set_version": report.rule_set_version,
                "blocking_open": len(report.unresolved_blocking),
                "evaluated_at": report.evaluated_at.isoformat(),
                "report_json": report.model_dump_json(),
            }
        )
        return report_id

    def load_validation_report(self, report_id: str) -> ValidationReport:
        """Load a stored validation report by its storage id."""
        row = self.db["validation_reports"].get(report_id)
        return ValidationReport.model_validate_json(row["report_json"])

    def validation_reports_for(self, workflow_id: str) -> list[ValidationReport]:
        """Every report for a workflow, newest first."""
        return [
            ValidationReport.model_validate_json(r["report_json"])
            for r in self.db["validation_reports"].rows_where(
                "workflow_id = ?", [workflow_id], order_by="evaluated_at desc"
            )
        ]

    def save_risk_acceptance(
        self, workflow_id: str, acceptance: RiskAcceptance
    ) -> str:
        """Record a human accepting a finding as residual risk.

        Actor, timestamp and rationale are mandatory in the contract, so an
        acceptance that reaches here is always a decision on the record rather
        than a dismissed warning.
        """
        acceptance_id = _new_id("ra")
        self.db["risk_acceptances"].insert(
            {
                "acceptance_id": acceptance_id,
                "workflow_id": workflow_id,
                "finding_id": acceptance.finding_id,
                "rule_id": acceptance.rule.rule_id,
                "rule_version": acceptance.rule.rule_version,
                "accepted_by": acceptance.accepted_by,
                "accepted_at": acceptance.accepted_at.isoformat(),
                "rationale": acceptance.rationale,
            }
        )
        return acceptance_id

    def risk_acceptances_for(self, workflow_id: str) -> list[dict]:
        """Every accepted risk on a workflow, newest first."""
        return list(
            self.db["risk_acceptances"].rows_where(
                "workflow_id = ?", [workflow_id], order_by="accepted_at desc"
            )
        )

    def record_workflow_promotion(
        self,
        workflow_id: str,
        from_maturity: str,
        to_maturity: str,
        granted: bool,
        promoted_by: str,
        rule_set_version: str = "",
        schema_version: str = "",
        report_id: str = "",
        detail: str = "",
    ) -> str:
        """Append one maturity transition attempt to the audit trail.

        Refusals are recorded as well as grants. A promotion that was declined,
        and why, is part of a workflow's history — losing it would leave the
        record showing only the attempts that succeeded.
        """
        promotion_id = _new_id("wpromo")
        self.db["workflow_promotions"].insert(
            {
                "promotion_id": promotion_id,
                "workflow_id": workflow_id,
                "from_maturity": from_maturity,
                "to_maturity": to_maturity,
                "granted": 1 if granted else 0,
                "promoted_by": promoted_by,
                "promoted_at": datetime.now(timezone.utc).isoformat(),
                "rule_set_version": rule_set_version,
                "schema_version": schema_version,
                "report_id": report_id,
                "detail": detail,
            }
        )
        return promotion_id

    def workflow_promotions_for(self, workflow_id: str) -> list[dict]:
        """Every transition attempt on a workflow, newest first."""
        return list(
            self.db["workflow_promotions"].rows_where(
                "workflow_id = ?", [workflow_id], order_by="promoted_at desc"
            )
        )

    def save_accountable_workflow(self, artifact: AccountableWorkflow) -> None:
        """Store a promoted artifact. Earlier versions are never overwritten."""
        self.db["accountable_workflows"].insert(
            {
                "workflow_id": artifact.workflow_id,
                "version": artifact.version,
                "maturity": artifact.maturity.value,
                "promoted_by": artifact.lineage.promoted_by,
                "promoted_at": artifact.lineage.promoted_at.isoformat(),
                "artifact_json": artifact.model_dump_json(),
            }
        )

    def load_accountable_workflow(
        self, workflow_id: str, version: str = "", maturity: str = ""
    ) -> AccountableWorkflow:
        """Load a promoted artifact, newest first when unqualified.

        A workflow usually has several artifacts at one draft version — one per
        maturity step it climbed — so both filters are optional and narrow
        independently.
        """
        where, params = ["workflow_id = ?"], [workflow_id]
        if version:
            where.append("version = ?")
            params.append(version)
        if maturity:
            where.append("maturity = ?")
            params.append(maturity)
        rows = list(
            self.db["accountable_workflows"].rows_where(
                " and ".join(where), params, order_by="promoted_at desc"
            )
        )
        if not rows:
            raise KeyError(
                f"no accountable workflow stored for '{workflow_id}'"
                + (f" version '{version}'" if version else "")
                + (f" at {maturity}" if maturity else "")
            )
        return AccountableWorkflow.model_validate_json(rows[0]["artifact_json"])

    def has_accountable_artifact(
        self, workflow_id: str, version: str, maturity: str
    ) -> bool:
        """Whether this exact version has already been promoted to this maturity."""
        return any(
            self.db["accountable_workflows"].rows_where(
                "workflow_id = ? and version = ? and maturity = ?",
                [workflow_id, version, maturity],
            )
        )

    def accountable_workflow_versions(self, workflow_id: str) -> list[str]:
        """Every stored version of a promoted workflow, newest first."""
        return [
            r["version"]
            for r in self.db["accountable_workflows"].rows_where(
                "workflow_id = ?", [workflow_id], order_by="promoted_at desc"
            )
        ]

    # ------------------------------------------------- cooperation and export

    def save_cooperation_assessments(
        self, assessments: list[CooperationAssessment]
    ) -> list[str]:
        """Store a workflow's assessments, returning the new record ids.

        Written with one `insert_all`, so an interrupted save cannot leave a
        workflow half-assessed: SQLite applies the batch or none of it.

        Saving again after an override does not overwrite anything. The new row
        supersedes the old one for reads while the original remains as the
        record of what the decision table recommended before a person overruled
        it — which is the only way an override stays auditable.
        """
        recorded_at = datetime.now(timezone.utc).isoformat()
        rows = [
            {
                "record_id": _new_id("ca"),
                "workflow_id": a.workflow_id,
                "step_id": a.step_id,
                "assessment_id": a.assessment_id,
                "recommended_executor": a.recommended_executor.value,
                "effective_executor": a.effective_executor.value,
                "safety_floor": a.safety_floor.value,
                "overridden": 1 if a.override is not None else 0,
                "recorded_at": recorded_at,
                "assessment_json": a.model_dump_json(),
            }
            for a in assessments
        ]
        if not rows:
            return []
        self.db["cooperation_assessments"].insert_all(rows)
        return [r["record_id"] for r in rows]

    def load_cooperation_assessments(
        self, workflow_id: str
    ) -> list[CooperationAssessment]:
        """The current assessment for each step, newest row per step winning.

        Returns an empty list for a workflow that has never been assessed —
        absence is a normal state, not an error, and the caller decides whether
        it matters.
        """
        newest: dict[str, dict] = {}
        for row in self.db["cooperation_assessments"].rows_where(
            "workflow_id = ?", [workflow_id], order_by="recorded_at, rowid"
        ):
            # Ascending order means the last row seen for a step is its newest.
            newest[row["step_id"]] = row
        return [
            CooperationAssessment.model_validate_json(r["assessment_json"])
            for r in newest.values()
        ]

    def cooperation_assessment_history(self, workflow_id: str) -> list[dict]:
        """Every assessment row ever written for a workflow, oldest first.

        The audit view: shows a step's recommendation and any later override as
        separate events, which `load_cooperation_assessments` deliberately
        collapses.
        """
        return list(
            self.db["cooperation_assessments"].rows_where(
                "workflow_id = ?", [workflow_id], order_by="recorded_at, rowid"
            )
        )

    def save_cooperative_workflow(self, artifact: CooperativeWorkflow) -> str:
        """Store a built or approved cooperative workflow, returning its record id.

        Never overwrites. Approving a workflow writes a second row whose
        `approved` flag is set; the unapproved build stays readable, because an
        audit needs to see that the assignments existed before anyone signed
        them.
        """
        record_id = _new_id("cw")
        self.db["cooperative_workflows"].insert(
            {
                "record_id": record_id,
                "workflow_id": artifact.workflow_id,
                "version": artifact.version,
                "source_workflow_version": artifact.source_workflow_version,
                "approved": 1 if artifact.approved else 0,
                "approved_by": artifact.approved_by,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "artifact_json": artifact.model_dump_json(),
            }
        )
        return record_id

    def load_cooperative_workflow(
        self, workflow_id: str, version: str = ""
    ) -> CooperativeWorkflow:
        """Load the newest cooperative workflow, optionally pinned to a version."""
        where, params = ["workflow_id = ?"], [workflow_id]
        if version:
            where.append("version = ?")
            params.append(version)
        rows = list(
            self.db["cooperative_workflows"].rows_where(
                " and ".join(where), params, order_by="recorded_at desc, rowid desc"
            )
        )
        if not rows:
            raise KeyError(
                f"no cooperative workflow stored for '{workflow_id}'"
                + (f" version '{version}'" if version else "")
            )
        return CooperativeWorkflow.model_validate_json(rows[0]["artifact_json"])

    def has_cooperative_workflow(self, workflow_id: str) -> bool:
        """Whether any cooperative workflow has been built for this workflow."""
        return any(
            self.db["cooperative_workflows"].rows_where(
                "workflow_id = ?", [workflow_id]
            )
        )
