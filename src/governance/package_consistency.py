# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Package consistency check — Level 0, deterministic, no model, no network.

Issue #27: the Q2C content pipeline writes two documents per run that can
disagree about whether a package should ship. ``build_package_quality_report``
(private pipeline, not part of this repo) computes a deterministic verdict
(PASS/HOLD) from the actual generated files and writes it to
``quality-report.json``. ``build_duath_operator_handoff`` writes a separate,
operator-facing Markdown handoff whose "Shipping Decision" lines are derived
from deployment *scope*, not from that verdict — so the handoff can tell a
human to ship a run the deterministic gate held. See
``experiments/issue-27-handoff-verdict/PROTOCOL.md`` for the full evidence
and the owner's original, never-implemented intent for this exact gap
("Duath/Angela PASS cannot override deterministic blockers").

This module is the Level-0 fix: a pure function that compares the two
documents' claims for the *same run* and says whether they agree. It never
reads a file, never calls a model, never makes a network request, and never
writes anything. All I/O is the caller's responsibility; this module only
answers "given these two texts, do they contradict each other".

It is also, deliberately, never wrong in the permissive direction: if either
document cannot be read, is malformed, or is missing the specific fields
this check compares, the result is ABSTAIN, not CONSISTENT. A rule that
treats "I don't know" as "it's fine" is worse than no rule at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

#: Matches the handoff's "Angela verdict: <value>" line, case-insensitive,
#: wherever it appears in the text.
_ANGELA_LINE_RE = re.compile(r"^\s*angela verdict\s*:.*$", re.IGNORECASE | re.MULTILINE)

#: Matches the "## Shipping Decision" section header and everything up to
#: the next blank line (the handoff always separates sections with one).
_SHIPPING_SECTION_RE = re.compile(
    r"^##\s*shipping decision\s*$\n(.*?)(?:\n\s*\n|\Z)", re.IGNORECASE | re.MULTILINE | re.DOTALL
)

#: Matches one "- <label>: <value>" bullet line within that section.
_SHIPPING_LINE_RE = re.compile(r"^\s*-\s*([^:]+):\s*(.+?)\s*$")

#: A verdict value counts as "the handoff says PASS" only for an exact PASS
#: claim — NEEDS_REVISION, NEEDS REVISION, etc. are not a pass, even though
#: they contain no literal "FAIL" either. Boundaries section below explains
#: why this is intentionally narrow.
_ANGELA_PASS_RE = re.compile(r"\bpass\b", re.IGNORECASE)
_ANGELA_NOT_PASS_QUALIFIER_RE = re.compile(r"\b(needs|revision|fail)\w*\b", re.IGNORECASE)

#: The only verdict values the deterministic quality report is allowed to
#: carry. Anything else (missing key, unexpected value) is malformed.
_VALID_REPORT_VERDICTS = ("PASS", "HOLD")


class ConsistencyVerdict(str, Enum):
    """The three outcomes this check can reach. There is no fourth."""

    BLOCK = "BLOCK"
    """The handoff authorizes shipping (or claims an Angela PASS) for a run
    whose deterministic quality report says HOLD. Each contradicted line is
    named in ``ConsistencyResult.reasons``."""

    CONSISTENT = "CONSISTENT"
    """No contradiction was found between the two documents for this run."""

    ABSTAIN = "ABSTAIN"
    """A deterministic comparison could not be made — the quality report or
    the handoff is missing, unreadable, or malformed, or the handoff has
    none of the fields this check compares. This is never treated as a
    pass; see ``escalation_target``."""


@dataclass(frozen=True)
class ConsistencyResult:
    """The outcome of one ``check_package_consistency`` call.

    ``reasons`` names each contradicted line verbatim (for BLOCK) or the
    specific reason evidence was insufficient (for ABSTAIN). It is always
    non-empty for BLOCK and ABSTAIN, and always empty for CONSISTENT.
    """

    verdict: ConsistencyVerdict
    reasons: tuple[str, ...] = field(default_factory=tuple)
    escalation_target: Optional[str] = None
    """Who should resolve this. Always ``"human operator"`` when set (only
    set for ABSTAIN) — this check never names an agent or a model as an
    escalation target; it does not know which ones exist."""

    escalation_reason: Optional[str] = None
    """Plain-language reason for the escalation. Only set for ABSTAIN."""


def _extract_angela_line(handoff_text: str) -> Optional[str]:
    """Return the handoff's "Angela verdict:" line, verbatim, or None if absent."""
    match = _ANGELA_LINE_RE.search(handoff_text)
    return match.group(0).strip() if match else None


def _extract_shipping_lines(handoff_text: str) -> tuple[str, ...]:
    """Return the handoff's "## Shipping Decision" bullet lines, verbatim, or ()."""
    section = _SHIPPING_SECTION_RE.search(handoff_text)
    if not section:
        return ()
    lines = [line.strip() for line in section.group(1).splitlines() if line.strip()]
    return tuple(lines)


def _angela_line_claims_pass(angela_line: str) -> bool:
    """True only for an unqualified PASS claim (not NEEDS_REVISION, not FAIL)."""
    if _ANGELA_NOT_PASS_QUALIFIER_RE.search(angela_line):
        return False
    return bool(_ANGELA_PASS_RE.search(angela_line))


