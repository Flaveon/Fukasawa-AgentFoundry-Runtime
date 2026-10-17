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
every distinct brief snapshot, content-hashed and dated, plus an explicit
`run_brief_pins` table) and in `src/cli.py` (a `_refuse_if_brief_drifted`
gate). Neither FROZEN file is touched.

Gate G re-review findings addressed here too:

* **R1** — the gate was originally wired into only `resume` and
  `graph resume`. `review`, `runs block` and `runs complete` also continue
  an existing run under its brief's rules (`review` reaches
  `runtime.advance()` the same way `resume` does) and are gated the same
  way now. `TestAllRunContinuingCommandsAreGated` walks the exact F1 repro
  through every one of them.
* **R5** — the pin is now recorded *explicitly*, by `run`/`graph run`
  calling `ledger.pin_run_brief()` right after the frozen `start()`
  returns, rather than only inferred after the fact from `created_at`. The
  time-based `brief_hash_at()` lookup remains as a fallback for a run with
  no explicit pin (started before `run_brief_pins` existed), and is still
  exercised by `TestLedgerBriefPinning`/`TestRefuseIfBriefDrifted` below,
  which construct runs the old way on purpose.
* **R2** — the refusal message now names the way out in plain language:
  start a fresh `fukasawa run`, and the old run stays in the ledger as
  history. `test_refusal_message_names_the_recovery_path` checks the exact
  wording. No override command was added — accepting a changed brief for a
  specific run is a decision for the workflow owner, not this CLI.
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


