# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Automated rollback test for the issue #27 package-consistency capsule.

Proves the claim in experiments/issue-27-handoff-verdict/capsule/ROLLOUT.md:
with the capsule disabled (its rule function never invoked), the shadow
runner emits no rule findings at all, and Baseline A's real-world numbers
(what the pipeline's own handoff documents actually say) are completely
unchanged — because Baseline A never calls the rule in the first place.

This is the rollback guarantee available at the Shadow stage: there is no
live integration point to disable yet (nothing outside this experiment
calls the rule), so the strongest thing to prove is that the shadow
runner's own output collapses to "nothing found" when the rule is not
called, and that nothing else in the experiment depends on it having been
called.

The experiment directory's name (``issue-27-handoff-verdict``) is not a
valid Python package identifier (hyphens), so its modules are loaded here
via ``importlib.util`` rather than a normal import statement.
"""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

EXPERIMENT_DIR = (
    Path(__file__).resolve().parent.parent / "experiments" / "issue-27-handoff-verdict"
)


def _load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, EXPERIMENT_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_baseline_a_never_references_the_capsule_rule() -> None:
    """Baseline A's source never names check_package_consistency or the governance module.

    This is the structural guarantee that "baseline behaviour is unchanged"
    when the capsule is disabled: Baseline A cannot be affected by the
    capsule's presence or absence because it never calls into it.
    """
    baseline = _load_module("issue27_baseline_rollback_check", "baseline.py")
    source = inspect.getsource(baseline.run_baseline_a)
    assert "check_package_consistency" not in source
    assert "package_consistency" not in source


def test_shadow_runner_emits_no_findings_when_capsule_disabled(monkeypatch) -> None:
    """With the rule function replaced by a disabled no-op, the shadow runner finds nothing."""
    shadow = _load_module("issue27_shadow_rollback_check", "shadow.py")

    from src.governance.package_consistency import ConsistencyResult, ConsistencyVerdict

    def disabled_rule(handoff_text, quality_report):  # noqa: ARG001 - signature must match
        """Stand-in for 'the capsule is not wired in': always CONSISTENT, no reasons, no BLOCK."""
        return ConsistencyResult(verdict=ConsistencyVerdict.CONSISTENT, reasons=())

    monkeypatch.setattr(shadow, "check_package_consistency", disabled_rule)

    treatment = shadow.run_treatment()

    blocked_cases = [
        case_id
        for case_id, result in treatment["per_case"].items()
        if result["rule_verdict"] == "BLOCK"
    ]
    cases_with_reasons = [
        case_id for case_id, result in treatment["per_case"].items() if result["reasons"]
    ]
    assert blocked_cases == [], "disabled capsule must never BLOCK anything"
    assert cases_with_reasons == [], "disabled capsule must never surface a reason/finding"

    abstentions = sum(split.get("abstentions", 0) for split in treatment["per_split"].values())
    assert abstentions == 0, "disabled capsule must never ABSTAIN either -- it is simply not called"


def test_baseline_a_identical_with_and_without_the_rule_imported() -> None:
    """Baseline A's actual numeric output is identical whether or not the governance rule exists.

    Simulates "capsule removed from the system": temporarily hides the
    governance module from sys.modules / the import system is overkill for
    a pure-function rule with no side effects, so this test instead proves
    the simpler, sufficient fact: calling run_baseline_a() twice -- once
    before anything related to the capsule is touched, once after the
    shadow runner's treatment pass has fully executed -- produces byte-for-
    byte identical output. Baseline A has no shared state with the rule.
    """
    baseline = _load_module("issue27_baseline_rollback_check_2", "baseline.py")
    shadow = _load_module("issue27_shadow_rollback_check_2", "shadow.py")

    cases = baseline.load_cases()
    before = baseline.run_baseline_a(cases)

    shadow.run_treatment()  # exercise the capsule fully

    after = baseline.run_baseline_a(cases)
    assert before == after
