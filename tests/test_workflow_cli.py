# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Phase 6 tests — the workflow CLI, the Gate F (first half) evidence.

Three properties here are the ones the phase boundary names, and each has a
class of its own:

* ``TestExitCodes`` — the codes are a contract. A caller must be able to tell
  "you typed it wrong" (1) from "understood, blocked for now" (2) from
  "understood, refused as doctrine" (3). Collapsing them would make the CLI
  unscriptable in exactly the situations that matter.
* ``TestNoTracebacks`` — no stack trace ever crosses the CLI boundary for an
  ordinary operator mistake. A traceback is not an error message.
* ``TestJsonOutput`` — every command's ``--json`` emits one parseable object,
  on the success path *and* on every failure path.

``TestBoundary`` mechanically enforces ADR-007: the CLI never imports the GUI.

The lifecycle tests drive the real commands against a real SQLite ledger in a
tmp_path. Nothing is mocked; if the ledger or the export breaks, these fail.
"""

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.cli import EXIT_BLOCKED, EXIT_INPUT, EXIT_OK, EXIT_REFUSED, app

ROOT = Path(__file__).resolve().parent.parent
PILOT_DIR = ROOT / "examples" / "workflows" / "substack-publication"

runner = CliRunner()


@pytest.fixture()
def draft(tmp_path) -> Path:
    """The pilot's repaired draft, copied so tests never touch the repo copy."""
    target = tmp_path / "repaired.yaml"
    shutil.copy(PILOT_DIR / "repaired-workflow.yaml", target)
    return target


@pytest.fixture()
def db(tmp_path) -> str:
    """A fresh ledger path per test."""
    return str(tmp_path / "test.db")


def run(*args: str):
    """Invoke the CLI, letting exceptions surface so tests can inspect them."""
    return runner.invoke(app, list(args))


def accountable(draft: Path, db: str) -> None:
    """Walk a draft up to ACCOUNTABLE, the precondition for cooperation work."""
    assert run("workflow", "promote", str(draft), "--by", "tester", "--db", db).exit_code == EXIT_OK
    assert run("workflow", "promote", str(draft), "--by", "tester", "--db", db).exit_code == EXIT_OK


def assessed(draft: Path, db: str) -> None:
    """Reach stored assessments."""
    accountable(draft, db)
    assert run(
        "workflow", "assess-cooperation", "substack-publication", "--db", db
    ).exit_code == EXIT_OK


# ------------------------------------------------------ the named properties


