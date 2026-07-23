# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""State machine and ledger tests: invalid transitions, evidence, resumption.

Each test gets its own SQLite file via tmp_path, so tests cannot contaminate
each other's ledgers — an append-only audit trail makes cleanup-by-deletion
impossible by design.
"""

import sqlite3
from pathlib import Path

import pytest

from src.runtime.ledger import RunLedger
from src.runtime.state_machine import NonConformanceError, WorkflowRuntime
from src.schemas.non_conformance import NonConformanceKind
from src.schemas.process_capsule import CapsuleStatus
from src.schemas.runtime_state import RunStatus
from src.schemas.workflow_brief import WorkflowBrief

EXAMPLE_BRIEF = (
    Path(__file__).resolve().parent.parent / "examples" / "q2c-production-handoff.yaml"
)


@pytest.fixture()
def runtime(tmp_path) -> WorkflowRuntime:
    return WorkflowRuntime(RunLedger(tmp_path / "test.db"))


@pytest.fixture()
def brief(runtime) -> WorkflowBrief:
    return runtime.load_brief(EXAMPLE_BRIEF)


class TestAdvance:
    def test_happy_path_updates_capsule_run_and_ledger(self, runtime, brief):
        capsule, run = runtime.start(brief, brief_path=EXAMPLE_BRIEF)
        capsule = runtime.advance(
            brief, capsule, "DRAFT_READY", evidence="~/draft.md", run=run
        )
        assert capsule.state == "DRAFT_READY"
        assert capsule.status is CapsuleStatus.IN_PROGRESS
        assert run.status is RunStatus.RUNNING
        assert run.current_state == "DRAFT_READY"
        events = runtime.ledger.history(brief.id)
        assert [e["to_state"] for e in events] == ["RESEARCH_COMPLETE", "DRAFT_READY"]
        assert all(e["conforming"] for e in events)

    def test_missing_evidence_refused_capsule_stays_put(self, runtime, brief):
        capsule, run = runtime.start(brief)
        with pytest.raises(NonConformanceError, match="required evidence missing"):
            runtime.advance(brief, capsule, "DRAFT_READY", evidence="   ", run=run)
        # Capsule did not move and is retryable; run is not failed.
        reloaded = runtime.ledger.load_capsule(capsule.id)
        assert reloaded.state == "RESEARCH_COMPLETE"
        assert reloaded.status is not CapsuleStatus.NON_CONFORMANCE
        assert runtime.ledger.load_run(run.run_id).status is not RunStatus.FAILED
        # Structured record captured the failure kind.
        records = runtime.ledger.non_conformance_records()
        assert len(records) == 1
        assert records[0].kind is NonConformanceKind.MISSING_EVIDENCE

    def test_no_valid_path_freezes_capsule_and_fails_run(self, runtime, brief):
        capsule, run = runtime.start(brief)
        with pytest.raises(NonConformanceError, match="no valid transition"):
            runtime.advance(brief, capsule, "PUBLISHED", evidence="yolo", run=run)
        reloaded = runtime.ledger.load_capsule(capsule.id)
        assert reloaded.status is CapsuleStatus.NON_CONFORMANCE
        assert "Exception path" in (reloaded.non_conformance_note or "")
        assert runtime.ledger.load_run(run.run_id).status is RunStatus.FAILED
        records = runtime.ledger.non_conformance_records()
        assert records[0].kind is NonConformanceKind.NO_VALID_PATH

    def test_terminal_state_completes_capsule_and_run_with_check(self, runtime, brief):
        capsule, run = runtime.start(brief)
        for state, ev in [
            ("DRAFT_READY", "draft.md"),
            ("EDITOR_REVIEW", "submitted"),
            ("APPROVED", "sign-off"),
            ("PUBLISHED", "final.md -> ~/substack/"),
        ]:
            capsule = runtime.advance(brief, capsule, state, evidence=ev, run=run)
        assert capsule.status is CapsuleStatus.COMPLETE
        assert capsule.completed_at is not None
        assert run.status is RunStatus.COMPLETE
        # Completion carried a passing verification check (contract rule).
        assert any(c.result.value == "pass" for c in run.completed_checks)


class TestLedgerImmutability:
    def test_ledger_rejects_update_and_delete(self, runtime, brief):
        capsule, run = runtime.start(brief)
        db = sqlite3.connect(runtime.ledger.db_path)
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute("UPDATE ledger SET evidence='tampered'")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute("DELETE FROM ledger")


class TestResume:
    def test_run_resumes_from_persisted_state(self, runtime, brief, tmp_path):
        capsule, run = runtime.start(brief, brief_path=EXAMPLE_BRIEF)
        capsule = runtime.advance(brief, capsule, "DRAFT_READY", "draft.md", run=run)
        runtime.block_run(run, reason="editor unavailable", next_action="resume Monday")
        assert runtime.ledger.load_run(run.run_id).status is RunStatus.BLOCKED

        # A completely fresh runtime (new process, same db) picks it back up.
        fresh = WorkflowRuntime(RunLedger(tmp_path / "test.db"))
        brief2, capsule2, run2 = fresh.resume_run(run.run_id)
        assert capsule2.state == "DRAFT_READY"
        assert run2.status is RunStatus.RUNNING
        assert run2.blocked_reason == ""
        # And the run can actually continue.
        capsule2 = fresh.advance(brief2, capsule2, "EDITOR_REVIEW", "submitted", run=run2)
        assert capsule2.state == "EDITOR_REVIEW"

    def test_blocked_without_next_action_is_impossible(self, runtime, brief):
        capsule, run = runtime.start(brief)
        with pytest.raises(Exception):
            runtime.block_run(run, reason="stuck", next_action="")
