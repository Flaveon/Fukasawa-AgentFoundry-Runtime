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

v2 note: this file was rewritten after an independent review (PROTOCOL.md
Amendment 3) found the v1 rule failed open — it silently read unparseable
input as "not ship" and returned CONSISTENT. The ``ADVERSARIAL_CASES``
table below is the review's own adversarial script, committed verbatim as
tests rather than left in a scratch directory, plus the branch-pinning
tests in the "M2" section that the review found were missing (mutations
that survived the v1 suite).
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
    """Run every real case in the dataset through the rule; every outcome must match its label.

    Review note (M1, PROTOCOL.md Amendment 3): all 35 real cases reduce to
    4 distinct rule inputs, all against a HOLD report — this test exercises
    the same 4 shapes 35 times, not 35 independent inputs. It is a
    regression check against this specific corpus, not evidence of
    generalization. See ADVERSARIAL_CASES below for the inputs that
    actually exercise the rule's parsing logic.
    """
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


# --- Synthetic adversarial / malformed / tool-failure cases (dataset fixtures) ---


@pytest.mark.parametrize(
    "case_id,expected",
    [
        ("synthetic-clean-pass-001", ConsistencyVerdict.CONSISTENT),
        ("synthetic-adversarial-spacing-001", ConsistencyVerdict.BLOCK),
        ("synthetic-adversarial-lowercase-001", ConsistencyVerdict.BLOCK),
        # v2 correction (post-review): a shipping value that merely MENTIONS
        # "ship" in prose ("hold (ship once blockers fixed)") no longer
        # resolves to CONSISTENT by cleverly checking only a value prefix.
        # v2's allowlist requires an EXACT value match ("hold", not "hold
        # (ship once blockers fixed)"), so decorated/prose-suffixed values
        # are unparseable -> ABSTAIN, never silently resolved either way.
        ("synthetic-adversarial-hold-prose-001", ConsistencyVerdict.ABSTAIN),
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


# --- Adversarial cases, committed verbatim from the independent review ------
#
# This is the reviewer's own adversarial script (originally
# /tmp/.../scratchpad/d27r/adv.py), kept here as a permanent, version-
# controlled test rather than a one-off scratch artifact. Each case is a
# handoff built from the SAME real-shaped template the pipeline uses
# (base header + an Angela line + a Shipping Decision block), varying one
# adversarial property at a time, always against a HOLD report with one
# finding. Expected outcomes were derived by running v2 and recording what
# a fail-closed allowlist parser should, and does, produce — see the
# per-case comments for the reasoning, not just the number.

_HOLD_REPORT = {"verdict": "HOLD", "finding_counts": {"x": 1}}
_BASE_HEADER = "# Duath Operator Handoff\n\nTopic: x\n"
_NEEDS_REVISION = "Angela verdict: NEEDS_REVISION"


def _handoff(angela: str, ship_block: str) -> str:
    """Build a real-shaped handoff: header + an Angela line + a Shipping Decision block."""
    return _BASE_HEADER + angela + "\n\n" + ship_block + "\n"


ADVERSARIAL_CASES: dict[str, tuple[str, ConsistencyVerdict]] = {
    # name: (handoff_text, expected_verdict)
    "baseline_real_shape": (
        _handoff(_NEEDS_REVISION, "## Shipping Decision\n- Article HTML: ship\n- Visual support: ship\n- Interactive tool: ship"),
        ConsistencyVerdict.BLOCK,  # clean, recognized "ship" line -> correctly caught
    ),
    "cyrillic_S_ship": (
        _handoff(_NEEDS_REVISION, "## Shipping Decision\n- Article HTML: Ѕhip"),
        ConsistencyVerdict.ABSTAIN,  # Cyrillic Ѕ is not a Latin "S"; NFKC does not fix it
    ),
    "fullwidth_ship": (
        _handoff(_NEEDS_REVISION, "## Shipping Decision\n- Article HTML: ｓｈｉｐ"),
        # NFKC normalizes fullwidth Latin to plain ASCII "ship" -- a width
        # convention, not a disguise. Recognized and correctly BLOCKed; see
        # package_consistency.py's _normalize docstring for the reasoning.
        ConsistencyVerdict.BLOCK,
    ),
    "bold_ship": (
        _handoff(_NEEDS_REVISION, "## Shipping Decision\n- Article HTML: **ship**"),
        ConsistencyVerdict.ABSTAIN,  # decorated value, not an exact match
    ),
    "backtick_ship": (
        _handoff(_NEEDS_REVISION, "## Shipping Decision\n- Article HTML: `ship`"),
        ConsistencyVerdict.ABSTAIN,
    ),
    "emoji_ship": (
        _handoff(_NEEDS_REVISION, "## Shipping Decision\n- Article HTML: ✅ ship"),
        ConsistencyVerdict.ABSTAIN,
    ),
    "yes_publish": (
        _handoff(_NEEDS_REVISION, "## Shipping Decision\n- Article HTML: publish"),
        ConsistencyVerdict.ABSTAIN,  # a different word is not a recognized value
    ),
    "star_bullet": (
        _handoff(_NEEDS_REVISION, "## Shipping Decision\n* Article HTML: ship"),
        ConsistencyVerdict.ABSTAIN,  # only "-" is a recognized bullet marker
    ),
    "numbered_bullet": (
        _handoff(_NEEDS_REVISION, "## Shipping Decision\n1. Article HTML: ship"),
        ConsistencyVerdict.ABSTAIN,
    ),
    "emdash_no_colon": (
        _handoff(_NEEDS_REVISION, "## Shipping Decision\n- Article HTML — ship"),
        ConsistencyVerdict.ABSTAIN,  # no colon separator at all
    ),
    "h3_header": (
        _handoff(_NEEDS_REVISION, "### Shipping Decision\n- Article HTML: ship"),
        ConsistencyVerdict.ABSTAIN,  # wrong header level
    ),
    "plural_header": (
        _handoff(_NEEDS_REVISION, "## Shipping Decisions\n- Article HTML: ship"),
        ConsistencyVerdict.ABSTAIN,
    ),
    "header_suffix": (
        _handoff(_NEEDS_REVISION, "## Shipping Decision (Dwight)\n- Article HTML: ship"),
        ConsistencyVerdict.ABSTAIN,
    ),
    "blank_after_header": (
        _handoff(_NEEDS_REVISION, "## Shipping Decision\n\n- Article HTML: ship"),
        # A single clean bullet after a benign extra blank line right after
        # the header is still one clean paragraph once blank lines are
        # filtered -- nothing is lost, so this one still resolves. Compare
        # to blank_between_bullets below, where real content follows the
        # blank line and would be silently dropped if not caught.
        ConsistencyVerdict.BLOCK,
    ),
    "blank_between_bullets": (
        _handoff(_NEEDS_REVISION, "## Shipping Decision\n- Article HTML: hold\n\n- Visual support: ship"),
        # A blank line SPLITS real content across two paragraphs; reading
        # only the first would silently miss the "ship" line entirely.
        ConsistencyVerdict.ABSTAIN,
    ),
    "two_sections": (
        _handoff(_NEEDS_REVISION, "## Shipping Decision\n- Article HTML: hold\n\n## Shipping Decision\n- Visual support: ship"),
        ConsistencyVerdict.ABSTAIN,  # more than one section -> ambiguous which is authoritative
    ),
    "multi_angela_second_pass": (
        _handoff(_NEEDS_REVISION + "\nAngela verdict: PASS", "## Shipping Decision\n- Article HTML: hold"),
        ConsistencyVerdict.ABSTAIN,  # duplicate Angela line -> which one is real?
    ),
    "angela_PASS_no_revisions": (
        _handoff("Angela verdict: PASS (no revisions needed)", "## Shipping Decision\n- Article HTML: hold"),
        ConsistencyVerdict.ABSTAIN,  # trailing parenthetical -> not an exact value match
    ),
    "angela_PASS_no_failures": (
        _handoff("Angela verdict: PASS - zero failures", "## Shipping Decision\n- Article HTML: hold"),
        ConsistencyVerdict.ABSTAIN,
    ),
    "angela_PASSED": (
        _handoff("Angela verdict: PASSED", "## Shipping Decision\n- Article HTML: hold"),
        ConsistencyVerdict.ABSTAIN,  # "PASSED" is not an allowlisted token ("PASS" is)
    ),
    "angela_cyrillic_PASS": (
        _handoff("Angela verdict: РASS", "## Shipping Decision\n- Article HTML: hold"),
        ConsistencyVerdict.ABSTAIN,  # Cyrillic Р is not a Latin "P"
    ),
    "angela_nbsp": (
        # A non-breaking space between "Angela" and "verdict" -- NFKC
        # normalizes it to a plain space, so this structurally-benign
        # whitespace variant does not block recognizing an otherwise
        # well-formed, unqualified PASS claim.
        _handoff("Angela verdict: PASS", "## Shipping Decision\n- Article HTML: hold"),
        ConsistencyVerdict.BLOCK,
    ),
    "angela_bold_label": (
        _handoff("**Angela verdict:** PASS", "## Shipping Decision\n- Article HTML: hold"),
        ConsistencyVerdict.ABSTAIN,  # the LABEL is decorated -> line doesn't match at all
    ),
    "angela_only_NR_no_section": (
        _BASE_HEADER + _NEEDS_REVISION + "\n",
        # NEEDS_REVISION (not PASS) and no Shipping section attempted at
        # all: nothing contradicts a HOLD report here.
        ConsistencyVerdict.CONSISTENT,
    ),
    "angela_NR_section_unparseable": (
        _handoff(_NEEDS_REVISION, "## Shipping Decision\nShip everything."),
        ConsistencyVerdict.ABSTAIN,  # prose, not a bullet -> zero recognized bullets
    ),
    "crlf": (
        _handoff(_NEEDS_REVISION, "## Shipping Decision\n- Article HTML: ship").replace("\n", "\r\n"),
        ConsistencyVerdict.BLOCK,  # CRLF is a line-ending convention, normalized before matching
    ),
    "ship_trailing_text": (
        _handoff(_NEEDS_REVISION, "## Shipping Decision\n- Article HTML: ship (after fix)"),
        ConsistencyVerdict.ABSTAIN,  # trailing text -> not an exact value match
    ),
    "SHIP_heading_only": (
        _BASE_HEADER + "# SHIP IT\n",
        # Neither "angela verdict" nor "shipping decision" appears anywhere
        # -- an unrelated heading using the word "ship" must not trigger
        # either loose detector.
        ConsistencyVerdict.ABSTAIN,
    ),
}


@pytest.mark.parametrize("name", sorted(ADVERSARIAL_CASES))
def test_adversarial_cases_from_independent_review(name: str) -> None:
    handoff_text, expected = ADVERSARIAL_CASES[name]
    result = check_package_consistency(handoff_text, _HOLD_REPORT)
    assert result.verdict is expected, f"{name}: expected {expected}, got {result.verdict} ({result.reasons})"


@pytest.mark.parametrize(
    "name,report",
    [
        ("hold_zero_findings", {"verdict": "HOLD", "finding_counts": {}}),
        ("pass_with_findings", {"verdict": "PASS", "finding_counts": {"x": 1}}),
        ("lower_hold", {"verdict": "hold"}),
        ("unrecognized_verdict_WARN", {"verdict": "WARN"}),
        ("report_is_none", None),
        ("report_is_a_list_not_a_dict", [{"verdict": "HOLD"}]),
        ("report_has_no_verdict_key", {"verdict": None}),
        ("report_is_empty_dict", {}),
    ],
)
def test_report_variants_from_independent_review(name: str, report) -> None:
    """Every quality_report shape the review tried against a clean, real-shaped handoff."""
    handoff_text = ADVERSARIAL_CASES["baseline_real_shape"][0]
    result = check_package_consistency(handoff_text, report)
    if name == "hold_zero_findings":
        assert result.verdict is ConsistencyVerdict.BLOCK, name
    else:
        assert result.verdict is ConsistencyVerdict.ABSTAIN, f"{name}: got {result.verdict}"


def test_nonstr_handoff_text_raises_rather_than_silently_passing() -> None:
    """bytes/int are not a supported handoff_text type; this documents what happens, not a crash fix."""
    with pytest.raises(TypeError):
        check_package_consistency(b"Angela verdict: PASS", _HOLD_REPORT)
    with pytest.raises(AttributeError):
        check_package_consistency(123, _HOLD_REPORT)  # type: ignore[arg-type]


# --- M2: tests that pin each safety branch on its own (so a mutation in ---
# --- exactly that branch is caught, not accidentally covered by another) --


def test_angela_pass_alone_blocks_with_no_shipping_section_at_all() -> None:
    """Angela-PASS detection, pinned alone: no Shipping Decision section exists anywhere."""
    handoff_text = "# Duath Operator Handoff\n\nAngela verdict: PASS\n"
    result = check_package_consistency(handoff_text, {"verdict": "HOLD"})
    assert result.verdict is ConsistencyVerdict.BLOCK
    assert "Angela verdict is PASS" in result.reasons[0]


@pytest.mark.parametrize("value", ["NEEDS_REVISION", "FAIL"])
def test_angela_qualified_values_alone_are_consistent_not_blocked(value: str) -> None:
    """The qualifier, pinned alone: NEEDS_REVISION and FAIL are recognized but never a PASS claim."""
    handoff_text = f"# Duath Operator Handoff\n\nAngela verdict: {value}\n"
    result = check_package_consistency(handoff_text, {"verdict": "HOLD"})
    assert result.verdict is ConsistencyVerdict.CONSISTENT


def test_angela_unknown_alone_abstains() -> None:
    """UNKNOWN is a recognized token, but the pipeline's own placeholder value, not a real answer."""
    handoff_text = "# Duath Operator Handoff\n\nAngela verdict: UNKNOWN\n"
    result = check_package_consistency(handoff_text, {"verdict": "HOLD"})
    assert result.verdict is ConsistencyVerdict.ABSTAIN


def test_every_shipping_line_is_checked_not_just_the_first() -> None:
    """A 'ship' value in the SECOND or THIRD bullet must still BLOCK, not only the first bullet.

    Guards against a regression that reads only shipping_values[0].
    """
    handoff_text = (
        "# Duath Operator Handoff\n\nAngela verdict: NEEDS_REVISION\n\n"
        "## Shipping Decision\n"
        "- Article HTML: hold\n"
        "- Visual support: do not ship\n"
        "- Interactive tool: ship\n"
    )
    result = check_package_consistency(handoff_text, {"verdict": "HOLD"})
    assert result.verdict is ConsistencyVerdict.BLOCK
    assert any("Interactive tool" in reason for reason in result.reasons)


def test_abstain_branch_quality_report_none() -> None:
    """Pinned alone: quality_report=None (report missing/unreadable)."""
    handoff_text = ADVERSARIAL_CASES["baseline_real_shape"][0]
    result = check_package_consistency(handoff_text, None)
    assert result.verdict is ConsistencyVerdict.ABSTAIN
    assert "quality report" in result.reasons[0]


def test_abstain_branch_quality_report_invalid_verdict_value() -> None:
    """Pinned alone: quality_report has a verdict key, but not PASS/HOLD."""
    handoff_text = ADVERSARIAL_CASES["baseline_real_shape"][0]
    result = check_package_consistency(handoff_text, {"verdict": "WARN"})
    assert result.verdict is ConsistencyVerdict.ABSTAIN


def test_abstain_branch_handoff_none() -> None:
    """Pinned alone: handoff_text=None (handoff missing/unreadable), report is valid."""
    result = check_package_consistency(None, {"verdict": "HOLD"})
    assert result.verdict is ConsistencyVerdict.ABSTAIN
    assert "handoff" in result.reasons[0]


def test_abstain_branch_handoff_empty_string() -> None:
    """Pinned alone and DISTINCT from handoff_text=None: an empty (but non-None) string."""
    result = check_package_consistency("", {"verdict": "HOLD"})
    assert result.verdict is ConsistencyVerdict.ABSTAIN


def test_abstain_branch_handoff_readable_but_missing_both_fields() -> None:
    """Pinned alone and DISTINCT from the empty-string branch: non-empty text, neither field present.

    Review finding (M2): the only existing fixture for "readable handoff
    missing fields" (synthetic-adversarial-missing-section-001) is
    rebuilt by _case_to_rule_inputs as the EMPTY string, so it actually
    exercised the empty-handoff branch, not this one. This test uses
    genuinely non-empty, unrelated text so this branch is reached on its
    own, independent of the empty-string branch above.
    """
    handoff_text = "# Some Other Document\n\nThis has nothing to do with Duath at all.\n"
    assert handoff_text.strip()  # sanity: this is NOT the empty-string case
    result = check_package_consistency(handoff_text, {"verdict": "HOLD"})
    assert result.verdict is ConsistencyVerdict.ABSTAIN


def test_abstain_branch_pass_report_with_findings() -> None:
    """Pinned alone: a PASS verdict that still lists findings is internally inconsistent."""
    handoff_text = "# Duath Operator Handoff\n\nAngela verdict: PASS\n"
    result = check_package_consistency(handoff_text, {"verdict": "PASS", "finding_counts": {"x": 1}})
    assert result.verdict is ConsistencyVerdict.ABSTAIN


def test_block_takes_priority_over_an_unrelated_abstain_worthy_field() -> None:
    """A clean, unambiguous BLOCK signal is not buried under ABSTAIN from a different, garbled field.

    Angela's line is garbled (would abstain on its own); the Shipping
    Decision section is clean and says ship. The clean "ship" signal must
    still surface as BLOCK — losing a known escape to an unrelated field's
    noise would be worse than flagging both.
    """
    handoff_text = (
        "# Duath Operator Handoff\n\n**Angela verdict:** PASS\n\n"
        "## Shipping Decision\n- Article HTML: ship\n"
    )
    result = check_package_consistency(handoff_text, {"verdict": "HOLD"})
    assert result.verdict is ConsistencyVerdict.BLOCK


# --- Mutation check: break the HOLD comparison and confirm the test goes red ---
#
# This is not an automated mutation-testing harness; it is a manual record,
# per the task brief, that the positive assertions above actually depend on
# the code they claim to test. The mutation and restoration were performed
# by hand against src/governance/package_consistency.py during development:
#
#   Mutated `if report_verdict == "PASS":` to `if report_verdict == "HOLD":`
#   in check_package_consistency (the early-return branch that marks a PASS
#   report out of scope). Result: every real-case test, every synthetic
#   BLOCK/CONSISTENT case, and the explicit boundary/mutation-guard tests
#   went red, because the mutated branch now treats every HOLD report as
#   the out-of-scope one (always CONSISTENT, no matter what the handoff
#   says) and every PASS report as the one that gets compared for
#   contradictions. The mutation was then reverted (verified via `diff`
#   against the pre-mutation file: no difference) and the full suite
#   re-run green. See the implementer's final report for the exact pytest
#   output of both runs, repeated for v2 after the H1/M2 rewrite.
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


def test_capsule_validates_against_agent_capsule_contract() -> None:
    """The promotion-review capsule YAML must always validate, so it cannot silently drift.

    Review LOW finding: nothing previously checked this automatically.
    """
    import yaml

    from src.schemas.agent_package import AgentCapsuleContract

    capsule_path = (
        Path(__file__).resolve().parent.parent
        / "experiments"
        / "issue-27-handoff-verdict"
        / "capsule"
        / "process_capsule.yaml"
    )
    data = yaml.safe_load(capsule_path.read_text(encoding="utf-8"))
    capsule = AgentCapsuleContract.model_validate(data)
    assert capsule.maturity.value == "draft"
    assert capsule.depth_level == 0