class TestExitCodes:
    """0 / 1 / 2 / 3 are a contract a script may branch on.

    These assert **literal integers**, not the imported constants. A test that
    compares the code against the same constant the code returns proves only
    that the module agrees with itself — renumbering EXIT_BLOCKED to 1 would
    keep such a test green while silently breaking every caller. The numbers
    are the contract, so the numbers are what is pinned.
    """

    def test_the_scheme_is_pinned(self):
        assert (EXIT_OK, EXIT_INPUT, EXIT_BLOCKED, EXIT_REFUSED) == (0, 1, 2, 3)

    def test_zero_on_success(self, draft, db):
        result = run("workflow", "findings", str(draft))
        assert result.exit_code == 0

    def test_one_for_a_missing_file(self, tmp_path):
        result = run("workflow", "validate", str(tmp_path / "absent.yaml"))
        assert result.exit_code == 1

    def test_one_for_malformed_yaml(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("this: [is\n  broken\n", encoding="utf-8")
        result = run("workflow", "validate", str(bad))
        assert result.exit_code == 1

    def test_one_for_yaml_that_is_not_a_mapping(self, tmp_path):
        bad = tmp_path / "list.yaml"
        bad.write_text("- just\n- a list\n", encoding="utf-8")
        assert run("workflow", "validate", str(bad)).exit_code == 1

    def test_one_for_a_schema_violation(self, tmp_path):
        bad = tmp_path / "wrong.yaml"
        bad.write_text("workflow_id: 'Not A Slug'\nname: x\n", encoding="utf-8")
        assert run("workflow", "validate", str(bad)).exit_code == 1

    def test_one_for_a_missing_prerequisite(self, db):
        # Assessing a workflow that was never promoted is an operator mistake,
        # not a governance refusal.
        result = run("workflow", "assess-cooperation", "never-promoted", "--db", db)
        assert result.exit_code == 1

    def test_two_when_blocking_findings_remain(self, tmp_path, db):
        skeleton = tmp_path / "new.yaml"
        assert run("workflow", "init", "new-flow", "--out", str(skeleton)).exit_code == EXIT_OK
        result = run("workflow", "validate", str(skeleton), "--db", db)
        assert result.exit_code == 2

    def test_two_when_promotion_is_blocked_by_findings(self, tmp_path, db):
        skeleton = tmp_path / "new.yaml"
        run("workflow", "init", "new-flow", "--out", str(skeleton))
        result = run("workflow", "promote", str(skeleton), "--by", "tester", "--db", db)
        assert result.exit_code == 2

    def test_three_when_an_override_crosses_a_safety_floor(self, draft, db):
        assessed(draft, db)
        result = run(
            "workflow", "assess-cooperation", "substack-publication", "--db", db,
            "--override", "review-and-approve=BOUNDED_AUTONOMOUS_AGENT",
            "--by", "tester", "--why", "trying to skip the gate",
        )
        assert result.exit_code == 3

    def test_three_when_exporting_an_unapproved_workflow(self, draft, db):
        assessed(draft, db)
        run("workflow", "build-cooperative", "substack-publication", "--db", db)
        result = run("workflow", "export-agent-brief", "substack-publication", "--db", db)
        assert result.exit_code == 3

    def test_blocked_and_refused_are_distinguishable(self, tmp_path, draft, db):
        # The whole point of the scheme: a caller must be able to tell "fix the
        # workflow and retry" from "reconsider the request".
        skeleton = tmp_path / "new.yaml"
        run("workflow", "init", "new-flow", "--out", str(skeleton))
        blocked = run("workflow", "validate", str(skeleton))

        assessed(draft, db)
        refused = run(
            "workflow", "assess-cooperation", "substack-publication", "--db", db,
            "--override", "review-and-approve=BOUNDED_AUTONOMOUS_AGENT",
            "--by", "tester", "--why", "no",
        )
        assert blocked.exit_code != refused.exit_code
        assert {blocked.exit_code, refused.exit_code} == {2, 3}


def assert_clean_exit(result) -> None:
    """Assert the command exited deliberately rather than crashing.

    This check is not optional decoration. CliRunner reports ``exit_code == 1``
    for an **unhandled exception** as well as for a deliberate ``typer.Exit(1)``,
    so asserting the code alone cannot distinguish a clean refusal from a
    traceback. Only ``typer.Exit`` (a SystemExit) counts as leaving on purpose.
    """
    assert "Traceback" not in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit), (
        f"exception leaked past the CLI boundary: {result.exception!r}"
    )


