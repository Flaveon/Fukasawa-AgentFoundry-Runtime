# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Orchestration kernel tests.

The Phase 4 exit criteria, made executable:
* one pilot workflow runs end-to-end through persisted states,
* failed nodes produce non-conformance records or blocked-state artifacts,
* the state graph remains inspectable without a framework UI.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.kernel.adapters import AdapterRegistry, AdapterResult
from src.kernel.kernel import GraphRunner, GraphSpecError, load_graph
from src.runtime.ledger import RunLedger
from src.runtime.review_gate import ReviewDecision
from src.runtime.state_machine import WorkflowRuntime
from src.schemas.graph import GraphRunStatus, GraphSpec
from src.schemas.process_capsule import CapsuleStatus
from src.schemas.runtime_state import RunStatus

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_BRIEF = ROOT / "examples" / "q2c-production-handoff.yaml"
PILOT_GRAPH = ROOT / "examples" / "q2c-pipeline-graph.yaml"


@pytest.fixture()
def runner(tmp_path) -> GraphRunner:
    return GraphRunner(
        RunLedger(tmp_path / "test.db"), handoff_dir=tmp_path / "handoffs"
    )


@pytest.fixture()
def brief(runner):
    return runner.runtime.load_brief(EXAMPLE_BRIEF)


@pytest.fixture()
def graph() -> GraphSpec:
    return load_graph(PILOT_GRAPH)


@pytest.fixture()
def workdir(tmp_path) -> Path:
    wd = tmp_path / "work"
    wd.mkdir()
    (wd / "research.md").write_text("# Research\n" + "word " * 200)
    return wd


def _vars(workdir: Path, tmp_path: Path) -> dict[str, str]:
    return {"workdir": str(workdir), "destdir": str(tmp_path / "published")}


class TestGraphSpec:
    def test_pilot_graph_fits_pilot_brief(self, graph, brief):
        assert graph.validate_against_brief(brief) == []

    def test_unknown_next_rejected(self):
        with pytest.raises(ValidationError, match="unknown next node"):
            GraphSpec.model_validate(
                {
                    "graph_id": "g",
                    "workflow": "w",
                    "nodes": [
                        {
                            "node_id": "a",
                            "kind": "deterministic",
                            "adapter": "filesystem",
                            "next": "ghost",
                        }
                    ],
                }
            )

    def test_gate_without_reason_rejected(self):
        with pytest.raises(ValidationError, match="gate_reason"):
            GraphSpec.model_validate(
                {
                    "graph_id": "g",
                    "workflow": "w",
                    "nodes": [{"node_id": "gate", "kind": "human_gate"}],
                }
            )

    def test_transition_not_in_brief_is_a_finding(self, brief):
        bad = GraphSpec.model_validate(
            {
                "graph_id": "bad-graph",
                "workflow": "q2c-production-handoff",
                "nodes": [
                    {
                        "node_id": "leap",
                        "kind": "agent",
                        "adapter": "shell",
                        "params": {"command": "true"},
                        "produces_transition": {"to_state": "PUBLISHED"},
                    }
                ],
            }
        )
        findings = bad.validate_against_brief(brief)
        assert findings and "only allows" in findings[0]


class TestEndToEnd:
    """Exit criterion: pilot workflow end-to-end through persisted states."""

    def test_pilot_graph_runs_to_completion(
        self, runner, brief, graph, workdir, tmp_path
    ):
        state = runner.start(
            graph, brief, variables=_vars(workdir, tmp_path), brief_path=EXAMPLE_BRIEF
        )
        state = runner.run(graph, state)
        # Paused at the editor gate — the kernel cannot approve itself.
        assert state.status is GraphRunStatus.PAUSED_HUMAN
        assert state.current_node == "editor-gate"
        run = runner.ledger.load_run(state.run_id)
        assert run.status is RunStatus.HUMAN_REVIEW

        state = runner.decide(
            graph, state, ReviewDecision.APPROVE, evidence="editor sign-off: clean"
        )
        state = runner.run(graph, state)
        assert state.status is GraphRunStatus.COMPLETE
        # The capsule went through the real state machine to PUBLISHED.
        capsule = runner.ledger.load_capsule(state.capsule_id)
        assert capsule.state == "PUBLISHED"
        assert capsule.status is CapsuleStatus.COMPLETE
        # The article actually moved.
        assert (tmp_path / "published" / "article-final.md").exists()
        # Ledger holds the full conforming trail.
        events = runner.ledger.history(brief.id)
        assert [e["to_state"] for e in events] == [
            "RESEARCH_COMPLETE", "DRAFT_READY", "EDITOR_REVIEW", "APPROVED", "PUBLISHED",
        ]
        # Final handoff artifact exists.
        assert (tmp_path / "handoffs" / f"{state.run_id}.md").exists()

    def test_checkpoint_survives_process_death(
        self, runner, brief, graph, workdir, tmp_path
    ):
        state = runner.start(graph, brief, variables=_vars(workdir, tmp_path))
        state = runner.run(graph, state)  # pauses at the gate
        graph_run_id = state.graph_run_id

        # A brand-new runner (fresh process, same db) picks up the checkpoint.
        fresh = GraphRunner(
            RunLedger(tmp_path / "test.db"), handoff_dir=tmp_path / "handoffs"
        )
        restored = fresh.resume(graph, graph_run_id)
        assert restored.status is GraphRunStatus.PAUSED_HUMAN  # resume never decides
        restored = fresh.decide(graph, restored, ReviewDecision.APPROVE, evidence="ok")
        restored = fresh.run(graph, restored)
        assert restored.status is GraphRunStatus.COMPLETE
        # History from before the "death" was preserved.
        assert [e.node_id for e in restored.history][:3] == [
            "check-research", "produce-draft", "submit-review",
        ]


