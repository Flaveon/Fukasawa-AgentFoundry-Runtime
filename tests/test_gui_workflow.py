# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Phase 7 tests — the desktop lifecycle, the Gate F evidence.

Four layers, and the ordering is deliberate:

* ``TestImportLaw`` — the R3 guard, and the only one that matters most.
  It parses the source rather than importing it, so it runs **with or without a
  display**. Risk R3 is "the desktop grows a second validator"; a guard that
  skips on a developer's plain `pytest` is a guard that is not there. This is
  ADR-007 §2 made executable.
* ``TestServices`` — the lifecycle services, Tk-free, always run.
* ``TestParity`` — the desktop and the CLI reach the same answers, because
  they call the same functions. Gate F asks for parity; this is what proves it.
* ``TestView`` — behaviour of the widgets, display-gated. CI runs
  `xvfb-run -a pytest`, so these execute there; locally they skip.

The services are exercised against the real pilot and a real SQLite ledger in
tmp_path. Nothing is mocked.
"""

import ast
import shutil
from pathlib import Path

import pytest

from src.gui import services

ROOT = Path(__file__).resolve().parent.parent
PILOT_DIR = ROOT / "examples" / "workflows" / "substack-publication"
GUI_DIR = ROOT / "src" / "gui"


@pytest.fixture()
def draft(tmp_path) -> Path:
    """The pilot's repaired draft, copied so tests never touch the repo copy."""
    target = tmp_path / "repaired.yaml"
    shutil.copy(PILOT_DIR / "repaired-workflow.yaml", target)
    return target


@pytest.fixture()
def db(tmp_path) -> str:
    """A fresh ledger per test."""
    return str(tmp_path / "gui.db")


def accountable(draft: Path, db: str) -> None:
    """Walk the pilot up to ACCOUNTABLE."""
    assert services.promote_draft(draft, "tester", db).ok
    assert services.promote_draft(draft, "tester", db).ok


def assessed(draft: Path, db: str) -> None:
    """Reach stored assessments."""
    accountable(draft, db)
    assert services.assess_cooperation("substack-publication", db).ok


# --------------------------------------------------------------- the R3 guard


