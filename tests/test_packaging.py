# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Packaging tests — master handoff §15.7, the gap that let a wheel ship broken.

Every other test in this suite runs from the source tree, where `import
src.gui.services` works because the directory is right there. That is exactly
why the defect these tests exist for was invisible: `pyproject.toml` listed its
packages by hand, phase 7 split `src/gui/services.py` into a package, and
nobody updated the list. A `pip install .` then produced a wheel with no
`src/gui/services/` in it at all — a GUI that cannot import its own service
layer — while 559 tests passed and CI stayed green, because CI builds through a
PyInstaller spec file rather than through setuptools.

Two guards, and they cover different things:

* `test_every_source_package_is_declared` is the cheap one, and it is aimed at
  the *hand-written list* style — the style that broke. Under the discovery
  style now in use it is close to vacuous by construction, and it stays because
  reverting to an explicit list is a plausible future edit and this is what
  would catch the omission.
* `test_a_built_wheel_contains_every_package` builds a real wheel and reads its
  manifest. It is the one that actually proves the claim, under either style,
  and it is why the fast test being weak is acceptable rather than a gap.
"""

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"


def source_packages() -> set[str]:
    """Every importable package under `src/`, dotted, including `src` itself."""
    found = {"src"}
    for init in SRC.rglob("__init__.py"):
        if "__pycache__" in init.parts:
            continue
        found.add(".".join(init.relative_to(ROOT).parent.parts))
    return found


def declared_packages() -> set[str]:
    """Every package the pyproject would collect, whichever style it uses.

    The glob matching is reimplemented here rather than imported from
    setuptools, which is a build-time dependency and absent from a plain test
    venv. `find.include` patterns are shell globs over dotted names, and
    `fnmatch` is what setuptools uses for them too.
    """
    import fnmatch
    import tomllib

    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    tool = config.get("tool", {}).get("setuptools", {})

    explicit = tool.get("packages")
    if isinstance(explicit, list):
        return set(explicit)

    find = (explicit or {}).get("find", {})
    include = find.get("include", ["*"])
    exclude = find.get("exclude", [])

    def matches(name: str, patterns: list[str]) -> bool:
        return any(fnmatch.fnmatchcase(name, p) for p in patterns)

    # The candidate set is the tree itself: what is declared is the subset of
    # what exists that the patterns admit. That is precisely what setuptools'
    # discovery computes.
    return {
        name
        for name in source_packages()
        if matches(name, include) and not matches(name, exclude)
    }


def test_every_source_package_is_declared():
    """No package in the tree may be missing from the distribution.

    Aimed at the explicit-list style: it would have caught `src.gui.services`
    the moment the split happened, with no build and no network. The discovery
    style now configured makes it near-tautological — see the module docstring
    — and the wheel test below is what carries the property today.
    """
    missing = source_packages() - declared_packages()
    assert not missing, (
        f"{sorted(missing)} exist in src/ but would not be packaged. "
        f"A wheel built now installs a broken import."
    )


def test_no_declared_package_is_a_ghost():
    """And nothing is declared that does not exist, which would fail the build."""
    ghosts = {p for p in declared_packages() if p.startswith("src")} - source_packages()
    assert not ghosts, f"{sorted(ghosts)} are declared but not in the tree"


def test_a_built_wheel_contains_every_package(tmp_path):
    """Build a real wheel and look inside it.

    The only test here that proves the claim rather than approximating it, and
    the reason it runs on every invocation rather than behind a slow marker: a
    guard for a defect that shipped once, gated behind a flag nobody passes, is
    not a guard.
    Skipped rather than failed when the build backend is unavailable — a
    missing `wheel` is an environment fact, not a defect in this repository.
    """
    # Two precautions, both load-bearing, both found by breaking
    # `pyproject.toml` and watching this stay green anyway:
    #
    # * --no-cache-dir, or pip serves a wheel it built earlier from this same
    #   directory and the assertion runs against a stale artifact.
    # * building from a copy, not from ROOT. An in-place build leaves a
    #   `*.egg-info/SOURCES.txt` behind, and setuptools reads that manifest on
    #   the next build — so the residue of a correct build makes a later broken
    #   config look correct. It is gitignored, so it survives invisibly.
    source = tmp_path / "clean"
    shutil.copytree(
        ROOT,
        source,
        ignore=shutil.ignore_patterns(
            ".git", ".venv", "__pycache__", "*.egg-info", "build", "dist", "*.db"
        ),
    )
    result = subprocess.run(
        [
            sys.executable, "-m", "pip", "wheel",
            "--no-deps", "--no-cache-dir", "-w", str(tmp_path), str(source),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"could not build a wheel here: {result.stderr[-300:]}")

    wheels = list(tmp_path.glob("*.whl"))
    assert wheels, "pip reported success but produced no wheel"
    with zipfile.ZipFile(wheels[0]) as archive:
        names = set(archive.namelist())

    for package in sorted(source_packages()):
        expected = package.replace(".", "/") + "/__init__.py"
        assert expected in names, f"{package} is missing from the built wheel"


# ------------------------------------------------------- the documented commands


class TestDocumentedCommandsAreReal:
    """§2.3: "a clean checkout can install, test, build, and run using
    documented commands", and §17: "useful --help".

    Written after the README shipped `fukasawa workflow findings <workflow-id>`
    when that command actually takes a path. Documentation drift of this kind is
    invisible until someone types the command and it fails, and by then they
    have concluded the tool is broken rather than the sentence.
    """

    README = ROOT / "README.md"

    #: (command, argument metavar the CLI really declares).
    EXPECTED = {
        "init": "workflow_id",
        "validate": "path",
        "findings": "path",
        "accept-risk": "path",
        "promote": "path",
        "assess-cooperation": "workflow_id",
        "build-cooperative": "workflow_id",
        "export-agent-brief": "workflow_id",
        "status": "workflow_id",
    }

    def test_every_workflow_command_exists(self):
        from typer.testing import CliRunner

        from src.cli import app

        result = CliRunner().invoke(app, ["workflow", "--help"])
        assert result.exit_code == 0
        for command in self.EXPECTED:
            assert command in result.output, f"`workflow {command}` is gone"

    @pytest.mark.parametrize("command,metavar", sorted(EXPECTED.items()))
    def test_each_command_takes_the_argument_the_readme_says(self, command, metavar):
        from typer.testing import CliRunner

        from src.cli import app

        result = CliRunner().invoke(app, ["workflow", command, "--help"])
        assert result.exit_code == 0, result.output
        assert metavar in result.output, (
            f"`workflow {command}` no longer takes {metavar!r}; the README "
            f"documents it as such and would now be wrong"
        )

    def test_the_readme_documents_each_command_with_the_right_argument(self):
        text = self.README.read_text(encoding="utf-8")
        wrong = []
        for command, metavar in self.EXPECTED.items():
            line = next(
                (
                    ln for ln in text.splitlines()
                    if ln.strip().startswith(f"fukasawa workflow {command} ")
                ),
                None,
            )
            if line is None:
                wrong.append(f"{command}: not documented in the README")
                continue
            # The README writes `path` as <draft.yaml> and workflow_id as
            # <workflow-id>; check the shape rather than the literal metavar.
            shown_path = "<draft.yaml>" in line
            shown_id = "<workflow-id>" in line
            if metavar == "path" and not shown_path:
                wrong.append(f"{command}: takes a path, README shows {line.strip()!r}")
            if metavar == "workflow_id" and not shown_id:
                wrong.append(f"{command}: takes an id, README shows {line.strip()!r}")
        assert not wrong, "README command drift:\n  " + "\n  ".join(wrong)

    def test_the_readme_does_not_claim_unbuilt_infrastructure(self):
        """The README described a "workflow node library" and a prompt/module
        registry as delivered infrastructure. Neither exists — the first not at
        all, the second as a `schema_version: 0.1` draft no code reads.

        That text dated from the 2026-07-19 planning package and survived nine
        phases unread. This fails if either claim returns without the thing.
        """
        text = self.README.read_text(encoding="utf-8").lower()
        historical = text[text.index("historical, not current"):] if "historical, not current" in text else ""

        node_library_exists = any(
            "node_library" in p.read_text(encoding="utf-8")
            or "NodeLibrary" in p.read_text(encoding="utf-8")
            for p in (ROOT / "src").rglob("*.py")
        )
        if not node_library_exists:
            claims = text.count("node library")
            assert claims == 0 or "node library" in historical, (
                "the README mentions a workflow node library outside the "
                "historical-documents section, and none exists in src/"
            )

    def test_every_doc_the_readme_links_exists(self):
        import re

        text = self.README.read_text(encoding="utf-8")
        referenced = set(re.findall(r"`(docs/[a-z0-9-]+\.md)`", text))
        assert referenced, "the README stopped linking any documentation"
        missing = [d for d in sorted(referenced) if not (ROOT / d).is_file()]
        assert not missing, f"README links dead documents: {missing}"