class TestNoTracebacks:
    """An ordinary mistake produces a message, never a stack trace."""

    @pytest.mark.parametrize(
        "content",
        [
            "this: [is\n  broken\n",  # malformed YAML
            "- just\n- a list\n",  # valid YAML, wrong shape
            "workflow_id: 'Not A Slug'\nname: x\n",  # schema violation
            "",  # empty file
        ],
        ids=["malformed", "not-a-mapping", "schema-violation", "empty"],
    )
    def test_a_bad_draft_file_never_crashes(self, content, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text(content, encoding="utf-8")
        result = run("workflow", "validate", str(bad))
        assert result.exit_code == 1
        assert_clean_exit(result)

    # `findings` takes no --db, so each case carries its own complete argv
    # rather than having one appended to it.
    @pytest.mark.parametrize(
        "args,needs_db",
        [
            (("workflow", "validate", "definitely-absent.yaml"), True),
            (("workflow", "findings", "definitely-absent.yaml"), False),
            (("workflow", "promote", "definitely-absent.yaml", "--by", "t"), True),
            (("workflow", "assess-cooperation", "never-promoted"), True),
            (("workflow", "build-cooperative", "never-promoted"), True),
            (("workflow", "export-agent-brief", "never-promoted"), True),
        ],
    )
    def test_no_traceback_and_no_leaked_exception(self, args, needs_db, tmp_path):
        argv = list(args) + (["--db", str(tmp_path / "t.db")] if needs_db else [])
        result = run(*argv)
        assert result.exit_code == EXIT_INPUT
        assert_clean_exit(result)

    def test_version_pinned_draft_lookup_does_not_leak_notfounderror(self, draft, db):
        # Regression: ledger.load_workflow_draft(id, version) used to raise
        # sqlite_utils' NotFoundError instead of the KeyError its docstring
        # promises, which reached the CLI as a traceback on the second promote.
        result = run("workflow", "promote", str(draft), "--by", "tester", "--db", db)
        assert result.exit_code == EXIT_OK
        assert_clean_exit(result)

    def test_an_unwritable_output_path_is_a_message(self, tmp_path):
        # A directory where a file should be: OSError, not a traceback.
        blocked = tmp_path / "taken.yaml"
        blocked.mkdir()
        result = run("workflow", "init", "some-flow", "--out", str(blocked), "--force")
        assert result.exit_code == EXIT_INPUT
        assert_clean_exit(result)


class TestJsonOutput:
    """Every command emits one parseable object, success or failure."""

    def test_init_json(self, tmp_path):
        out = tmp_path / "d.yaml"
        result = run("workflow", "init", "demo-flow", "--out", str(out), "--json")
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["workflow_id"] == "demo-flow"
        assert Path(payload["path"]).exists()

    def test_validate_json_carries_findings(self, draft, db):
        result = run("workflow", "validate", str(draft), "--db", db, "--json")
        payload = json.loads(result.output)
        assert payload["promotion_ready"] is True
        assert isinstance(payload["findings"], list)
        assert {"rule_id", "blocking", "message", "remediation"} <= set(payload["findings"][0])

    def test_findings_json(self, draft):
        result = run("workflow", "findings", str(draft), "--json")
        payload = json.loads(result.output)
        assert payload["count"] == len(payload["findings"])

    def test_findings_json_filtered_by_rule(self, draft):
        result = run("workflow", "findings", str(draft), "--rule", "HW-013", "--json")
        payload = json.loads(result.output)
        assert all(f["rule_id"] == "HW-013" for f in payload["findings"])

    def test_promote_json(self, draft, db):
        result = run("workflow", "promote", str(draft), "--by", "tester", "--db", db, "--json")
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["from_maturity"] == "OBSERVED"
        assert payload["to_maturity"] == "MAPPED"

    def test_assess_cooperation_json(self, draft, db):
        accountable(draft, db)
        result = run(
            "workflow", "assess-cooperation", "substack-publication", "--db", db, "--json"
        )
        payload = json.loads(result.output)
        assert len(payload["assessments"]) == 8
        first = payload["assessments"][0]
        assert {"recommended_executor", "effective_executor", "safety_floor"} <= set(first)

    def test_build_cooperative_json_reports_steps_kept_human(self, draft, db):
        assessed(draft, db)
        result = run(
            "workflow", "build-cooperative", "substack-publication", "--db", db,
            "--approve-by", "tester", "--json",
        )
        payload = json.loads(result.output)
        assert payload["approved"] is True
        assert payload["steps_kept_human"]
        # Three agents, not the pilot artifact's two. `assess-cooperation`
        # recomputes from the table, and the table puts request-artwork on a
        # supervised agent — the operator's recorded override is what makes it
        # human in the committed pilot. The gap between these two numbers is
        # exactly the value an override carries.
        assert payload["required_agent_packages"] == [
            "archive-notes-agent",
            "publish-post-agent",
            "request-artwork-agent",
        ]

    def test_export_json(self, draft, db):
        assessed(draft, db)
        run(
            "workflow", "build-cooperative", "substack-publication", "--db", db,
            "--approve-by", "tester",
        )
        result = run("workflow", "export-agent-brief", "substack-publication", "--db", db, "--json")
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["transitions"] == 13
        assert payload["status"] == "approved"
        # 2, 2, 0 — two local-triage agents and one rule task. Never 4 or 5.
        assert [a["depth_level"] for a in payload["agents"]] == [2, 2, 0]
        assert "publish-post-pending-approval" in payload["states"]

    def test_status_json(self, draft, db):
        assessed(draft, db)
        result = run("workflow", "status", "substack-publication", "--db", db, "--json")
        payload = json.loads(result.output)
        stages = {s["stage"]: s["present"] for s in payload["stages"]}
        assert stages["accountable"] is True
        assert stages["assessed"] is True
        assert stages["cooperative"] is False

    def test_json_on_the_input_error_path(self, tmp_path):
        result = run("workflow", "validate", str(tmp_path / "absent.yaml"), "--json")
        payload = json.loads(result.output)
        assert payload["ok"] is False
        assert payload["error"] == "input"

    def test_json_on_the_refusal_path(self, draft, db):
        assessed(draft, db)
        result = run(
            "workflow", "assess-cooperation", "substack-publication", "--db", db, "--json",
            "--override", "review-and-approve=BOUNDED_AUTONOMOUS_AGENT",
            "--by", "tester", "--why", "no",
        )
        payload = json.loads(result.output)
        assert payload["ok"] is False
        assert payload["error"] == "override_refused"
        assert "IRREVERSIBLE" in payload["message"]

    def test_json_on_the_blocked_path(self, tmp_path):
        skeleton = tmp_path / "new.yaml"
        run("workflow", "init", "new-flow", "--out", str(skeleton))
        result = run("workflow", "validate", str(skeleton), "--json")
        payload = json.loads(result.output)
        assert payload["promotion_ready"] is False
        assert payload["unresolved_blocking"]

    def test_json_carries_no_rich_markup(self, draft, db):
        # Rich markup in a JSON string would reach the caller as literal
        # "[red]" text. The error paths are the easiest place to leak it.
        result = run("workflow", "assess-cooperation", "nope", "--db", db, "--json")
        assert "[red]" not in result.output
        assert "[/" not in result.output
        json.loads(result.output)


class TestBoundary:
    """ADR-007, enforced mechanically rather than by review.

    The directive words this as "src/cli.py never imports from src/gui/", but
    read literally that is unpassable and always was: `fukasawa gui` exists to
    launch the desktop app, so it necessarily imports it. What ADR-007 §5
    actually requires is that **the desktop stays optional forever** — the
    runtime must be fully operable from the CLI with no display and without
    customtkinter installed. That is the property tested here.

    The single `src.gui` reference is function-local inside the `gui` launcher,
    with an ImportError fallback. That import is the mechanism implementing
    ADR-007 §5, not a violation of it.
    """

    def test_importing_the_cli_does_not_import_the_gui(self):
        import subprocess
        import sys

        # A subprocess, because an earlier test in this session may already
        # have imported src.gui and poisoned sys.modules.
        probe = (
            "import sys; import src.cli; "
            "print(any(m.startswith('src.gui') for m in sys.modules))"
        )
        out = subprocess.run(
            [sys.executable, "-c", probe], cwd=ROOT, capture_output=True, text=True
        )
        assert out.stdout.strip() == "False", out.stderr

    def test_the_only_gui_reference_is_the_launcher(self):
        source = (ROOT / "src" / "cli.py").read_text(encoding="utf-8")
        gui_lines = [ln for ln in source.splitlines() if "src.gui" in ln]
        assert len(gui_lines) == 1
        # Function-local, so it cannot execute at import time.
        assert gui_lines[0].startswith("        from src.gui.app import main")

    def test_no_workflow_command_touches_the_gui(self):
        source = (ROOT / "src" / "cli.py").read_text(encoding="utf-8")
        marker = "# ===================================================== human & cooperative"
        workflow_section = source[source.index(marker) :]
        # Match the import forms, not the bare substring — "distinguish"
        # contains "gui" and a naive check fails on prose.
        assert "src.gui" not in workflow_section
        assert "from src import gui" not in workflow_section
        assert "import gui" not in workflow_section

    def test_the_workflow_subapp_holds_no_classification_logic(self):
        # Executor classification lives in src/governance/cooperation.py. The
        # CLI may call it; it must not reimplement a decision table.
        source = (ROOT / "src" / "cli.py").read_text(encoding="utf-8")
        assert "_base_recommendation" not in source
        assert "_FLOOR_CEILINGS" not in source


# --------------------------------------------------------------- the lifecycle


class TestLifecycle:
    def test_init_produces_a_draft_that_loads(self, tmp_path):
        out = tmp_path / "d.yaml"
        assert run("workflow", "init", "demo-flow", "--out", str(out)).exit_code == EXIT_OK
        # The skeleton must be loadable, or capture cannot start. It is
        # deliberately incomplete, so validate blocks — but it parses.
        assert run("workflow", "findings", str(out)).exit_code == EXIT_OK

    def test_init_refuses_a_bad_slug(self, tmp_path):
        result = run("workflow", "init", "Not A Slug", "--out", str(tmp_path / "d.yaml"))
        assert result.exit_code == EXIT_INPUT

    def test_init_refuses_to_clobber_without_force(self, tmp_path):
        out = tmp_path / "d.yaml"
        run("workflow", "init", "demo-flow", "--out", str(out))
        assert run("workflow", "init", "demo-flow", "--out", str(out)).exit_code == EXIT_INPUT
        assert run(
            "workflow", "init", "demo-flow", "--out", str(out), "--force"
        ).exit_code == EXIT_OK

    def test_validate_save_stores_a_draft_with_findings(self, tmp_path, db):
        # Blocking findings must never prevent saving. A workflow is allowed to
        # be a mess while you are writing down what it is.
        skeleton = tmp_path / "new.yaml"
        run("workflow", "init", "new-flow", "--out", str(skeleton))
        result = run("workflow", "validate", str(skeleton), "--db", db, "--save")
        assert result.exit_code == EXIT_BLOCKED

        from src.runtime.ledger import RunLedger

        assert RunLedger(db).load_workflow_draft("new-flow").workflow_id == "new-flow"

    def test_findings_never_gates(self, tmp_path):
        skeleton = tmp_path / "new.yaml"
        run("workflow", "init", "new-flow", "--out", str(skeleton))
        # Same workflow that makes `validate` exit 2 leaves `findings` at 0.
        assert run("workflow", "findings", str(skeleton)).exit_code == EXIT_OK

    def test_promotion_advances_rather_than_repeating(self, draft, db):
        # Regression: the CLI read maturity from the file, which promotion never
        # rewrites, so every run repeated OBSERVED -> MAPPED forever.
        first = run("workflow", "promote", str(draft), "--by", "t", "--db", db, "--json")
        second = run("workflow", "promote", str(draft), "--by", "t", "--db", db, "--json")
        assert json.loads(first.output)["to_maturity"] == "MAPPED"
        assert json.loads(second.output)["to_maturity"] == "ACCOUNTABLE"

    def test_file_edits_are_not_ignored_when_maturity_is_lifted(self, draft, db):
        # Content comes from the file even after the ledger records progress,
        # so an operator's edit is never silently discarded.
        run("workflow", "promote", str(draft), "--by", "t", "--db", db)
        text = draft.read_text(encoding="utf-8").replace(
            "name: ConcordiaPax Substack Article Production", "name: Renamed Pilot"
        )
        draft.write_text(text, encoding="utf-8")
        run("workflow", "promote", str(draft), "--by", "t", "--db", db)

        from src.runtime.ledger import RunLedger

        assert RunLedger(db).load_accountable_workflow("substack-publication").name == "Renamed Pilot"

    def test_assessment_survives_a_separate_invocation(self, draft, db):
        # The gap this phase closed: assessments used to vanish when the
        # process exited, so no second command could read them.
        assessed(draft, db)
        result = run("workflow", "build-cooperative", "substack-publication", "--db", db, "--json")
        assert json.loads(result.output)["ok"] is True

    def test_an_override_survives_to_the_export(self, draft, db):
        assessed(draft, db)
        run(
            "workflow", "assess-cooperation", "substack-publication", "--db", db,
            "--override", "archive-notes=HUMAN_ONLY",
            "--by", "tester", "--why", "doing this by hand for now",
        )
        run(
            "workflow", "build-cooperative", "substack-publication", "--db", db,
            "--approve-by", "tester",
        )
        result = run("workflow", "export-agent-brief", "substack-publication", "--db", db, "--json")
        payload = json.loads(result.output)
        # archive-notes was DETERMINISTIC_AUTOMATION by the table; the override
        # made it human, so its agent must not be declared. The two agents the
        # table chose freely are untouched.
        names = [a["agent_name"] for a in payload["agents"]]
        assert "archive-notes-agent" not in names
        assert sorted(names) == ["publish-post-agent", "request-artwork-agent"]
        assert "archive-notes" in payload["steps_kept_human"]

    def test_reassessing_carries_a_recorded_override_forward(self, draft, db):
        # The footgun this guards: the ledger keeps every override row, but
        # reads take the newest per step. A fresh un-overridden assessment
        # would become newest, so the human's decision would stop governing
        # while still sitting visibly in the history.
        assessed(draft, db)
        run(
            "workflow", "assess-cooperation", "substack-publication", "--db", db,
            "--override", "archive-notes=HUMAN_ONLY",
            "--by", "tester", "--why", "doing this by hand for now",
        )
        # Re-assess with no --override at all.
        result = run(
            "workflow", "assess-cooperation", "substack-publication", "--db", db, "--json"
        )
        archive = next(
            a for a in json.loads(result.output)["assessments"] if a["step_id"] == "archive-notes"
        )
        assert archive["overridden"] is True
        assert archive["effective_executor"] == "HUMAN_ONLY"
        # The recommendation is still recomputed and still visible underneath.
        assert archive["recommended_executor"] == "DETERMINISTIC_AUTOMATION"

    def test_a_new_override_replaces_the_stored_one(self, draft, db):
        assessed(draft, db)
        run(
            "workflow", "assess-cooperation", "substack-publication", "--db", db,
            "--override", "archive-notes=HUMAN_ONLY", "--by", "t", "--why", "first",
        )
        result = run(
            "workflow", "assess-cooperation", "substack-publication", "--db", db, "--json",
            "--override", "archive-notes=HUMAN_LED_AI_ASSISTED",
            "--by", "t", "--why", "second, AI helps now",
        )
        archive = next(
            a for a in json.loads(result.output)["assessments"] if a["step_id"] == "archive-notes"
        )
        assert archive["effective_executor"] == "HUMAN_LED_AI_ASSISTED"

    def test_a_carried_override_reaches_the_export(self, draft, db):
        assessed(draft, db)
        run(
            "workflow", "assess-cooperation", "substack-publication", "--db", db,
            "--override", "archive-notes=HUMAN_ONLY", "--by", "t", "--why", "by hand",
        )
        run("workflow", "assess-cooperation", "substack-publication", "--db", db)
        run(
            "workflow", "build-cooperative", "substack-publication", "--db", db,
            "--approve-by", "t",
        )
        result = run("workflow", "export-agent-brief", "substack-publication", "--db", db, "--json")
        names = [a["agent_name"] for a in json.loads(result.output)["agents"]]
        assert "archive-notes-agent" not in names

    def test_override_requires_actor_and_reason(self, draft, db):
        assessed(draft, db)
        result = run(
            "workflow", "assess-cooperation", "substack-publication", "--db", db,
            "--override", "archive-notes=HUMAN_ONLY",
        )
        assert result.exit_code == EXIT_INPUT

    def test_override_rejects_an_unknown_step(self, draft, db):
        assessed(draft, db)
        result = run(
            "workflow", "assess-cooperation", "substack-publication", "--db", db,
            "--override", "no-such-step=HUMAN_ONLY", "--by", "t", "--why", "x",
        )
        assert result.exit_code == EXIT_INPUT

    def test_override_rejects_an_unknown_executor_class(self, draft, db):
        assessed(draft, db)
        result = run(
            "workflow", "assess-cooperation", "substack-publication", "--db", db,
            "--override", "archive-notes=MAGIC_ROBOT", "--by", "t", "--why", "x",
        )
        assert result.exit_code == EXIT_INPUT

    def test_export_writes_a_brief_the_runtime_can_load(self, draft, db, tmp_path):
        assessed(draft, db)
        run(
            "workflow", "build-cooperative", "substack-publication", "--db", db,
            "--approve-by", "tester",
        )
        out = tmp_path / "brief.yaml"
        assert run(
            "workflow", "export-agent-brief", "substack-publication",
            "--db", db, "--out", str(out),
        ).exit_code == EXIT_OK

        from src.runtime.state_machine import WorkflowRuntime

        brief = WorkflowRuntime.load_brief(out)
        assert brief.id == "substack-publication"
        assert "publish-post-pending-approval" in brief.states

    def test_export_generates_agent_packages(self, draft, db, tmp_path):
        assessed(draft, db)
        run(
            "workflow", "build-cooperative", "substack-publication", "--db", db,
            "--approve-by", "tester",
        )
        paths = tmp_path / "paths.yaml"
        paths.write_text(
            "context: c/\ntasks_ready: r/\ntasks_blocked: b/\noutputs: o/\n"
            "logs: l/\nagent_config: a/\narchive: z/\n",
            encoding="utf-8",
        )
        result = run(
            "workflow", "export-agent-brief", "substack-publication", "--db", db,
            "--packages", str(tmp_path / "pkgs"), "--paths-file", str(paths), "--json",
        )
        assert sorted(json.loads(result.output)["packages_built"]) == [
            "archive-notes-agent",
            "publish-post-agent",
            "request-artwork-agent",
        ]

    def test_status_on_an_unknown_workflow_never_fails(self, db):
        # The command you run when you have lost track must not punish you for
        # not knowing what exists.
        result = run("workflow", "status", "never-heard-of-it", "--db", db)
        assert result.exit_code == EXIT_OK

    def test_status_tracks_progress_through_the_lifecycle(self, draft, db):
        def stages():
            out = run("workflow", "status", "substack-publication", "--db", db, "--json").output
            return {s["stage"]: s["present"] for s in json.loads(out)["stages"]}

        assert stages()["accountable"] is False
        accountable(draft, db)
        assert stages()["accountable"] is True
        assert stages()["assessed"] is False
        run("workflow", "assess-cooperation", "substack-publication", "--db", db)
        assert stages()["assessed"] is True
        assert stages()["exported"] is False
        run(
            "workflow", "build-cooperative", "substack-publication", "--db", db,
            "--approve-by", "tester",
        )
        run("workflow", "export-agent-brief", "substack-publication", "--db", db)
        assert stages()["exported"] is True


class TestRiskAcceptance:
    """Accepting an advisory finding records a decision and reaches the artifact.

    The bug this closes was two-sided: there was no way to record an acceptance
    from the CLI, and `promote` would have discarded one anyway. Validation is
    stateless, so a fresh report has no memory of what a human accepted — and
    `AccountableWorkflow.accepted_risks` is built from that report.
    """

    ADVISORY = "HW-013:unwritten_rules/Never publish two long articles in the s"

    def test_an_advisory_finding_can_be_accepted(self, draft, db):
        result = run(
            "workflow", "accept-risk", str(draft), "--db", db,
            "--finding", self.ADVISORY, "--by", "tester", "--why", "judgement call",
        )
        assert result.exit_code == 0

    def test_an_acceptance_survives_revalidation(self, draft, db):
        run(
            "workflow", "accept-risk", str(draft), "--db", db,
            "--finding", self.ADVISORY, "--by", "tester", "--why", "judgement call",
        )
        result = run("workflow", "validate", str(draft), "--db", db, "--json")
        accepted = [f["finding_id"] for f in json.loads(result.output)["findings"] if f["accepted"]]
        assert accepted == [self.ADVISORY]

    def test_an_acceptance_reaches_the_promoted_artifact(self, draft, db):
        # This is the half that was silently broken: the acceptance existed in
        # the ledger but never appeared on the artifact that cites it.
        run(
            "workflow", "accept-risk", str(draft), "--db", db,
            "--finding", self.ADVISORY, "--by", "tester", "--why", "judgement call",
        )
        accountable(draft, db)

        from src.runtime.ledger import RunLedger

        artifact = RunLedger(db).load_accountable_workflow("substack-publication")
        assert [a.rule.rule_id for a in artifact.accepted_risks] == ["HW-013"]
        assert artifact.accepted_risks[0].accepted_by == "tester"

    def test_promotion_without_an_acceptance_carries_none(self, draft, db):
        # The negative half of the pair: re-attachment must not invent rows.
        accountable(draft, db)

        from src.runtime.ledger import RunLedger

        artifact = RunLedger(db).load_accountable_workflow("substack-publication")
        assert artifact.accepted_risks == []

    def test_a_blocking_finding_cannot_be_accepted(self, tmp_path, db):
        skeleton = tmp_path / "new.yaml"
        run("workflow", "init", "new-flow", "--out", str(skeleton))
        result = run(
            "workflow", "accept-risk", str(skeleton), "--db", db,
            "--finding", "HW-001:trigger", "--by", "t", "--why", "we do not need one",
        )
        # Doctrine refusing, not a typo: waiving a blocking finding would turn
        # the promotion gate into a formality.
        assert result.exit_code == 3

    def test_an_unknown_finding_id_is_an_input_error(self, draft, db):
        result = run(
            "workflow", "accept-risk", str(draft), "--db", db,
            "--finding", "HW-999:nope", "--by", "t", "--why", "x",
        )
        assert result.exit_code == 1
        assert_clean_exit(result)
        # The message lists what is available, so the operator can correct it.
        assert "HW-013" in result.output

    def test_a_stored_acceptance_never_reattaches_onto_a_blocking_finding(
        self, tmp_path, db
    ):
        # The scenario this guards is a rule's *policy* changing between
        # versions: HW-013 and HW-014 are documented as the heuristic pair, and
        # an acceptance recorded while a rule was advisory must not silently
        # waive it once it is blocking. `accept_risk` cannot create such a row,
        # so the test writes it straight to the ledger — which is exactly the
        # shape an older release would have left behind.
        from src.governance.workflow_promotion import reattach_acceptances
        from src.governance.workflow_rules import validate_workflow
        from src.runtime.ledger import RunLedger
        from src.schemas.findings import RiskAcceptance
        from src.schemas.human_workflow import HumanWorkflowDraft

        import yaml as yamllib

        skeleton = tmp_path / "new.yaml"
        run("workflow", "init", "new-flow", "--out", str(skeleton))
        drafted = HumanWorkflowDraft.model_validate(
            yamllib.safe_load(skeleton.read_text(encoding="utf-8"))
        )
        report = validate_workflow(drafted)
        blocking = next(f for f in report.findings if f.blocking)

        ledger = RunLedger(db)
        ledger.save_risk_acceptance(
            "new-flow",
            RiskAcceptance(
                finding_id=blocking.finding_id,
                rule=blocking.rule,
                accepted_by="someone-long-ago",
                rationale="this was advisory when I accepted it",
            ),
        )

        fresh = validate_workflow(drafted)
        reattached = reattach_acceptances(fresh, ledger)
        assert reattached == []
        assert all(f.acceptance is None for f in fresh.findings if f.blocking)
        # And the gate stays shut.
        assert fresh.promotion_ready is False

    def test_acceptance_requires_actor_and_reason(self, draft, db):
        result = run(
            "workflow", "accept-risk", str(draft), "--db", db, "--finding", self.ADVISORY
        )
        # Typer's own missing-option handling; must not be a traceback.
        assert result.exit_code != 0
        assert "Traceback" not in result.output


class TestSharedReconciliation:
    """The file/ledger rule lives in governance, not in the CLI.

    Phase 7's services.py must reach the same behaviour, and the only way that
    happens reliably is by calling the same function. A private copy in cli.py
    is how the promote-repeats bug comes back in the desktop.
    """

    def test_the_helpers_are_importable_from_governance(self):
        from src.governance.workflow_promotion import (  # noqa: F401
            at_recorded_maturity,
            reattach_acceptances,
        )

    def test_the_cli_does_not_keep_a_private_copy(self):
        source = (ROOT / "src" / "cli.py").read_text(encoding="utf-8")
        assert "def _at_recorded_maturity" not in source
        assert "def _reattach_acceptances" not in source

    def test_at_recorded_maturity_prefers_file_content(self, draft, db):
        from src.governance.workflow_promotion import at_recorded_maturity
        from src.runtime.ledger import RunLedger
        from src.schemas.human_workflow import HumanWorkflowDraft, WorkflowMaturity

        import yaml as yamllib

        ledger = RunLedger(db)
        run("workflow", "promote", str(draft), "--by", "t", "--db", db)

        on_disk = HumanWorkflowDraft.model_validate(
            yamllib.safe_load(draft.read_text(encoding="utf-8"))
        )
        assert on_disk.maturity is WorkflowMaturity.OBSERVED

        lifted, note = at_recorded_maturity(on_disk, ledger)
        assert lifted.maturity is WorkflowMaturity.MAPPED
        assert lifted.name == on_disk.name  # content untouched
        assert "MAPPED" in note

    def test_at_recorded_maturity_never_lowers_maturity(self, draft, db):
        from src.governance.workflow_promotion import at_recorded_maturity
        from src.runtime.ledger import RunLedger
        from src.schemas.human_workflow import WorkflowMaturity

        ledger = RunLedger(db)
        accountable(draft, db)
        stored = ledger.load_workflow_draft("substack-publication")
        # Hand it something already ahead of the ledger; it must not regress.
        ahead = stored.model_copy(deep=True)
        ahead.maturity = WorkflowMaturity.RUNTIME_READY
        result, note = at_recorded_maturity(ahead, ledger)
        assert result.maturity is WorkflowMaturity.RUNTIME_READY
        assert note == ""


class TestExistingCommandsUntouched:
    """The phase boundary forbids editing the ten sub-apps that were here."""

    @pytest.mark.parametrize(
        "name",
        [
            "nonconformance", "validate", "runs", "package", "eval",
            "maturity", "graph", "trust", "model", "bundle", "workflow",
        ],
    )
    def test_subapp_is_registered(self, name):
        result = runner.invoke(app, [name, "--help"])
        assert result.exit_code == EXIT_OK

    def test_top_level_status_still_takes_a_workflow_id(self, db):
        # `fukasawa status` and `fukasawa workflow status` are different
        # commands; adding the sub-app must not have shadowed the original.
        result = runner.invoke(app, ["status", "unknown-workflow", "--db", db])
        assert result.exit_code == EXIT_INPUT
        assert "Unknown workflow" in result.output