def _shipping_line_authorizes_ship(line: str) -> bool:
    """True if a "- <label>: <value>" line's VALUE starts with "ship".

    Deliberately checks only the parsed value, not the whole line — a value
    of "hold (ship once blockers fixed)" mentions "ship" in prose but its
    value is "hold", and must not be treated as an authorization to ship.
    """
    match = _SHIPPING_LINE_RE.match(line)
    if not match:
        return False
    value = match.group(2).strip()
    return value.lower().startswith("ship")


def _report_verdict(quality_report: Optional[dict[str, Any]]) -> Optional[str]:
    """Return the report's verdict if it is a readable dict with a valid verdict, else None."""
    if not isinstance(quality_report, dict):
        return None
    verdict = quality_report.get("verdict")
    if verdict not in _VALID_REPORT_VERDICTS:
        return None
    return verdict


def check_package_consistency(
    handoff_text: Optional[str],
    quality_report: Optional[dict[str, Any]],
) -> ConsistencyResult:
    """Compare one run's operator handoff against its deterministic quality report.

    Parameters:
        handoff_text: the full text of the Duath operator handoff Markdown
            file for this run, or ``None`` if the file does not exist, is
            empty, or could not be read. This function does not distinguish
            those three cases from each other — the caller owns all file
            I/O and must pass ``None`` for any of them.
        quality_report: the parsed ``quality-report.json`` dict for the SAME
            run, or ``None`` if the file does not exist, is empty, could not
            be parsed as JSON, or could not be read. As with ``handoff_text``,
            the caller owns I/O; a dict that parsed successfully but lacks a
            valid ``"verdict"`` key (e.g. truncated schema, unexpected value)
            is a normal, expected input here, not an error the caller must
            pre-filter.

    Returns:
        A ``ConsistencyResult``. Verdict is BLOCK only when the report says
        HOLD and the handoff contains an unqualified Angela PASS claim or
        any Shipping Decision line whose value authorizes shipping; CONSISTENT
        when a comparison was possible and found no such claim; ABSTAIN
        whenever the comparison itself could not be made. ABSTAIN is never
        collapsed into CONSISTENT — evidence that is missing is not evidence
        that everything is fine.

    What this function does NOT check (boundaries):
        * It never reads a file, calls a model, or makes a network request.
        * It does not evaluate WHY the report is HOLD (what blocker fired) —
          only whether the handoff's shipping claims contradict that HOLD.
        * It does not inspect the handoff's other sections (Bundle Contents,
          Tool Reality Check, Asset Follow-Up, Required Fixes) — only the
          "Angela verdict:" line and the "## Shipping Decision" bullets.
        * It does not flag a handoff that is MORE conservative than the
          report (e.g. a PASS report whose handoff says "hold" everywhere);
          only over-authorization against a HOLD report is in scope. A
          needlessly conservative handoff is a different, lower-severity
          problem than one that authorizes a held artifact to ship, and the
          plan this check implements ("Duath/Angela PASS cannot override
          deterministic blockers") is specifically about the latter.
        * It does not compare across different run_ids — matching the right
          handoff to the right quality report by run_id is the caller's job.
        * It does not retry, cache, or rate-limit — it is a pure function of
          its two arguments; calling it twice with the same inputs always
          returns an equal result.
    """
    report_verdict = _report_verdict(quality_report)
    if report_verdict is None:
        return ConsistencyResult(
            verdict=ConsistencyVerdict.ABSTAIN,
            reasons=("quality report is missing, unreadable, or has no valid 'verdict' field",),
            escalation_target="human operator",
            escalation_reason=(
                "cannot compare the handoff against a quality report that is absent or malformed; "
                "never treat an unreadable gate as a pass"
            ),
        )

    if handoff_text is None or not handoff_text.strip():
        return ConsistencyResult(
            verdict=ConsistencyVerdict.ABSTAIN,
            reasons=("operator handoff is missing, empty, or unreadable",),
            escalation_target="human operator",
            escalation_reason="no handoff text exists to compare against the quality report",
        )

    angela_line = _extract_angela_line(handoff_text)
    shipping_lines = _extract_shipping_lines(handoff_text)
    if angela_line is None and not shipping_lines:
        return ConsistencyResult(
            verdict=ConsistencyVerdict.ABSTAIN,
            reasons=(
                "handoff has neither an 'Angela verdict:' line nor a "
                "'## Shipping Decision' section to compare",
            ),
            escalation_target="human operator",
            escalation_reason="handoff is readable but missing the fields this check compares",
        )

    if report_verdict == "PASS":
        # Out of scope by design: a PASS report with an over-conservative
        # handoff is not a contradiction this check flags. See boundaries.
        return ConsistencyResult(verdict=ConsistencyVerdict.CONSISTENT)

    # report_verdict == "HOLD" from here on: look for any claim that
    # authorizes shipping anyway.
    reasons: list[str] = []
    if angela_line is not None and _angela_line_claims_pass(angela_line):
        reasons.append(f"handoff line '{angela_line}' claims PASS but quality report verdict is HOLD")
    for line in shipping_lines:
        if _shipping_line_authorizes_ship(line):
            reasons.append(f"handoff line '{line}' authorizes shipping but quality report verdict is HOLD")

    if reasons:
        return ConsistencyResult(verdict=ConsistencyVerdict.BLOCK, reasons=tuple(reasons))
    return ConsistencyResult(verdict=ConsistencyVerdict.CONSISTENT)
