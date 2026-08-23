# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Turning what was discovered into something a person can read.

Two rules from the design govern every string produced here, and both are the
product's own doctrine turned on its own interface.

**State outputs, never judge them.** Five words a second is twice a fast
typist; whether that is slow depends on the task, and the person who knows the
task is the reader, not this program. So: figures with units, and no verdicts.

**Never assume who owns the work.** The person reading this may be an
administrator setting a machine up for somebody else. This runtime already
names a step's performer (``WorkflowStep.actor``), so copy saying "you" about
the work contradicts its own data. Say what happens to the *step* instead.

The one sentence of consequence this module emits — "likely to fail" — is
chosen because it is falsifiable: exceeding a model's context produces either
an error or silent truncation, and both fail the step.
"""

from dataclasses import dataclass, field

from src.schemas.node import InferenceNode, Provenance

#: Words per token for English prose. A rough but stable convention, used so a
#: reader who has never heard of a token still gets a figure they can act on.
#: The exact token count is always shown beside it.
WORDS_PER_TOKEN = 0.75

#: What each source reads as on screen.
_SOURCE_WORDS = {
    Provenance.DETECTED: "found it",
    Provenance.MEASURED: "measured",
    Provenance.DECLARED: "you told me",
    Provenance.UNKNOWN: "not sure",
}

#: Shown wherever a figure was never established. One phrase everywhere, so a
#: reader learns it once.
UNKNOWN = "not sure"


def source_label(source: Provenance) -> str:
    """The plain-words rendering of where a value came from."""
    return _SOURCE_WORDS[source]


def words_from_tokens(tokens: int) -> int:
    """Approximate English words in a token budget."""
    return int(tokens * WORDS_PER_TOKEN)


def _two_significant(value: int) -> int:
    """Round to two significant digits, so a figure reads as an estimate."""
    if value <= 0:
        return 0
    digits = len(str(value))
    if digits <= 2:
        return value
    factor = 10 ** (digits - 2)
    return round(value / factor) * factor


def human_words(tokens: int) -> str:
    """A token budget as an approximate word count."""
    if tokens <= 0:
        return UNKNOWN
    return f"about {_two_significant(words_from_tokens(tokens)):,} words"


def human_rate(tokens_per_second: float) -> str:
    """A generation rate as approximate words a second."""
    if tokens_per_second <= 0:
        return UNKNOWN
    words = _two_significant(round(tokens_per_second * WORDS_PER_TOKEN))
    return f"about {words:,} words a second"


def human_bytes(count: int) -> str:
    """Video memory in GB, always as a floor.

    An inference server reports what a *loaded* model committed, so a total was
    never established and claiming one would be false.
    """
    if count <= 0:
        return UNKNOWN
    return f"{count // 1_000_000_000} GB or more"


@dataclass
class SummaryRow:
    """One line of the panel: what it is, the figure, and where it came from."""

    label: str
    value: str
    source: str = ""


@dataclass
class Summary:
    """The panel: rows of figures, and at most one consequence."""

    rows: list[SummaryRow] = field(default_factory=list)
    consequence: str = ""


def summarise(nodes: list[InferenceNode]) -> Summary:
    """Describe what is available, and what follows arithmetically from it."""
    usable = [n for n in nodes if n.reachable]

    if not usable:
        return Summary(
            rows=[SummaryRow("Agent steps can run on", "nothing yet")],
            consequence=(
                "No step can be assigned to an agent. Capture, validation, "
                "promotion and export do not require a computer."
            ),
        )

    best_context = max(n.max_context_length for n in usable)
    fastest = max(n.host.tokens_per_second for n in usable)
    with_gpu = [n for n in usable if n.host.gpu_present is True]
    any_unknown_gpu = any(n.host.gpu_present is None for n in usable)

    if with_gpu:
        vram = max(n.host.vram_bytes for n in with_gpu)
        card = f"yes, on {with_gpu[0].label} — {human_bytes(vram)}"
    elif any_unknown_gpu:
        card = UNKNOWN
    else:
        card = "none detected"

    rows = [
        SummaryRow("Agent steps can run on", ", ".join(n.label for n in usable)),
        SummaryRow(
            "Longest input any model takes",
            f"{human_words(best_context)}   ({best_context:,} tokens)"
            if best_context
            else UNKNOWN,
        ),
        SummaryRow("Measured speed", human_rate(fastest)),
        SummaryRow("Graphics card", card),
    ]

    consequence = ""
    if best_context:
        words = _two_significant(words_from_tokens(best_context))
        consequence = (
            f"A step needing more than about {words:,} words of input is "
            f"likely to fail on these computers."
        )

    return Summary(rows=rows, consequence=consequence)
