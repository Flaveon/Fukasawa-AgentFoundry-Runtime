# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Release-verification finding F1: a paused run must not silently resume
under a different brief.

`WorkflowRuntime.resume_run()` (src/runtime/state_machine.py) and
`GraphRunner.resume()` (src/kernel/kernel.py) are both FROZEN — they reload
whatever brief snapshot `RunLedger.load_workflow()` currently holds for the
workflow id, with no check that it is the same brief the run actually
started under. If a brief gets re-saved under the same id (someone edits it
and runs `fukasawa run` or `fukasawa graph run` again before the first run
is resumed), the resumed run silently inherits the new rules — including,
for instance, a transition whose `evidence_required` was quietly emptied
out.

The fix lives entirely in `src/runtime/ledger.py` (an append-only history of
every distinct brief snapshot, content-hashed and dated) and in
`src/cli.py`'s `resume`/`graph resume` commands (a `_refuse_if_brief_drifted`
gate called before either frozen `resume()` runs). Neither FROZEN file is
touched.
"""

from pathlib import Path

import pytest
import typer
import yaml
from typer.testing import CliRunner

from src.cli import _refuse_if_brief_drifted, app
from src.kernel.kernel import GraphRunner, load_graph
from src.runtime.ledger import RunLedger
from src.runtime.state_machine import WorkflowRuntime

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_BRIEF = ROOT / "examples" / "q2c-production-handoff.yaml"
PILOT_GRAPH = ROOT / "examples" / "q2c-pipeline-graph.yaml"


def _tampered_brief(tmp_path: Path) -> Path:
    """The example brief, same id, with the first transition's required
    evidence quietly emptied out — the exact repro from the F1 report."""
    data = yaml.safe_load(EXAMPLE_BRIEF.read_text(encoding="utf-8"))
    for t in data["transitions"]:
        if t["from_state"] == "RESEARCH_COMPLETE" and t["to_state"] == "DRAFT_READY":
            t["evidence_required"] = ""
    path = tmp_path / "tampered-brief.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


class TestLedgerBriefPinning:
    """The hashing/history primitives in ledger.py that the CLI gate reads."""

    def test_current_brief_hash_is_none_before_any_save(self, tmp_path):
        ledger = RunLedger(tmp_path / "t.db")
        assert ledger.current_brief_hash("q2c-production-handoff") is None

    def test_current_brief_hash_tracks_the_latest_content(self, tmp_path):
        ledger = RunLedger(tmp_path / "t.db")
        brief_v1 = WorkflowRuntime.load_brief(EXAMPLE_BRIEF)
        ledger.save_workflow(brief_v1)
        hash_v1 = ledger.current_brief_hash(brief_v1.id)
        assert hash_v1 is not None

        brief_v2 = WorkflowRuntime.load_brief(_tampered_brief(tmp_path))
        ledger.save_workflow(brief_v2)
        hash_v2 = ledger.current_brief_hash(brief_v2.id)
        assert hash_v2 != hash_v1

    def test_resaving_identical_content_does_not_grow_the_history(self, tmp_path):
        ledger = RunLedger(tmp_path / "t.db")
        brief = WorkflowRuntime.load_brief(EXAMPLE_BRIEF)
        ledger.save_workflow(brief)
        ledger.save_workflow(brief)
        ledger.save_workflow(brief)
        rows = list(
            ledger.db["workflow_snapshots"].rows_where(
                "workflow_id = ?", [brief.id]
            )
        )
        assert len(rows) == 1

    def test_brief_hash_at_pins_the_hash_current_when_a_run_started(self, tmp_path):
        ledger = RunLedger(tmp_path / "t.db")
        runtime = WorkflowRuntime(ledger)
        brief_v1 = runtime.load_brief(EXAMPLE_BRIEF)
        _, run = runtime.start(brief_v1, brief_path=EXAMPLE_BRIEF)
        pinned_at_start = ledger.brief_hash_at(brief_v1.id, run.created_at)
        assert pinned_at_start == ledger.current_brief_hash(brief_v1.id)

        # The brief changes under the same id after the run started.
        brief_v2 = runtime.load_brief(_tampered_brief(tmp_path))
        ledger.save_workflow(brief_v2)
        # The run's pin is unaffected by the later save...
        assert ledger.brief_hash_at(brief_v1.id, run.created_at) == pinned_at_start
        # ...but the current hash has moved on.
        assert ledger.current_brief_hash(brief_v1.id) != pinned_at_start


class TestRefuseIfBriefDrifted:
    """Direct tests of the CLI gate, independent of any particular command."""

    def test_refuses_when_no_pin_exists(self, tmp_path):
        # Simulates a database that predates workflow_snapshots: a run
        # exists (saved directly, bypassing start()/save_workflow()) whose
        # workflow id has no snapshot history at all — append-only means
        # this cannot be reproduced by deleting rows after the fact, so the
        # run is constructed to never have had one in the first place.
        from src.schemas.runtime_state import RuntimeState
        from src.schemas.workflow_brief import TaskDepth

        ledger = RunLedger(tmp_path / "t.db")
        run = RuntimeState(
            run_id="run-nopin",
            workflow_id="never-snapshotted",
            workflow_name="Never Snapshotted",
            capsule_id="capsule-nopin",
            operator="flaveon",
            current_state="START",
            task_depth=TaskDepth.GUIDED,
        )
        ledger.save_run(run)
        assert ledger.current_brief_hash(run.workflow_id) is None

        with pytest.raises(typer.Exit) as exc:
            _refuse_if_brief_drifted(ledger, run)
        assert exc.value.exit_code == 1

    def test_refuses_when_brief_changed_after_run_started(self, tmp_path):
        ledger = RunLedger(tmp_path / "t.db")
        runtime = WorkflowRuntime(ledger)
        brief_v1 = runtime.load_brief(EXAMPLE_BRIEF)
        _, run = runtime.start(brief_v1, brief_path=EXAMPLE_BRIEF)
        brief_v2 = runtime.load_brief(_tampered_brief(tmp_path))
        ledger.save_workflow(brief_v2)
        with pytest.raises(typer.Exit) as exc:
            _refuse_if_brief_drifted(ledger, run)
        assert exc.value.exit_code == 1

    def test_allows_when_brief_is_unchanged(self, tmp_path):
        ledger = RunLedger(tmp_path / "t.db")
        runtime = WorkflowRuntime(ledger)
        brief = runtime.load_brief(EXAMPLE_BRIEF)
        _, run = runtime.start(brief, brief_path=EXAMPLE_BRIEF)
        _refuse_if_brief_drifted(ledger, run)  # must not raise


class TestFukasawaResumeCLI:
    """End-to-end repro of the F1 report through the actual `fukasawa`
    command-line entry points."""

    def test_resume_refuses_a_run_whose_brief_changed_underneath_it(self, tmp_path):
        db = tmp_path / "r.db"
        handoff_dir = tmp_path / "handoffs"
        runner = CliRunner()

        # `fukasawa run brief.yaml --db r.db` — advance once, then quit.
        result = runner.invoke(
            app,
            ["run", str(EXAMPLE_BRIEF), "--db", str(db), "--handoff-dir", str(handoff_dir)],
            input="DRAFT_READY\ndraft.md\n\nquit\n\n\n",
        )
        assert result.exit_code == 0, result.stdout
        first_run_id = RunLedger(db).list_runs()[0].run_id

        # A modified brief, same id, gets run (and immediately paused) —
        # exactly the "edit and re-run" step from the report.
        tampered = _tampered_brief(tmp_path)
        result = runner.invoke(
            app,
            ["run", str(tampered), "--db", str(db), "--handoff-dir", str(handoff_dir)],
            input="quit\n\n\n",
        )
        assert result.exit_code == 0, result.stdout

        # `fukasawa resume <first run id> --db r.db` must now refuse.
        result = runner.invoke(
            app,
            ["resume", first_run_id, "--db", str(db), "--handoff-dir", str(handoff_dir)],
        )
        assert result.exit_code == 1
        assert "brief" in result.stdout and "changed" in result.stdout

    def test_resume_still_works_when_the_brief_never_changed(self, tmp_path):
        db = tmp_path / "r.db"
        handoff_dir = tmp_path / "handoffs"
        runner = CliRunner()

        result = runner.invoke(
            app,
            ["run", str(EXAMPLE_BRIEF), "--db", str(db), "--handoff-dir", str(handoff_dir)],
            input="quit\n\n\n",
        )
        assert result.exit_code == 0, result.stdout
        run_id = RunLedger(db).list_runs()[0].run_id

        result = runner.invoke(
            app,
            ["resume", run_id, "--db", str(db), "--handoff-dir", str(handoff_dir)],
            input="quit\n\n\n",
        )
        assert result.exit_code == 0, result.stdout
        assert "refused" not in result.stdout.lower()


class TestGraphResumeCLI:
    """The same gate, exercised through `fukasawa graph resume`."""

    def test_graph_resume_refuses_when_brief_changed_underneath_a_blocked_run(
        self, tmp_path
    ):
        db = tmp_path / "r.db"
        handoff_dir = tmp_path / "handoffs"
        ledger = RunLedger(db)
        graph_runner = GraphRunner(ledger, handoff_dir=handoff_dir)
        brief = graph_runner.runtime.load_brief(EXAMPLE_BRIEF)
        graph = load_graph(PILOT_GRAPH)

        # An empty workdir makes the first node fail and the graph block —
        # cheaper to set up than a full run, and irrelevant to this gate:
        # the brief check fires before any node executes.
        empty = tmp_path / "empty"
        empty.mkdir()
        variables = {"workdir": str(empty), "destdir": str(tmp_path / "published")}
        state = graph_runner.start(graph, brief, variables=variables, brief_path=EXAMPLE_BRIEF)
        state = graph_runner.run(graph, state)
        from src.schemas.graph import GraphRunStatus

        assert state.status is GraphRunStatus.BLOCKED

        # The brief changes under the same id after the run started.
        tampered = graph_runner.runtime.load_brief(_tampered_brief(tmp_path))
        ledger.save_workflow(tampered)

        result = CliRunner().invoke(
            app,
            [
                "graph", "resume", state.graph_run_id,
                "--graph", str(PILOT_GRAPH),
                "--db", str(db),
                "--handoff-dir", str(handoff_dir),
            ],
        )
        assert result.exit_code == 1
        assert "brief" in result.stdout and "changed" in result.stdout
