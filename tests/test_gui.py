# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""GUI tests.

Two layers, matching the design:

* The service layer (Tk-free) is tested directly and always runs — this is
  the logic the Phase 5 exit criterion cares about.
* The CustomTkinter view is smoke-tested by constructing the window,
  driving its handlers headlessly, and reading the results back. It skips
  cleanly when no display is available (so a plain `pytest` still passes;
  run under xvfb to exercise it).
"""

from pathlib import Path

import pytest
from unittest.mock import patch
from src.gui.services import BuildRefusedError
import yaml

from src.gui.services import build_workflow, validate_brief_file

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_BRIEF = ROOT / "examples" / "q2c-production-handoff.yaml"


@pytest.fixture()
def cpax_workspace(tmp_path) -> Path:
    ws = tmp_path / "ws"
    for d in ("05_tasks/blocked", "11_outputs"):
        (ws / d).mkdir(parents=True)
    (ws / "doctrine.md").write_text("# Doctrine\n")
    return ws


class TestValidateService:
    def test_valid_brief(self):
        result = validate_brief_file(EXAMPLE_BRIEF)
        assert result.ok
        assert result.brief_id == "q2c-production-handoff"
        assert result.approved
        assert result.agent_count == 2
        assert result.review_gates == 2


    def test_directory_path(self, tmp_path):
        result = validate_brief_file(tmp_path)
        assert not result.ok
        assert "No such file" in result.summary

    def test_missing_file(self):
        result = validate_brief_file("/no/such/brief.yaml")
        assert not result.ok
        assert "No such file" in result.summary


    def test_empty_yaml(self, tmp_path):
        empty = tmp_path / "empty.yaml"
        empty.write_text("")
        result = validate_brief_file(empty)
        assert not result.ok
        assert result.problems

    def test_schema_violation_wrong_type(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("id: 123\ntitle: 456\n")
        result = validate_brief_file(bad)
        assert not result.ok
        assert result.problems

    def test_invalid_brief_lists_problems(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("id: 'Bad Id!'\ntitle: x\n")  # missing required fields, bad id
        result = validate_brief_file(bad)
        assert not result.ok
        assert result.problems
        assert any("id" in p for p in result.problems)

    def test_bad_yaml(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("id: [unclosed\n")
        result = validate_brief_file(bad)
        assert not result.ok
        assert "YAML" in result.summary


class TestBuildService:
    def test_build_succeeds_and_self_validates(self, cpax_workspace, tmp_path):
        outcome = build_workflow(EXAMPLE_BRIEF, tmp_path / "out", cpax_workspace)
        assert outcome.ok
        assert len(outcome.packages) == 2
        assert all(p.ok for p in outcome.packages)
        assert Path(outcome.report_path).exists()

    def test_build_refuses_invalid_brief(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("id: x\n")
        outcome = build_workflow(bad, tmp_path / "out")
        assert not outcome.ok
        assert outcome.refusal

    def test_build_refuses_draft_brief(self, tmp_path):
        data = yaml.safe_load(EXAMPLE_BRIEF.read_text())
        data["status"] = "draft"
        draft = tmp_path / "draft.yaml"
        draft.write_text(yaml.safe_dump(data))
        outcome = build_workflow(draft, tmp_path / "out", tmp_path)
        assert not outcome.ok
        assert "approved" in outcome.refusal.lower()



    # Patch target follows the symbol: `generate_packages` is resolved in
    # `services.brief`'s own namespace, so patching the package's re-export
    # would bind a name `build_workflow` never looks at. Moved when services
    # became a package (phase 7); the test's intent is unchanged.
    @patch("src.gui.services.brief.generate_packages")
    def test_build_refuses_with_doctrine_error(self, mock_generate, tmp_path):
        mock_generate.side_effect = BuildRefusedError("Simulated doctrine refusal")
        outcome = build_workflow(EXAMPLE_BRIEF, tmp_path / "out")
        assert not outcome.ok
        assert outcome.summary == "Build refused by doctrine."
        assert outcome.refusal == "Simulated doctrine refusal"

# --------------------------------------------------------------- view layer


@pytest.fixture()
def app():
    """Construct the CustomTkinter app, or skip if there is no display."""
    ctk = pytest.importorskip("customtkinter")
    import tkinter

    from src.gui.app import FukasawaApp

    try:
        window = FukasawaApp()
    except tkinter.TclError as exc:
        pytest.skip(f"no display for GUI test: {exc}")
    yield window
    window.destroy()


class TestGuiView:
    def test_validate_tab_renders_valid_brief(self, app):
        app.set_fields(validate_entry=str(EXAMPLE_BRIEF))
        result = app.on_validate()
        assert result.ok
        shown = app.validate_results.get("1.0", "end")
        assert "is valid" in shown
        assert "q2c-production-handoff" in shown

    def test_validate_tab_renders_problems(self, app, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("id: 'Bad Id!'\ntitle: x\n")
        app.set_fields(validate_entry=str(bad))
        result = app.on_validate()
        assert not result.ok
        assert "✗" in app.validate_results.get("1.0", "end")

    def test_build_tab_builds_and_lists_packages(self, app, cpax_workspace, tmp_path):
        app.set_fields(
            build_brief_entry=str(EXAMPLE_BRIEF),
            build_out_entry=str(tmp_path / "out"),
            build_ws_entry=str(cpax_workspace),
        )
        outcome = app.on_build()
        assert outcome.ok
        shown = app.build_results.get("1.0", "end")
        assert "writer-agent" in shown
        assert "publisher-agent" in shown

    def test_build_tab_requires_fields(self, app):
        app.set_fields(build_brief_entry="", build_out_entry="")
        outcome = app.on_build()
        assert not outcome.ok
        assert "required" in app.build_results.get("1.0", "end").lower()