def _imported_modules(path: Path) -> set[str]:
    """Fully-qualified paths a file imports, from its AST.

    `from src.gui import services` resolves to ``src.gui.services``, not
    ``src.gui`` — otherwise a legal import of the service package reads as an
    import of the whole GUI package and the law cannot tell them apart.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


class TestImportLaw:
    """ADR-007 §2, enforced mechanically. Runs without a display."""

    #: What a view is allowed to reach for. Anything else is business logic
    #: creeping into the UI, which is exactly risk R3. `workflow_views` is
    #: listed because `app.py` mounts the tab — one view composing another is
    #: still a view.
    VIEW_ALLOWED_PREFIXES = (
        "src.gui.services",
        "src.gui.workflow_views",
        "customtkinter",
        "tkinter",
    )

    @pytest.mark.parametrize("name", ["app.py", "workflow_views.py"])
    def test_views_import_only_services_stdlib_and_ctk(self, name):
        import sys

        offenders = []
        for module in _imported_modules(GUI_DIR / name):
            if module.startswith(self.VIEW_ALLOWED_PREFIXES):
                continue
            root = module.split(".")[0]
            if root in sys.stdlib_module_names:
                continue
            offenders.append(module)
        assert not offenders, (
            f"{name} imports {offenders}; a view may only reach "
            f"src.gui.services, stdlib, and customtkinter (ADR-007 §2)"
        )

    def test_views_never_import_the_runtime_directly(self):
        # The specific failure R3 describes: a view calling governance itself.
        for name in ("app.py", "workflow_views.py"):
            modules = _imported_modules(GUI_DIR / name)
            for forbidden in (
                "src.governance",
                "src.runtime",
                "src.foundry",
                "src.schemas",
                "src.kernel",
            ):
                assert not any(m.startswith(forbidden) for m in modules), (
                    f"{name} imports {forbidden} directly — it must go through services"
                )

    @pytest.mark.parametrize(
        "name", ["services/__init__.py", "services/brief.py", "services/workflow.py"]
    )
    def test_services_never_import_widgets(self, name):
        modules = _imported_modules(GUI_DIR / name)
        for widget_lib in ("customtkinter", "tkinter"):
            assert not any(m.split(".")[0] == widget_lib for m in modules), (
                f"{name} imports {widget_lib}; services must stay Tk-free so the "
                f"runtime is usable with no display (ADR-007 §1)"
            )

    def test_services_do_not_print(self):
        # A service that prints has decided how to present something, which is
        # the view's job — and is invisible in a GUI anyway.
        for name in ("services/__init__.py", "services/brief.py", "services/workflow.py"):
            tree = ast.parse((GUI_DIR / name).read_text(encoding="utf-8"))
            calls = [
                n.func.id
                for n in ast.walk(tree)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            ]
            assert "print" not in calls, f"{name} prints; services return data"

    def test_no_classification_or_rule_logic_in_the_gui(self):
        # Directive §6.3: no rule, promotion decision, or executor
        # classification anywhere under src/gui/.
        for path in GUI_DIR.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            for marker in ("_base_recommendation", "_FLOOR_CEILINGS", "_SUPERVISION"):
                assert marker not in source, f"{path.name} contains {marker}"

    def test_the_package_split_kept_the_import_surface(self):
        # ADR-007's consequence note: services may become a package, but views'
        # import surface must not change.
        from src.gui.services import build_workflow, validate_brief_file  # noqa: F401

        assert services.validate_brief_file is not None
        assert services.build_workflow is not None


# ------------------------------------------------------------------ services


class TestServices:
    def test_create_writes_a_loadable_skeleton(self, tmp_path):
        out = tmp_path / "new.yaml"
        assert services.create_draft("demo-flow", out).ok
        assert out.exists()
        # Deliberately incomplete, but it must parse — capture comes first.
        result = services.validate_draft(out, str(tmp_path / "d.db"))
        assert result.ok
        assert not result.promotion_ready

    def test_create_refuses_a_bad_slug(self, tmp_path):
        result = services.create_draft("Not A Slug", tmp_path / "x.yaml")
        assert not result.ok
        assert "not a valid workflow id" in result.refusal

    def test_create_refuses_to_clobber(self, tmp_path):
        out = tmp_path / "new.yaml"
        services.create_draft("demo-flow", out)
        assert not services.create_draft("demo-flow", out).ok
        assert services.create_draft("demo-flow", out, overwrite=True).ok

    def test_import_and_reload_round_trip(self, draft, db):
        assert services.import_draft(draft, db).ok
        reloaded = services.reload_draft("substack-publication", db)
        assert reloaded.ok
        assert "8 step(s)" in reloaded.summary

    def test_import_saves_a_draft_with_blocking_findings(self, tmp_path):
        # Saving must never depend on the draft being complete.
        skeleton = tmp_path / "new.yaml"
        services.create_draft("new-flow", skeleton)
        db = str(tmp_path / "d.db")
        assert services.import_draft(skeleton, db).ok
        assert services.reload_draft("new-flow", db).ok

    def test_reload_of_an_unknown_workflow_is_a_refusal_not_a_crash(self, db):
        result = services.reload_draft("never-heard-of-it", db)
        assert not result.ok
        assert result.refusal

    def test_bad_files_come_back_as_messages(self, tmp_path, db):
        missing = services.validate_draft(tmp_path / "absent.yaml", db)
        assert not missing.ok and "No such file" in missing.refusal

        broken = tmp_path / "bad.yaml"
        broken.write_text("this: [is\n  broken\n", encoding="utf-8")
        assert "Not valid YAML" in services.validate_draft(broken, db).refusal

        wrong = tmp_path / "wrong.yaml"
        wrong.write_text("- a\n- list\n", encoding="utf-8")
        assert not services.validate_draft(wrong, db).ok

    def test_list_workflows(self, draft, db):
        assert services.list_workflows(db).workflows == []
        services.import_draft(draft, db)
        listing = services.list_workflows(db)
        assert [w.workflow_id for w in listing.workflows] == ["substack-publication"]

    def test_validate_reports_findings_without_failing(self, draft, db):
        result = services.validate_draft(draft, db)
        assert result.ok
        assert result.promotion_ready
        assert result.findings
        assert all(f.rule_id.startswith("HW-") for f in result.findings)

    def test_accept_records_and_survives_revalidation(self, draft, db):
        report = services.validate_draft(draft, db)
        advisory = next(f for f in report.findings if not f.blocking)
        assert services.accept_finding(draft, advisory.finding_id, "tester", "known", db).ok
        again = services.validate_draft(draft, db)
        assert [f.finding_id for f in again.findings if f.accepted] == [advisory.finding_id]

    def test_accept_requires_actor_and_reason(self, draft, db):
        report = services.validate_draft(draft, db)
        advisory = next(f for f in report.findings if not f.blocking)
        assert not services.accept_finding(draft, advisory.finding_id, "", "why", db).ok
        assert not services.accept_finding(draft, advisory.finding_id, "who", "", db).ok

    def test_accept_refuses_a_blocking_finding(self, tmp_path):
        skeleton = tmp_path / "new.yaml"
        services.create_draft("new-flow", skeleton)
        db = str(tmp_path / "d.db")
        report = services.validate_draft(skeleton, db)
        blocking = next(f for f in report.findings if f.blocking)
        result = services.accept_finding(skeleton, blocking.finding_id, "t", "no", db)
        assert not result.ok
        assert "blocking" in result.refusal

    def test_promotion_advances_rather_than_repeating(self, draft, db):
        # at_recorded_maturity, reached through the service layer.
        first = services.promote_draft(draft, "tester", db)
        second = services.promote_draft(draft, "tester", db)
        assert first.to_maturity == "MAPPED"
        assert second.to_maturity == "ACCOUNTABLE"

    def test_promotion_requires_an_actor(self, draft, db):
        assert not services.promote_draft(draft, "  ", db).ok

    def test_promotion_blocked_by_findings_reports_them(self, tmp_path):
        skeleton = tmp_path / "new.yaml"
        services.create_draft("new-flow", skeleton)
        result = services.promote_draft(skeleton, "tester", str(tmp_path / "d.db"))
        assert not result.ok
        assert result.blocking
        assert all(f.blocking for f in result.blocking)

    def test_assess_requires_an_accountable_workflow(self, db):
        result = services.assess_cooperation("never-promoted", db)
        assert not result.ok
        assert "ACCOUNTABLE" in result.refusal

    def test_assessment_matches_the_published_table(self, draft, db):
        accountable(draft, db)
        result = services.assess_cooperation("substack-publication", db)
        by_step = {a.step_id: a.effective_executor for a in result.assessments}
        assert by_step["publish-post"] == "AGENT_PREPARED_HUMAN_APPROVED"
        assert by_step["archive-notes"] == "DETERMINISTIC_AUTOMATION"
        assert by_step["review-and-approve"] == "HUMAN_ONLY"

    def test_override_toward_human_is_allowed(self, draft, db):
        assessed(draft, db)
        result = services.override_executor(
            "substack-publication", "archive-notes", "HUMAN_ONLY",
            "tester", "by hand for now", db,
        )
        assert result.ok
        by_step = {a.step_id: a for a in result.assessments}
        assert by_step["archive-notes"].effective_executor == "HUMAN_ONLY"
        assert by_step["archive-notes"].overridden

    def test_override_across_a_safety_floor_is_refused(self, draft, db):
        assessed(draft, db)
        result = services.override_executor(
            "substack-publication", "review-and-approve", "BOUNDED_AUTONOMOUS_AGENT",
            "tester", "skip the gate", db,
        )
        assert not result.ok
        assert "IRREVERSIBLE" in result.refusal

    def test_override_requires_actor_and_reason(self, draft, db):
        assessed(draft, db)
        assert not services.override_executor(
            "substack-publication", "archive-notes", "HUMAN_ONLY", "", "why", db
        ).ok
        assert not services.override_executor(
            "substack-publication", "archive-notes", "HUMAN_ONLY", "who", "", db
        ).ok

    def test_override_rejects_unknown_step_and_class(self, draft, db):
        assessed(draft, db)
        assert not services.override_executor(
            "substack-publication", "no-such-step", "HUMAN_ONLY", "t", "x", db
        ).ok
        assert not services.override_executor(
            "substack-publication", "archive-notes", "MAGIC_ROBOT", "t", "x", db
        ).ok

    def test_reassessment_carries_a_recorded_override(self, draft, db):
        assessed(draft, db)
        services.override_executor(
            "substack-publication", "archive-notes", "HUMAN_ONLY", "t", "by hand", db
        )
        again = services.assess_cooperation("substack-publication", db)
        assert "archive-notes" in again.carried_overrides
        by_step = {a.step_id: a for a in again.assessments}
        assert by_step["archive-notes"].effective_executor == "HUMAN_ONLY"
        assert by_step["archive-notes"].recommended_executor == "DETERMINISTIC_AUTOMATION"

    def test_build_requires_assessments(self, draft, db):
        accountable(draft, db)
        result = services.build_cooperative("substack-publication", db=db)
        assert not result.ok
        assert "assessments" in result.refusal

    def test_build_reports_steps_kept_human(self, draft, db):
        assessed(draft, db)
        result = services.build_cooperative("substack-publication", db=db)
        assert result.ok
        assert result.steps_kept_human
        assert not result.approved

    def test_export_refuses_an_unapproved_workflow(self, draft, db):
        assessed(draft, db)
        services.build_cooperative("substack-publication", db=db)
        result = services.export_brief("substack-publication", db=db)
        assert not result.ok
        assert "approved" in result.refusal

    def test_export_splits_the_gated_step(self, draft, db):
        assessed(draft, db)
        services.build_cooperative("substack-publication", "tester", db)
        result = services.export_brief("substack-publication", db=db)
        assert result.ok
        assert "publish-post-pending-approval" in result.states
        assert result.status == "approved"

    def test_export_writes_a_file_when_asked(self, draft, db, tmp_path):
        assessed(draft, db)
        services.build_cooperative("substack-publication", "tester", db)
        out = tmp_path / "brief.yaml"
        result = services.export_brief("substack-publication", out, db)
        assert result.written_path == str(out)

        from src.runtime.state_machine import WorkflowRuntime

        assert WorkflowRuntime.load_brief(out).id == "substack-publication"

    def test_lifecycle_status_never_refuses(self, db):
        result = services.lifecycle_status("never-heard-of-it", db)
        assert result.ok
        assert all(not s.present for s in result.stages)

    def test_lifecycle_status_tracks_progress(self, draft, db):
        def reached():
            return {s.stage: s.present for s in services.lifecycle_status(
                "substack-publication", db
            ).stages}

        assert not reached()["accountable"]
        accountable(draft, db)
        assert reached()["accountable"]
        assert not reached()["assessed"]
        services.assess_cooperation("substack-publication", db)
        assert reached()["assessed"]

    def test_every_stage_is_reported(self, db):
        result = services.lifecycle_status("anything", db)
        assert [s.stage for s in result.stages] == list(services.STAGES)


# -------------------------------------------------------------------- parity


class TestParity:
    """The desktop and the CLI reach the same answers (Gate F).

    Not by comparing implementations — by both calling the same governance
    functions. These tests would catch a future change that gave one surface
    its own copy of a rule.
    """

    def test_assessment_matches_the_cli(self, draft, db, tmp_path):
        from typer.testing import CliRunner

        from src.cli import app

        cli_db = str(tmp_path / "cli.db")
        runner = CliRunner()
        for _ in range(2):
            runner.invoke(app, ["workflow", "promote", str(draft), "--by", "t", "--db", cli_db])
        cli_out = runner.invoke(
            app, ["workflow", "assess-cooperation", "substack-publication", "--db", cli_db, "--json"]
        )
        import json

        cli_rows = {
            a["step_id"]: a["effective_executor"]
            for a in json.loads(cli_out.output)["assessments"]
        }

        accountable(draft, db)
        gui = services.assess_cooperation("substack-publication", db)
        gui_rows = {a.step_id: a.effective_executor for a in gui.assessments}

        assert gui_rows == cli_rows

    def test_export_matches_the_cli(self, draft, db, tmp_path):
        import json

        from typer.testing import CliRunner

        from src.cli import app

        cli_db = str(tmp_path / "cli.db")
        runner = CliRunner()
        for _ in range(2):
            runner.invoke(app, ["workflow", "promote", str(draft), "--by", "t", "--db", cli_db])
        runner.invoke(app, ["workflow", "assess-cooperation", "substack-publication", "--db", cli_db])
        runner.invoke(
            app,
            ["workflow", "build-cooperative", "substack-publication", "--db", cli_db,
             "--approve-by", "t"],
        )
        cli_out = runner.invoke(
            app, ["workflow", "export-agent-brief", "substack-publication", "--db", cli_db, "--json"]
        )
        cli = json.loads(cli_out.output)

        assessed(draft, db)
        services.build_cooperative("substack-publication", "t", db)
        gui = services.export_brief("substack-publication", db=db)

        assert gui.states == cli["states"]
        assert gui.transition_count == cli["transitions"]
        assert [a.agent_name for a in gui.agents] == [a["agent_name"] for a in cli["agents"]]
        assert gui.steps_kept_human == cli["steps_kept_human"]

    def test_both_surfaces_refuse_the_same_override(self, draft, db, tmp_path):
        from typer.testing import CliRunner

        from src.cli import app

        cli_db = str(tmp_path / "cli.db")
        runner = CliRunner()
        for _ in range(2):
            runner.invoke(app, ["workflow", "promote", str(draft), "--by", "t", "--db", cli_db])
        runner.invoke(app, ["workflow", "assess-cooperation", "substack-publication", "--db", cli_db])
        cli_result = runner.invoke(
            app,
            ["workflow", "assess-cooperation", "substack-publication", "--db", cli_db,
             "--override", "review-and-approve=BOUNDED_AUTONOMOUS_AGENT",
             "--by", "t", "--why", "no"],
        )

        assessed(draft, db)
        gui_result = services.override_executor(
            "substack-publication", "review-and-approve", "BOUNDED_AUTONOMOUS_AGENT",
            "t", "no", db,
        )

        assert cli_result.exit_code == 3
        assert not gui_result.ok
        assert "IRREVERSIBLE" in gui_result.refusal


# ---------------------------------------------------------------- the view


def pump(tab, captured: list, timeout: float = 5.0) -> None:
    """Wait for a worker to deliver, draining the queue directly.

    Deliberately does **not** spin ``window.update()``. Hammering ``update()``
    in a tight loop is a test-only pathology — real code runs ``mainloop()`` —
    and under Xvfb it segfaulted inside Tk's event dispatch, because the loop
    processes queued events against action buttons the view had already
    destroyed and rebuilt.

    Draining the queue is also the more honest test: it exercises the actual
    mechanism (worker → queue → ``drain`` → callback) rather than relying on
    the poller's timer to have fired within an arbitrary window. ``drain`` is
    public for exactly this reason.
    """
    import time

    deadline = time.monotonic() + timeout
    while not captured and time.monotonic() < deadline:
        time.sleep(0.01)
        tab.drain()


@pytest.fixture(scope="module")
def _shared_window():
    """One Tk root for this whole module, or skip when there is no display.

    **Module-scoped on purpose.** Tk expects one root per process;
    customtkinter keeps global appearance and scaling trackers that hold
    references to live windows, and creating then destroying a root per test
    made the suite segfault intermittently once this file added ten more view
    tests to the four that already existed. Sharing one window is both the
    stable arrangement and the way the toolkit is designed to be used.

    Tests must therefore leave no state behind that another test would read;
    `app_window` resets the tab between them.
    """
    pytest.importorskip("customtkinter")
    import tkinter

    from src.gui.app import FukasawaApp

    try:
        window = FukasawaApp()
    except tkinter.TclError as exc:
        pytest.skip(f"no display for GUI test: {exc}")
    yield window
    window.destroy()


@pytest.fixture()
def app_window(_shared_window):
    """The shared window, reset to a known state for each test."""
    tab = _shared_window.workflow_tab
    tab.select_stage("draft")
    tab.set_fields(workflow_entry="", draft_entry="", db_entry="")
    tab.results.delete("1.0", "end")
    return _shared_window


class TestView:
    """Widget behaviour. Display-gated; CI runs these under xvfb."""

    def test_the_workflow_tab_is_mounted_first(self, app_window):
        assert hasattr(app_window, "workflow_tab")

    def test_every_stage_has_a_button(self, app_window):
        assert list(app_window.workflow_tab.stage_buttons) == list(services.STAGES)

    def test_selecting_a_stage_changes_the_actions(self, app_window):
        tab = app_window.workflow_tab
        assert tab.selected_stage == "draft"
        tab.select_stage("exported")
        assert tab.selected_stage == "exported"

    def test_the_lifecycle_drives_end_to_end(self, app_window, draft, db):
        tab = app_window.workflow_tab
        tab.set_fields(
            workflow_entry="substack-publication",
            draft_entry=str(draft),
            db_entry=db,
        )
        assert tab.run_import().ok
        assert tab.run_validate().ok
        assert tab.run_promote().to_maturity == "MAPPED"
        assert tab.run_promote().to_maturity == "ACCOUNTABLE"
        assert tab.run_assess().ok
        assert not tab.run_export().ok  # nothing built yet
        assert tab.run_build(approved=True).ok
        assert tab.run_export().ok

    def test_stage_markers_follow_progress(self, app_window, draft, db):
        tab = app_window.workflow_tab
        tab.set_fields(
            workflow_entry="substack-publication", draft_entry=str(draft), db_entry=db
        )
        before = {s.stage: s.present for s in tab.refresh_stages().stages}
        assert not before["accountable"]
        tab.run_promote()
        tab.run_promote()
        after = {s.stage: s.present for s in tab.refresh_stages().stages}
        assert after["accountable"]

    def test_a_refusal_is_rendered_as_a_refusal(self, app_window, draft, db):
        tab = app_window.workflow_tab
        tab.set_fields(
            workflow_entry="substack-publication", draft_entry=str(draft), db_entry=db
        )
        tab.run_promote()
        tab.run_promote()
        tab.run_assess()
        tab.run_build(approved=False)
        tab._show(tab.run_export())
        shown = tab.shown()
        assert "Refused:" in shown
        assert "approved" in shown

    def test_findings_are_rendered_with_remediation(self, app_window, draft, db):
        tab = app_window.workflow_tab
        tab.set_fields(
            workflow_entry="substack-publication", draft_entry=str(draft), db_entry=db
        )
        tab._show(tab.run_validate())
        shown = tab.shown()
        assert "HW-013" in shown
        assert "→" in shown

    def test_kept_human_is_always_stated(self, app_window, draft, db):
        tab = app_window.workflow_tab
        tab.set_fields(
            workflow_entry="substack-publication", draft_entry=str(draft), db_entry=db
        )
        tab.run_promote()
        tab.run_promote()
        tab.run_assess()
        tab._show(tab.run_build(approved=True))
        assert "stay with a person" in tab.shown()

    def test_a_worker_error_surfaces_instead_of_vanishing(self, app_window):
        # An exception on a worker thread otherwise dies with the thread,
        # leaving a window that looks like it did nothing.
        tab = app_window.workflow_tab
        captured = []

        def boom():
            raise RuntimeError("simulated failure")

        tab._in_worker(boom, captured.append)
        pump(tab, captured)
        assert captured, "worker result never arrived"
        assert not captured[0].ok
        assert "simulated failure" in captured[0].refusal

    def test_the_ui_thread_is_not_blocked_while_working(self, app_window, draft, db):
        tab = app_window.workflow_tab
        tab.set_fields(
            workflow_entry="substack-publication", draft_entry=str(draft), db_entry=db
        )
        captured = []
        tab._in_worker(tab.run_import, captured.append)
        # The call returned before the work finished — that is the property.
        # A blocking implementation would have delivered before this line.
        assert not captured
        pump(tab, captured)
        assert captured and captured[0].ok

    def test_the_poller_is_armed_and_rearms(self, app_window):
        # The queue only helps if something drains it. `drain` is called by
        # `_poll`, which must keep re-arming itself.
        tab = app_window.workflow_tab
        assert tab._poll_id is not None
        first = tab._poll_id
        tab._poll()
        assert tab._poll_id is not None
        assert tab._poll_id != first
