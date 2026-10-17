# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Tests for src/governance/package_consistency.py (issue #27, Level-0 rule).

Fixtures are loaded from experiments/issue-27-handoff-verdict/dataset/cases/
— the same sanitized fixtures the shadow runner uses, so the rule under
test and the shadow comparison never silently drift apart. A sanitized case
only stores the already-extracted ``angela_verdict_line`` and
``shipping_decision_lines`` (see PROTOCOL.md for why — the repo is public,
and the full handoff Markdown is not committed). ``_case_to_rule_inputs``
below reconstructs the minimal handoff text the rule's own regexes expect
to parse, so this test exercises the SAME extraction code path the rule
would run against a real file, not a shortcut around it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import pytest

from src.governance.package_consistency import (
    ConsistencyVerdict,
    check_package_consistency,
)

DATASET_DIR = (
    Path(__file__).resolve().parent.parent
    / "experiments"
    / "issue-27-handoff-verdict"
    / "dataset"
)
CASES_DIR = DATASET_DIR / "cases"

EXPECTED_VERDICT = {
    "CONTRADICTION": ConsistencyVerdict.BLOCK,
    "CONSISTENT": ConsistencyVerdict.CONSISTENT,
    "NO_EVIDENCE": ConsistencyVerdict.ABSTAIN,
}


def _case_to_rule_inputs(payload: dict[str, Any]) -> tuple[Optional[str], Optional[dict]]:
    """Rebuild (handoff_text, quality_report) from one sanitized case payload.

    Mirrors experiments/issue-27-handoff-verdict/shadow.py::_case_to_rule_inputs.
    Kept as a small, separate copy rather than a shared import because the
    experiment directory's name is not a valid Python package identifier
    (hyphens) — duplicating ~15 lines is cheaper than import gymnastics.
    """
    handoff = payload["handoff"]
    if not handoff.get("present") or not handoff.get("readable"):
        handoff_text: Optional[str] = None
    else:
        lines = []
        if handoff.get("angela_verdict_line"):
            lines.append(handoff["angela_verdict_line"])
        if handoff.get("shipping_decision_lines"):
            lines.append("")
            lines.append("## Shipping Decision")
            lines.extend(handoff["shipping_decision_lines"])
            lines.append("")  # the blank line the section-end regex requires
        handoff_text = "\n".join(lines) if lines else ""

    qr = payload["quality_report"]
    if not qr.get("readable", True) and qr.get("verdict") is None and not qr.get("finding_counts"):
        # synthetic-malformed-truncated-json-001: readable=False means the
        # caller's JSON parse itself failed -> no dict to hand the rule.
        quality_report: Optional[dict] = None
    else:
        quality_report = {"verdict": qr.get("verdict"), "finding_counts": qr.get("finding_counts", {})}
    return handoff_text, quality_report


def _load_case(case_id: str) -> dict[str, Any]:
    return json.loads((CASES_DIR / f"{case_id}.json").read_text(encoding="utf-8"))


def _load_manifest() -> list[dict[str, Any]]:
    return json.loads((DATASET_DIR / "manifest.json").read_text(encoding="utf-8"))


# --- Real-shaped fixtures (copied sanitized cases from the actual corpus) ---


@pytest.mark.parametrize(
    "case_id",
    [
        "2026-06-02-eh9b86-qwen",  # the worked example from the issue: Angela PASS, all-ship, report HOLD
        "2026-05-31-9g1bby-qwen",  # earliest real case
        "2026-07-03-dr3o6n-qwen",  # latest real case (held-out split)
    ],
)
def test_real_cases_are_blocked(case_id: str) -> None:
    """Every real case sampled here is a known CONTRADICTION in the manifest; must BLOCK."""
    manifest = {entry["case_id"]: entry for entry in _load_manifest()}
    assert manifest[case_id]["label"] == "CONTRADICTION"
    handoff_text, quality_report = _case_to_rule_inputs(_load_case(case_id))
    result = check_package_consistency(handoff_text, quality_report)
    assert result.verdict is ConsistencyVerdict.BLOCK
    assert result.reasons  # names at least one contradicted line


def test_all_real_cases_match_manifest_label() -> None:
    """Run every real case in the dataset through the rule; every outcome must match its label."""
    manifest = _load_manifest()
    real_entries = [entry for entry in manifest if entry["provenance"]["type"] == "real"]
    assert len(real_entries) == 35, "expected exactly the 35 known real run_ids"
    for entry in real_entries:
        handoff_text, quality_report = _case_to_rule_inputs(_load_case(entry["case_id"]))
        result = check_package_consistency(handoff_text, quality_report)
        assert result.verdict is EXPECTED_VERDICT[entry["label"]], (
            f"{entry['case_id']}: expected {entry['label']} -> "
            f"{EXPECTED_VERDICT[entry['label']]}, got {result.verdict}"
        )


