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
("Duath/Angela PASS cannot override deterministic blockers"; "Delivery
notes cannot recommend publish for held artifacts").

This module is the Level-0 fix: a pure function that compares the two
documents' claims for the *same run* and says whether they agree. It never
reads a file, never calls a model, never makes a network request, and never
writes anything. All I/O is the caller's responsibility; this module only
answers "given these two texts, do they contradict each other".

v2 (this version) rewrites the parser to be ALLOWLIST-based and fail
CLOSED. An independent review of v1 found it failed OPEN: v1 only abstained
when the Angela line and the Shipping Decision section were BOTH entirely
absent; any other unparseable or adversarially-shaped input (a renamed
header, an unfamiliar bullet marker, a decorated value, a duplicate
section, a blank line splitting a section's bullets, a qualified PASS
claim, an UNKNOWN Angela verdict, ...) was silently read as "not ship" /
"not PASS" and returned CONSISTENT — exactly the answer this check must
never give when it cannot actually tell. v2 fixes this: every field this
check reads is matched against a narrow allowlist of exact shapes and
values; a field that LOOKS like an attempt at that shape but does not
match the allowlist is treated as unparseable, not as "absent" or "not
ship" — and unparseable is always ABSTAIN, never CONSISTENT. See
``experiments/issue-27-handoff-verdict/CANDIDATES.md`` for the full
decision log, including which adversarial inputs this was tested against.

It is also, deliberately, never wrong in the permissive direction: if
either document cannot be read, is malformed, or is missing or has
unparseable shapes for the specific fields this check compares, the result
is ABSTAIN, not CONSISTENT. A rule that treats "I don't know" as "it's
fine" is worse than no rule at all.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

#: The only verdict values the deterministic quality report is allowed to
#: carry. Anything else (missing key, unexpected value) is malformed.
_VALID_REPORT_VERDICTS = ("PASS", "HOLD")

#: The only Angela verdict VALUES this check recognizes. Anything else
#: (a qualifier like "PASSED", a parenthetical like "PASS (no revisions
#: needed)", a homoglyph, markup) is unparseable, not "not PASS".
_ALLOWED_ANGELA_VALUES = ("PASS", "NEEDS_REVISION", "FAIL", "UNKNOWN")

#: The only Shipping Decision bullet VALUES this check recognizes, compared
#: case-insensitively after trimming only leading/trailing whitespace — no
#: other transformation. A value that merely starts with "ship" but has
#: trailing content ("ship (after fix)"), decoration ("**ship**",
#: "`ship`"), or is a different word entirely ("publish") does not match.
_ALLOWED_SHIP_VALUES = ("ship", "hold", "do not ship")

#: Loose detectors: "does this text contain something that LOOKS LIKE an
#: attempt" at the Angela line / Shipping Decision section at all. Used
#: only to distinguish "genuinely absent" (neither loose detector fires —
#: nothing to compare, but also nothing contradicted) from "present but
#: unparseable" (the loose detector fires, the strict allowlist regex
#: below does not match — ABSTAIN, never read as absent).
_ANGELA_ATTEMPT_RE = re.compile(r"angela\s*verdict", re.IGNORECASE)
_SHIPPING_ATTEMPT_RE = re.compile(r"shipping\s*decision", re.IGNORECASE)

#: Strict allowlist: the ENTIRE line (after trimming whitespace) must be
#: exactly "Angela verdict: <TOKEN>" with no markup, no qualifier, no
#: parenthetical, no second sentence. Multiline so every line in the text
#: is checked independently.
_ANGELA_LINE_STRICT_RE = re.compile(
    r"^Angela verdict:[ \t]*([A-Za-z_]+)[ \t]*$", re.IGNORECASE | re.MULTILINE
)

#: Strict allowlist: the section header must be exactly "## Shipping
#: Decision" — no "###", no plural, no suffix, no decoration.
_SHIPPING_HEADER_STRICT_RE = re.compile(
    r"^##[ \t]+Shipping Decision[ \t]*$", re.IGNORECASE | re.MULTILINE
)

#: Marks the start of ANY level-2+ Markdown header, used to find where a
#: Shipping Decision section ends (the next header, or end of text).
_ANY_HEADER_RE = re.compile(r"^##[ \t]", re.MULTILINE)

#: Strict allowlist: one bullet line, "- <label>: <value>", exactly one
#: leading hyphen (not "*", not "1.", not an em dash with no colon).
_BULLET_STRICT_RE = re.compile(r"^-[ \t]+([^:\n]+):[ \t]*(.+?)[ \t]*$")

#: Splits a Shipping Decision section's body into paragraphs on a blank
#: line. More than one non-empty paragraph means the section's content is
#: split by a blank line — the caller must not read only the first part.
_BLANK_LINE_RE = re.compile(r"\n[ \t]*\n")


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
    the handoff is missing, unreadable, or malformed, or the handoff's
    relevant fields are missing, duplicated, or do not match this check's
    allowlisted shapes/values. This is never treated as a pass; see
    ``escalation_target``."""


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


def _normalize(text: str) -> str:
    """Normalize Unicode (NFKC) and line endings before any matching.

    NFKC resolves purely cosmetic Unicode variation — a non-breaking space
    between "Angela" and "verdict", a fullwidth Latin "ship" — to its plain
    ASCII equivalent, so those do not block recognizing an otherwise
    well-formed line. A genuine homoglyph (e.g. Cyrillic "Ѕ" in "Ѕhip",
    Cyrillic "Р" in "РASS") is NOT a compatibility variant of a Latin
    letter and NFKC does not touch it — it still fails the allowlist
    afterward, as it should. CRLF line endings are also normalized to LF
    so a stray "\\r" before a line's end does not make an otherwise valid
    line fail the strict regexes below.
    """
    normalized = unicodedata.normalize("NFKC", text)
    return normalized.replace("\r\n", "\n").replace("\r", "\n")


@dataclass(frozen=True)
class _FieldOutcome:
    """Result of trying to read one field (Angela line or Shipping section).

    Exactly one of ``value``/``values`` is populated when ``abstain_reason``
    is None and the field was attempted; both are empty when the field was
    never attempted (genuinely absent) and there is nothing to report.
    """

    attempted: bool
    abstain_reason: Optional[str] = None
    angela_value: Optional[str] = None
    shipping_values: tuple[tuple[str, str], ...] = field(default_factory=tuple)


def _read_angela_line(normalized_text: str) -> _FieldOutcome:
    """Read the handoff's Angela verdict line against the strict allowlist."""
    attempted = bool(_ANGELA_ATTEMPT_RE.search(normalized_text))
    if not attempted:
        return _FieldOutcome(attempted=False)

    matches = list(_ANGELA_LINE_STRICT_RE.finditer(normalized_text))
    if not matches:
        return _FieldOutcome(
            attempted=True,
            abstain_reason=(
                "an 'Angela verdict:' line exists but does not match the recognized "
                "shape ('Angela verdict: <PASS|NEEDS_REVISION|FAIL|UNKNOWN>', no markup "
                "or extra text)"
            ),
        )
    if len(matches) > 1:
        return _FieldOutcome(
            attempted=True,
            abstain_reason="more than one 'Angela verdict:' line was found",
        )

    token = matches[0].group(1).upper()
    if token not in _ALLOWED_ANGELA_VALUES:
        return _FieldOutcome(
            attempted=True,
            abstain_reason=f"Angela verdict value '{token}' is not a recognized value",
        )
    if token == "UNKNOWN":
        return _FieldOutcome(
            attempted=True,
            abstain_reason="Angela verdict is UNKNOWN",
        )
    return _FieldOutcome(attempted=True, angela_value=token)


def _read_shipping_section(normalized_text: str) -> _FieldOutcome:
    """Read the handoff's Shipping Decision section against the strict allowlist."""
    attempted = bool(_SHIPPING_ATTEMPT_RE.search(normalized_text))
    if not attempted:
        return _FieldOutcome(attempted=False)

    headers = list(_SHIPPING_HEADER_STRICT_RE.finditer(normalized_text))
    if not headers:
        return _FieldOutcome(
            attempted=True,
            abstain_reason=(
                "a 'Shipping Decision' section exists but its header does not match "
                "the recognized shape ('## Shipping Decision', exactly)"
            ),
        )
    if len(headers) > 1:
        return _FieldOutcome(
            attempted=True,
            abstain_reason="more than one 'Shipping Decision' section was found",
        )

    header = headers[0]
    rest = normalized_text[header.end():]
    next_header = _ANY_HEADER_RE.search(rest)
    section_body = rest[: next_header.start()] if next_header else rest
    section_body = section_body.lstrip("\n")

    paragraphs = [p for p in _BLANK_LINE_RE.split(section_body) if p.strip()]
    if not paragraphs:
        return _FieldOutcome(
            attempted=True,
            abstain_reason="the 'Shipping Decision' section has no bullet lines",
        )
    if len(paragraphs) > 1:
        return _FieldOutcome(
            attempted=True,
            abstain_reason=(
                "the 'Shipping Decision' section's bullets are split by a blank line "
                "before more content follows — refusing to read only the first part"
            ),
        )

    lines = [line.strip() for line in paragraphs[0].splitlines() if line.strip()]
    parsed: list[tuple[str, str]] = []
    for line in lines:
        match = _BULLET_STRICT_RE.match(line)
        if not match:
            return _FieldOutcome(
                attempted=True,
                abstain_reason=(
                    f"the 'Shipping Decision' section contains a line that does not "
                    f"match the recognized bullet shape ('- <label>: <value>'): '{line}'"
                ),
            )
        label, value = match.group(1).strip(), match.group(2).strip()
        if value.lower() not in _ALLOWED_SHIP_VALUES:
            return _FieldOutcome(
                attempted=True,
                abstain_reason=(
                    f"the 'Shipping Decision' line '{line}' has a value that is not "
                    f"one of the recognized values (ship / hold / do not ship)"
                ),
            )
        parsed.append((label, value.lower()))

    return _FieldOutcome(attempted=True, shipping_values=tuple(parsed))


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
            pre-filter. A ``"findings"`` key (the real pipeline's shape, a
            list) or else a ``"finding_counts"`` key (this repo's sanitized
            dataset shape, a dict) is read only to detect a PASS report
            that still lists findings (see below) — everything else in the
            dict is ignored.

    Returns:
        A ``ConsistencyResult``. Verdict is BLOCK only when the report says
        HOLD and the handoff contains a recognized, unqualified Angela PASS
        claim or a recognized Shipping Decision line whose value is exactly
        "ship"; CONSISTENT when a full comparison was possible and found no
        such claim; ABSTAIN whenever the comparison itself could not be
        made — including when a field exists but does not match this
        check's allowlist of recognized shapes and values. ABSTAIN is
        never collapsed into CONSISTENT: a field this check cannot
        confidently read is treated as evidence that the check could not
        be performed, not as evidence that nothing is wrong. This is the
        core correction from v1 (see module docstring): a document that
        LOOKS unlike what this check expects is never silently treated as
        "not ship" / "not PASS".

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
        * It is a RUN-level check: it does not evaluate whether individual
          *artifacts* within a run should ship — the owner's plan language
          ("held artifacts") is per-artifact, and this check is coarser
          than that by design (Level 0). A future, finer-grained check is
          a separate, larger piece of work, not this one.
        * It does not compare across different run_ids — matching the right
          handoff to the right quality report by run_id is the caller's job.
        * It does not retry, cache, or rate-limit — it is a pure function of
          its two arguments; calling it twice with the same inputs always
          returns an equal result.
        * ``handoff_text`` and ``quality_report`` are expected to be ``str``
          and ``dict`` (or ``None``) respectively. Other types are not a
          supported input: a ``bytes`` handoff_text will raise ``TypeError``
          from the regex engine, and a non-dict, non-``None`` quality_report
          other than a ``dict`` is treated as malformed (``_report_verdict``
          returns ``None``) rather than raising. Callers must decode bytes
          and parse JSON before calling this function.
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

    normalized_text = _normalize(handoff_text)
    angela = _read_angela_line(normalized_text)
    shipping = _read_shipping_section(normalized_text)

    if not angela.attempted and not shipping.attempted:
        return ConsistencyResult(
            verdict=ConsistencyVerdict.ABSTAIN,
            reasons=(
                "handoff has neither an 'Angela verdict:' line nor a "
                "'## Shipping Decision' section to compare",
            ),
            escalation_target="human operator",
            escalation_reason="handoff is readable but missing the fields this check compares",
        )

    abstain_reasons = [r for r in (angela.abstain_reason, shipping.abstain_reason) if r]

    if report_verdict == "HOLD":
        # BLOCK takes priority over ABSTAIN: a field that resolved cleanly
        # to a recognized blocking value (Angela PASS, or a ship line) is
        # acted on immediately, even if the OTHER field is separately
        # unparseable. A document that is partly garbled but still
        # contains an unambiguous "ship this" claim must not have that
        # claim buried under an ABSTAIN just because something else on the
        # page didn't parse — missing a clear, already-in-hand escape is
        # worse than flagging it alongside a note that something else on
        # the page needs a human's eyes too. See CANDIDATES.md.
        block_reasons: list[str] = []
        if angela.angela_value == "PASS":
            block_reasons.append("handoff's Angela verdict is PASS but quality report verdict is HOLD")
        for label, value in shipping.shipping_values:
            if value == "ship":
                block_reasons.append(
                    f"handoff line '{label}: {value}' authorizes shipping but quality report verdict is HOLD"
                )
        if block_reasons:
            return ConsistencyResult(verdict=ConsistencyVerdict.BLOCK, reasons=tuple(block_reasons))

    if abstain_reasons:
        return ConsistencyResult(
            verdict=ConsistencyVerdict.ABSTAIN,
            reasons=tuple(abstain_reasons),
            escalation_target="human operator",
            escalation_reason=(
                "a field this check compares is present but does not match a recognized "
                "shape or value; an unrecognized shape is never read as 'not ship'"
            ),
        )

    if report_verdict == "PASS":
        # The real pipeline's quality-report.json carries findings as a
        # list under "findings"; this repo's sanitized dataset reduces that
        # to a dict of counts under "finding_counts" (see extract.py). A
        # caller may hand either shape — prefer "findings" (the real,
        # unreduced shape) when both happen to be present.
        findings = quality_report.get("findings") if isinstance(quality_report, dict) else None
        if findings is None and isinstance(quality_report, dict):
            findings = quality_report.get("finding_counts")
        if findings:
            return ConsistencyResult(
                verdict=ConsistencyVerdict.ABSTAIN,
                reasons=(
                    f"quality report verdict is PASS but still lists findings ({findings}) "
                    "— the report is internally inconsistent",
                ),
                escalation_target="human operator",
                escalation_reason="a PASS verdict with recorded findings cannot be trusted at face value",
            )
        # Out of scope by design: a PASS report with an over-conservative
        # handoff is not a contradiction this check flags. See boundaries.
        return ConsistencyResult(verdict=ConsistencyVerdict.CONSISTENT)

    # report_verdict == "HOLD", no block_reasons were found above, and
    # neither field was unparseable (abstain_reasons is empty, or this
    # point would not have been reached) -- both fields are either absent
    # or resolved to a non-blocking value.
    return ConsistencyResult(verdict=ConsistencyVerdict.CONSISTENT)