class TestFailureHandling:
    """Exit criterion: failed nodes produce NCRs or blocked-state artifacts."""

    def test_missing_research_retries_then_blocks_with_artifact(
        self, runner, brief, graph, tmp_path
    ):
        empty = tmp_path / "empty"
        empty.mkdir()
        state = runner.start(graph, brief, variables=_vars(empty, tmp_path))
        state = runner.run(graph, state)
        assert state.status is GraphRunStatus.BLOCKED
        # Blocked-state artifact: the handoff file with reason + next action.
        handoff = (tmp_path / "handoffs" / f"{state.run_id}.md").read_text()
        assert "check-research" in handoff
        assert f"fukasawa graph resume {state.graph_run_id}" in handoff
        run = runner.ledger.load_run(state.run_id)
        assert run.status is RunStatus.BLOCKED
        assert "does not exist" in run.blocked_reason

    def test_blocked_run_resumes_after_fix(self, runner, brief, graph, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        state = runner.start(graph, brief, variables=_vars(empty, tmp_path))
        state = runner.run(graph, state)
        assert state.status is GraphRunStatus.BLOCKED
        # Fix the cause, then resume from the checkpoint.
        (empty / "research.md").write_text("# Research\nfixed")
        state = runner.resume(graph, state.graph_run_id)
        assert state.status is GraphRunStatus.PAUSED_HUMAN  # made it to the gate
        # The failed attempts are still in the trace — history is not cleaned.
        failures = [e for e in state.history if not e.ok]
        assert failures and failures[0].node_id == "check-research"

    def test_retry_policy_counts_attempts(self, runner, brief, tmp_path):
        flaky = GraphSpec.model_validate(
            {
                "graph_id": "flaky-graph",
                "workflow": "q2c-production-handoff",
                "nodes": [
                    {
                        "node_id": "always-fails",
                        "kind": "agent",
                        "adapter": "shell",
                        "params": {"command": "false"},
                        "retry": {"max_attempts": 3},
                    }
                ],
            }
        )
        state = runner.start(flaky, brief)
        state = runner.run(flaky, state)
        assert state.status is GraphRunStatus.BLOCKED
        assert [e.attempt for e in state.history] == [1, 2, 3]

    def test_gate_reject_fails_run_with_ncr(
        self, runner, brief, graph, workdir, tmp_path
    ):
        state = runner.start(graph, brief, variables=_vars(workdir, tmp_path))
        state = runner.run(graph, state)
        state = runner.decide(
            graph, state, ReviewDecision.REJECT, note="draft not on brand"
        )
        assert state.status is GraphRunStatus.FAILED
        capsule = runner.ledger.load_capsule(state.capsule_id)
        assert capsule.status is CapsuleStatus.NON_CONFORMANCE
        records = runner.ledger.non_conformance_records()
        assert any(r.kind.value == "review_rejected" for r in records)

    def test_unknown_adapter_blocks_not_crashes(self, runner, brief):
        graph = GraphSpec.model_validate(
            {
                "graph_id": "bad-adapter-graph",
                "workflow": "q2c-production-handoff",
                "nodes": [
                    {
                        "node_id": "mystery",
                        "kind": "agent",
                        "adapter": "quantum",
                        "params": {},
                    }
                ],
            }
        )
        state = runner.start(graph, brief)
        state = runner.run(graph, state)
        assert state.status is GraphRunStatus.BLOCKED
        assert "no adapter 'quantum'" in state.history[-1].note


class TestInspectability:
    """Exit criterion: the state graph is inspectable without a framework UI."""

    def test_trace_is_plain_queryable_data(
        self, runner, brief, graph, workdir, tmp_path
    ):
        state = runner.start(graph, brief, variables=_vars(workdir, tmp_path))
        runner.run(graph, state)
        # Straight from SQLite, no kernel object needed.
        import sqlite_utils

        db = sqlite_utils.Database(tmp_path / "test.db")
        row = db["graph_runs"].get(state.graph_run_id)
        assert row["status"] == "paused_human"
        assert row["current_node"] == "editor-gate"
        # The checkpoint re-validates as a schema on load.
        restored = runner.ledger.load_graph_run(state.graph_run_id)
        assert [e.node_id for e in restored.history] == [
            "check-research", "produce-draft", "submit-review",
        ]
        assert all(e.evidence for e in restored.history if e.ok)


class TestAdapterRegistry:
    def test_custom_adapter_plugs_in(self, tmp_path, brief):
        class CountingAdapter:
            name = "counting"

            def __init__(self):
                self.calls = 0

            def execute(self, params):
                self.calls += 1
                return AdapterResult(ok=True, evidence=f"call {self.calls}")

        registry = AdapterRegistry()
        counting = CountingAdapter()
        registry.register(counting)
        runner = GraphRunner(
            RunLedger(tmp_path / "t.db"), registry=registry,
            handoff_dir=tmp_path / "h",
        )
        graph = GraphSpec.model_validate(
            {
                "graph_id": "custom-graph",
                "workflow": "q2c-production-handoff",
                "nodes": [
                    {
                        "node_id": "count",
                        "kind": "agent",
                        "adapter": "counting",
                        "params": {},
                    }
                ],
            }
        )
        state = runner.start(graph, brief)
        state = runner.run(graph, state)
        assert counting.calls == 1
        assert state.status is GraphRunStatus.COMPLETE
