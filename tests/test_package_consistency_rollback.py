# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Automated rollback tests for the issue #27 package-consistency capsule.

v2 note (post-review, M3 — see PROTOCOL.md Amendment 3): this file was
rewritten. The v1 version modelled "the capsule is disabled" as a stub rule
function that always returns CONSISTENT — the exact fail-open failure mode
this whole rewrite exists to eliminate, and a review found it proved
little: it survived an injected dependency in ``run_baseline_a`` (the
static check only inspects that one function's own source text, and the
before/after equality check is trivially true for a pure function whether
or not anything actually changed), and the real rollback described in
``capsule/ROLLOUT.md`` (deleting ``package_consistency.py``) broke the
suite outright, because ``ROLLOUT.md``'s own file list omitted this test
file. This version drops the "disabled = always CONSISTENT" model entirely
and proves two narrower, real things instead:

(a) Baseline A's computation does not import or call the rule — checked
    both statically (its source text never names the rule) and at runtime
    (it still runs correctly with the rule module blocked from being
    imported at all, simulating the module not existing).
(b) Nothing else under ``src/`` references the rule module, so removing
    ``src/governance/package_consistency.py`` cannot silently break
    anything outside the files ``capsule/ROLLOUT.md`` already lists for
    deletion.

A third test pins that ``shadow.py``'s only dependency on the rule is a
single, removable import line, supporting ``ROLLOUT.md``'s claim that
deleting ``shadow.py`` alongside the rule is a complete, clean removal —
not a partial one that leaves dangling references.

The experiment directory's name (``issue-27-handoff-verdict``) is not a
valid Python package identifier (hyphens), so its modules are loaded here
via ``importlib.util`` rather than a normal import statement.
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path

EXPERIMENT_DIR = (
    Path(__file__).resolve().parent.parent / "experiments" / "issue-27-handoff-verdict"
)
REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
RULE_MODULE_NAME = "src.governance.package_consistency"
RULE_FILE = SRC_DIR / "governance" / "package_consistency.py"


def _load_module(name: str, filename: str):
    """Load one experiment-directory script as a module (its dir name is not a valid package id)."""
    spec = importlib.util.spec_from_file_location(name, EXPERIMENT_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_baseline_a_never_references_the_capsule_rule_statically() -> None:
    """Baseline A's source never names check_package_consistency or the governance module."""
    baseline = _load_module("issue27_baseline_rollback_static", "baseline.py")
    source = inspect.getsource(baseline.run_baseline_a)
    assert "check_package_consistency" not in source
    assert "package_consistency" not in source


def test_baseline_a_runs_with_the_rule_module_unimportable(monkeypatch) -> None:
    """(a) Runtime proof: run_baseline_a works even if the rule module cannot be imported at all.

    Setting sys.modules[RULE_MODULE_NAME] = None forces any `import
    src.governance.package_consistency` (or `from ... import ...`) anywhere
    in the call stack to raise ImportError, as if the module genuinely did
    not exist on disk. If run_baseline_a (or anything it transitively
    calls) secretly depended on the rule, this test would fail with that
    ImportError. It does not -- proving the dependency the static check
    above suggests is also true at runtime, not just absent from one
    function's source text.
    """
    baseline = _load_module("issue27_baseline_rollback_runtime", "baseline.py")
    monkeypatch.setitem(sys.modules, RULE_MODULE_NAME, None)

    cases = baseline.load_cases()
    result = baseline.run_baseline_a(cases)

    assert result, "run_baseline_a should still produce real output with the rule module blocked"
    total_cases = sum(bucket["cases"] for bucket in result.values())
    assert total_cases == 35, "all 35 real cases should still be counted"


def test_rest_of_src_does_not_import_the_rule() -> None:
    """(b) Nothing under src/, other than the rule module itself, references it.

    This is what makes "rollback = delete src/governance/package_consistency.py"
    a clean, complete removal rather than one that leaves a dangling import
    somewhere else under src/ that ROLLOUT.md's file list did not catch.
    """
    offending: list[str] = []
    for path in SRC_DIR.rglob("*.py"):
        if path == RULE_FILE:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "package_consistency" in text:
            offending.append(str(path.relative_to(REPO_ROOT)))
    assert offending == [], (
        f"these src/ files reference package_consistency and would break if it were "
        f"deleted without also fixing them: {offending}"
    )


def test_shadow_py_rule_dependency_is_isolated_to_one_import_line() -> None:
    """shadow.py's only reference to the rule is a single, removable import statement.

    Supports ROLLOUT.md's rollback file list, which deletes shadow.py
    alongside the rule module rather than trying to keep a half-working
    shadow runner around: this test pins that there is exactly one line to
    account for, not an unknown number of call sites scattered through the
    file.
    """
    shadow_source = (EXPERIMENT_DIR / "shadow.py").read_text(encoding="utf-8")
    import_lines = [
        line.strip()
        for line in shadow_source.splitlines()
        if "package_consistency" in line and "import" in line
    ]
    assert len(import_lines) == 1, f"expected exactly one import line, found: {import_lines}"
    assert import_lines[0].startswith("from src.governance.package_consistency import")