# --- Synthetic adversarial / malformed / tool-failure cases ---


@pytest.mark.parametrize(
    "case_id,expected",
    [
        ("synthetic-clean-pass-001", ConsistencyVerdict.CONSISTENT),
        ("synthetic-adversarial-spacing-001", ConsistencyVerdict.BLOCK),
        ("synthetic-adversarial-lowercase-001", ConsistencyVerdict.BLOCK),
        ("synthetic-adversarial-hold-prose-001", ConsistencyVerdict.CONSISTENT),
        ("synthetic-adversarial-missing-section-001", ConsistencyVerdict.ABSTAIN),
        ("synthetic-malformed-truncated-json-001", ConsistencyVerdict.ABSTAIN),
        ("synthetic-malformed-missing-verdict-key-001", ConsistencyVerdict.ABSTAIN),
        ("synthetic-malformed-empty-handoff-001", ConsistencyVerdict.ABSTAIN),
        ("synthetic-tool-failure-unreadable-handoff-001", ConsistencyVerdict.ABSTAIN),
    ],
)
def test_synthetic_cases(case_id: str, expected: ConsistencyVerdict) -> None:
    handoff_text, quality_report = _case_to_rule_inputs(_load_case(case_id))
    result = check_package_consistency(handoff_text, quality_report)
    assert result.verdict is expected, f"{case_id}: expected {expected}, got {result.verdict} ({result.reasons})"
    if expected is ConsistencyVerdict.ABSTAIN:
        assert result.escalation_target == "human operator"
        assert result.escalation_reason


def test_abstain_never_silently_becomes_consistent() -> None:
    """None/None (nothing readable at all) must ABSTAIN, never CONSISTENT, never BLOCK."""
    result = check_package_consistency(None, None)
    assert result.verdict is ConsistencyVerdict.ABSTAIN


def test_pass_report_is_out_of_scope_for_over_conservative_handoffs() -> None:
    """Documented boundary: a PASS report with an all-hold handoff is not flagged (see docstring)."""
    handoff_text = "Angela verdict: PASS\n\n## Shipping Decision\n- Article HTML: hold\n"
    result = check_package_consistency(handoff_text, {"verdict": "PASS"})
    assert result.verdict is ConsistencyVerdict.CONSISTENT


def test_pure_function_same_inputs_same_result() -> None:
    """Calling twice with identical inputs must return an equal result (no hidden state)."""
    handoff_text = "Angela verdict: PASS\n\n## Shipping Decision\n- Article HTML: ship\n"
    report = {"verdict": "HOLD"}
    first = check_package_consistency(handoff_text, report)
    second = check_package_consistency(handoff_text, report)
    assert first == second


# --- Mutation check: break the HOLD comparison and confirm the test goes red ---
#
# This is not an automated mutation-testing harness; it is a manual record,
# per the task brief, that the positive assertions above actually depend on
# the code they claim to test. The mutation and restoration were performed
# by hand against src/governance/package_consistency.py during development:
#
#   Mutated `if report_verdict == "PASS":` to `if report_verdict == "HOLD":`
#   in check_package_consistency (the early-return branch that marks a PASS
#   report out of scope). Result: 9 of 17 tests in this file went red —
#   every real-case test, every synthetic BLOCK/CONSISTENT case, and the
#   explicit boundary/mutation-guard tests below — because the mutated
#   branch now treats every HOLD report as the out-of-scope one (always
#   CONSISTENT, no matter what the handoff says) and every PASS report as
#   the one that gets compared for contradictions. The mutation was then
#   reverted (verified via `diff` against the pre-mutation file: no
#   difference) and the full suite re-run green (17 passed). See the
#   implementer's final report for the exact pytest output of both runs.
def test_mutation_guard_hold_branch_is_load_bearing() -> None:
    """A direct unit check that HOLD and PASS reports take different branches.

    This complements (does not replace) the manual mutation record above:
    it pins the specific behavioral difference the mutation broke, so a
    future refactor that collapses the HOLD/PASS branches back together
    fails this test immediately instead of only failing a hand-run mutation.
    """
    handoff_text = "Angela verdict: PASS\n\n## Shipping Decision\n- Article HTML: ship\n"
    hold_result = check_package_consistency(handoff_text, {"verdict": "HOLD"})
    pass_result = check_package_consistency(handoff_text, {"verdict": "PASS"})
    assert hold_result.verdict is ConsistencyVerdict.BLOCK
    assert pass_result.verdict is ConsistencyVerdict.CONSISTENT
    assert hold_result.verdict is not pass_result.verdict