class TestExplicitPinAtRunStart:
    """Gate G re-review finding R5: the pin is recorded explicitly by the
    CLI, not only inferred after the fact from a clock reading."""

    def test_a_save_racing_the_start_cannot_choose_the_pin(self, tmp_path, monkeypatch):
        """Round-3 finding R5b. Another process saves an edited brief under the
        same id between ``start()`` and the pin. The run must still be pinned
        to the brief it started with, and resuming under the edited one must
        be refused."""
        from src.runtime.ledger import brief_content_hash

        db = str(tmp_path / "r.db")
        handoff_dir = str(tmp_path / "handoffs")
        tampered = WorkflowRuntime.load_brief(_tampered_brief(tmp_path))
        real_start = WorkflowRuntime.start

        def racing_start(self, brief, *args, **kwargs):
            """Start for real, then let 'another process' save the edit."""
            out = real_start(self, brief, *args, **kwargs)
            RunLedger(db).save_workflow(tampered)
            return out

        monkeypatch.setattr(WorkflowRuntime, "start", racing_start)
        CliRunner().invoke(
            app, ["run", str(EXAMPLE_BRIEF), "--db", db, "--handoff-dir", handoff_dir],
            input="quit\n\n\n",
        )
        monkeypatch.undo()

        ledger = RunLedger(db)
        run = ledger.list_runs()[0]
        started = brief_content_hash(WorkflowRuntime.load_brief(EXAMPLE_BRIEF))
        assert ledger.pinned_brief_hash(run.run_id) == started
        assert started != brief_content_hash(tampered)

        resumed = CliRunner().invoke(
            app, ["resume", run.run_id, "--db", db, "--handoff-dir", handoff_dir],
            input="quit\n\n\n",
        )
        assert resumed.exit_code != 0

    def test_a_save_racing_a_graph_start_cannot_choose_the_pin(self, tmp_path, monkeypatch):
        """R5b through ``graph run``, which pins separately from ``run``."""
        from src.runtime.ledger import brief_content_hash

        db = str(tmp_path / "r.db")
        workdir = tmp_path / "w"
        workdir.mkdir()
        (workdir / "research.md").write_text("# R\n" + "word " * 200)
        tampered = WorkflowRuntime.load_brief(_tampered_brief(tmp_path))
        real_start = WorkflowRuntime.start

        def racing_start(self, brief, *args, **kwargs):
            """Start for real, then let 'another process' save the edit."""
            out = real_start(self, brief, *args, **kwargs)
            RunLedger(db).save_workflow(tampered)
            return out

        monkeypatch.setattr(WorkflowRuntime, "start", racing_start)
        CliRunner().invoke(app, [
            "graph", "run", str(PILOT_GRAPH), "--brief", str(EXAMPLE_BRIEF),
            "--var", f"workdir={workdir}", "--var", f"destdir={tmp_path / 'p'}",
            "--db", db, "--handoff-dir", str(tmp_path / "h"),
        ])
        monkeypatch.undo()

        ledger = RunLedger(db)
        run = ledger.list_runs()[0]
        started = brief_content_hash(WorkflowRuntime.load_brief(EXAMPLE_BRIEF))
        assert ledger.pinned_brief_hash(run.run_id) == started

    def test_fukasawa_run_records_an_explicit_pin(self, tmp_path):
        db = tmp_path / "r.db"
        handoff_dir = tmp_path / "handoffs"
        result = CliRunner().invoke(
            app,
            ["run", str(EXAMPLE_BRIEF), "--db", str(db), "--handoff-dir", str(handoff_dir)],
            input="quit\n\n\n",
        )
        assert result.exit_code == 0, result.stdout
        ledger = RunLedger(db)
        run = ledger.list_runs()[0]
        pinned = ledger.pinned_brief_hash(run.run_id)
        assert pinned is not None
        assert pinned == ledger.current_brief_hash(run.workflow_id)

    def test_fukasawa_graph_run_records_an_explicit_pin(self, tmp_path):
        db = tmp_path / "r.db"
        handoff_dir = tmp_path / "handoffs"
        workdir = tmp_path / "work"
        workdir.mkdir()
        (workdir / "research.md").write_text("# Research\n" + "word " * 200)
        # The graph drives on to a human review gate, which needs more
        # stdin than this test supplies — irrelevant here: the pin is
        # recorded immediately after `runner.start()` returns, well before
        # `_drive_graph` reaches that gate, so it exists regardless of how
        # (or whether) the interactive loop that follows completes.
        CliRunner().invoke(
            app,
            [
                "graph", "run", str(PILOT_GRAPH),
                "--brief", str(EXAMPLE_BRIEF),
                "--var", f"workdir={workdir}",
                "--var", f"destdir={tmp_path / 'published'}",
                "--db", str(db),
                "--handoff-dir", str(handoff_dir),
            ],
        )
        ledger = RunLedger(db)
        run = ledger.list_runs()[0]
        pinned = ledger.pinned_brief_hash(run.run_id)
        assert pinned is not None
        assert pinned == ledger.current_brief_hash(run.workflow_id)

    def test_explicit_pin_takes_precedence_over_the_time_based_fallback(
        self, tmp_path
    ):
        # A corrupted/mismatched explicit pin must actually be read and
        # compared, not silently ignored in favour of the fallback lookup
        # that would otherwise accept this run (it is the same brief, so
        # brief_hash_at alone would return a match).
        ledger = RunLedger(tmp_path / "t.db")
        runtime = WorkflowRuntime(ledger)
        brief = runtime.load_brief(EXAMPLE_BRIEF)
        _, run = runtime.start(brief, brief_path=EXAMPLE_BRIEF)
        _refuse_if_brief_drifted(ledger, run)  # no explicit pin yet: fallback matches

        ledger.pin_run_brief(run.run_id, brief.id, "deliberately-wrong-hash")
        with pytest.raises(typer.Exit):
            _refuse_if_brief_drifted(ledger, run)


