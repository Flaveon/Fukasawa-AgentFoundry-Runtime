# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Bundled-resource resolution — phase 9.

`packaging/fukasawa.spec` bundles all 39 files under `examples/` into the
PyInstaller binary, and until phase 9 not one of them was reachable: PyInstaller
unpacks data into `sys._MEIPASS` and nothing resolved paths against it. Every
documented command of the form

    fukasawa workflow validate examples/workflows/.../observed-workflow.yaml

worked from a checkout and failed from the binary with "No such file", while the
file sat inside the executable the operator had just run.

These tests fake the frozen state rather than requiring a built binary, so they
run in the ordinary suite. `tests/test_packaging.py` covers the wheel; the
binary itself is verified by hand and recorded in `docs/packaging-guide.md`.
"""

from pathlib import Path

import pytest

from src import resources

ROOT = Path(__file__).resolve().parent.parent
PILOT = "examples/workflows/substack-publication/observed-workflow.yaml"


@pytest.fixture()
def frozen(tmp_path, monkeypatch):
    """Pretend to be a PyInstaller binary whose bundle root is tmp_path."""
    monkeypatch.setattr(resources.sys, "frozen", True, raising=False)
    monkeypatch.setattr(resources.sys, "_MEIPASS", str(tmp_path), raising=False)
    return tmp_path


class TestNotFrozen:
    """A source checkout must behave exactly as it always did."""

    def test_bundle_root_is_none(self):
        assert resources.bundle_root() is None

    def test_resolve_is_the_identity(self):
        assert resources.resolve("anything/at/all.yaml") == Path("anything/at/all.yaml")

    def test_an_existing_path_comes_back_unchanged(self):
        assert resources.resolve(ROOT / PILOT) == ROOT / PILOT


class TestFrozen:
    def test_a_bundled_file_is_found(self, frozen, tmp_path, monkeypatch):
        # chdir somewhere the file does NOT exist locally. Without this the
        # test passes for the wrong reason from a repo checkout, where
        # `examples/...` is genuinely present and rule 1 answers first.
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)

        target = frozen / PILOT
        target.parent.mkdir(parents=True)
        target.write_text("workflow_id: x", encoding="utf-8")
        assert resources.resolve(PILOT) == target

    def test_the_working_directory_always_wins(self, frozen, tmp_path, monkeypatch):
        # The operator's own file beats the bundled one of the same name. If it
        # did not, editing a copy of the pilot would silently validate the
        # shipped original and the operator would never know.
        work = tmp_path / "work"
        work.mkdir()
        local = work / "observed.yaml"
        local.write_text("workflow_id: mine", encoding="utf-8")
        bundled = frozen / "observed.yaml"
        bundled.write_text("workflow_id: theirs", encoding="utf-8")

        monkeypatch.chdir(work)
        assert resources.resolve("observed.yaml").read_text() == "workflow_id: mine"

    def test_a_missing_file_reports_what_the_operator_typed(self, frozen):
        # Not the temp directory they have never heard of.
        assert resources.resolve("nope.yaml") == Path("nope.yaml")

    def test_an_absolute_path_is_never_redirected(self, frozen):
        # /etc/passwd must not become <bundle>/etc/passwd.
        assert resources.resolve("/etc/hosts") == Path("/etc/hosts")

    def test_an_absolute_missing_path_is_returned_as_given(self, frozen):
        assert resources.resolve("/no/such/file.yaml") == Path("/no/such/file.yaml")

    def test_bundled_examples_points_into_the_bundle(self, frozen):
        (frozen / "examples").mkdir()
        assert resources.bundled_examples() == frozen / "examples"

    def test_bundled_examples_is_none_when_absent(self, frozen):
        assert resources.bundled_examples() is None


class TestTheCliUsesIt:
    """The seam is only useful if the CLI actually goes through it."""

    def test_both_loaders_resolve(self):
        source = (ROOT / "src" / "cli.py").read_text(encoding="utf-8")
        assert source.count("resources.resolve(path)") == 2, (
            "the CLI's two path loaders must both go through resources.resolve; "
            "a third loader added later needs it too"
        )

    def test_the_pilot_still_loads_by_its_documented_path(self, tmp_path):
        # The path every document tells an operator to type, from the repo root.
        from typer.testing import CliRunner

        from src.cli import app

        result = CliRunner().invoke(
            app, ["workflow", "validate", str(ROOT / PILOT), "--db", str(tmp_path / "d.db")]
        )
        assert result.exit_code == 2, result.output  # blocking findings, as expected