class TestAllRunContinuingCommandsAreGated:
    """Gate G re-review finding R1: every CLI command that continues an
    existing run under its brief's rules must refuse, not just
    resume/graph resume. `review` reaches `runtime.advance()` exactly the
    way `resume` does (via `_apply_decision`); `runs block`/`runs complete`
    load and act on the current brief too.
    """

    @staticmethod
    def _setup_drifted_run(tmp_path) -> tuple[Path, Path, str, str]:
        """The exact F1 repro: start a run, advance it once, pause it, then
        re-run a tampered brief under the same workflow id. Returns
        (db, handoff_dir, run_id, capsule_id) for the *first* run."""
        db = tmp_path / "r.db"
        handoff_dir = tmp_path / "handoffs"
        runner = CliRunner()
        result = runner.invoke(
            app,
            ["run", str(EXAMPLE_BRIEF), "--db", str(db), "--handoff-dir", str(handoff_dir)],
            input="DRAFT_READY\ndraft.md\n\nquit\n\n\n",
        )
        assert result.exit_code == 0, result.stdout
        run_state = RunLedger(db).list_runs()[0]
        run_id, capsule_id = run_state.run_id, run_state.capsule_id

        tampered = _tampered_brief(tmp_path)
        result = runner.invoke(
            app,
            ["run", str(tampered), "--db", str(db), "--handoff-dir", str(handoff_dir)],
            input="quit\n\n\n",
        )
        assert result.exit_code == 0, result.stdout
        return db, handoff_dir, run_id, capsule_id

    def test_review_refuses_and_changes_nothing(self, tmp_path):
        db, handoff_dir, run_id, capsule_id = self._setup_drifted_run(tmp_path)
        ledger = RunLedger(db)
        capsule_before = ledger.load_capsule(capsule_id)
        run_before = ledger.load_run(run_id)

        result = CliRunner().invoke(
            app,
            ["review", capsule_id, "--db", str(db), "--handoff-dir", str(handoff_dir)],
        )
        assert result.exit_code == 1
        assert "brief" in result.stdout and "changed" in result.stdout

        after = RunLedger(db)
        assert after.load_capsule(capsule_id) == capsule_before
        assert after.load_run(run_id) == run_before

    def test_runs_block_refuses_and_changes_nothing(self, tmp_path):
        db, handoff_dir, run_id, capsule_id = self._setup_drifted_run(tmp_path)
        run_before = RunLedger(db).load_run(run_id)

        result = CliRunner().invoke(
            app,
            [
                "runs", "block", run_id,
                "--reason", "testing", "--next-action", "nothing",
                "--db", str(db), "--handoff-dir", str(handoff_dir),
            ],
        )
        assert result.exit_code == 1
        assert "brief" in result.stdout and "changed" in result.stdout
        assert RunLedger(db).load_run(run_id) == run_before

    def test_runs_complete_refuses_and_changes_nothing(self, tmp_path):
        db, handoff_dir, run_id, capsule_id = self._setup_drifted_run(tmp_path)
        run_before = RunLedger(db).load_run(run_id)

        result = CliRunner().invoke(
            app,
            [
                "runs", "complete", run_id,
                "--check", "manual", "--evidence", "none",
                "--db", str(db), "--handoff-dir", str(handoff_dir),
            ],
        )
        assert result.exit_code == 1
        assert "brief" in result.stdout and "changed" in result.stdout
        assert RunLedger(db).load_run(run_id) == run_before


def test_refusal_message_names_the_recovery_path(tmp_path):
    """Gate G re-review finding R2: the refusal message must name the way
    out in plain language, not just refuse. No override command exists —
    accepting a changed brief for one run is an owner decision, recorded
    separately, not a CLI flag.
    """
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

    tampered = _tampered_brief(tmp_path)
    result = runner.invoke(
        app,
        ["run", str(tampered), "--db", str(db), "--handoff-dir", str(handoff_dir)],
        input="quit\n\n\n",
    )
    assert result.exit_code == 0, result.stdout

    result = runner.invoke(
        app, ["resume", run_id, "--db", str(db), "--handoff-dir", str(handoff_dir)]
    )
    assert result.exit_code == 1
    assert "fukasawa run" in result.stdout
    assert "history" in result.stdout.lower()
