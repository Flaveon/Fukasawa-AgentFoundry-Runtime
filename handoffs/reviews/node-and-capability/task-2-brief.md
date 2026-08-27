### Task 2: Unit conversion and the summary panel

Pure functions, no I/O. Built before discovery so the human layer exists to render into.

**Files:**
- Create: `src/nodes/__init__.py`, `src/nodes/summary.py`
- Test: `tests/test_node_summary.py`

**Interfaces:**
- Consumes: Task 1's `InferenceNode`, `HostCapability`, `ModelCapability`, `Provenance`.
- Produces: `words_from_tokens(tokens: int) -> int`, `human_words(tokens: int) -> str`, `human_rate(tokens_per_second: float) -> str`, `human_bytes(n: int) -> str`, `source_label(p: Provenance) -> str`, `SummaryRow(label: str, value: str, source: str)`, `summarise(nodes: list[InferenceNode]) -> Summary` where `Summary` has `.rows: list[SummaryRow]` and `.consequence: str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_node_summary.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""The human layer: figures with units, and one defensible consequence.

Spec sections 3.1.1 and 3.1.2 are the subject here. The product's own doctrine
is that a validator states what is wrong and lets a person judge; these tests
hold the same line for the environment screen.
"""

import pytest

from src.nodes.summary import (
    human_bytes,
    human_rate,
    human_words,
    source_label,
    summarise,
    words_from_tokens,
)
from src.schemas.node import (
    HostCapability,
    InferenceNode,
    ModelCapability,
    NodeKind,
    Provenance,
)

JUDGEMENT = ["slow", "fast", "good", "bad", "poor", "powerful", "weak",
             "adequate", "plenty", "enough", "limited", "decent"]
OWNERSHIP = ["stays with you", "your workflow", "your model", "your hardware",
             "off your hands", "my network"]
JARGON = ["provenance", "scope", "vram", "endpoint", "capability"]


def node(**kw) -> InferenceNode:
    """A reachable Ollama computer, overridable per test."""
    base = dict(node_id="home-pc", label="Home PC", kind=NodeKind.OLLAMA,
                url="http://localhost:11434", reachable=True,
                models=[ModelCapability(name="llama3.1:8b", context_length=8192)],
                host=HostCapability(gpu_present=True, vram_bytes=6_000_000_000,
                                    tokens_per_second=53.0))
    base.update(kw)
    return InferenceNode(**base)


class TestUnits:
    def test_tokens_become_words_at_three_quarters(self):
        assert words_from_tokens(8192) == 6144

    def test_word_figures_round_to_two_significant_digits(self):
        assert human_words(8192) == "about 6,100 words"
        assert human_words(131072) == "about 98,000 words"

    def test_zero_tokens_is_not_a_figure(self):
        assert human_words(0) == "not sure"

    def test_rate_is_words_a_second(self):
        assert human_rate(53.0) == "about 40 words a second"

    def test_unmeasured_rate_says_so(self):
        assert human_rate(0.0) == "not sure"

    def test_bytes_become_gb_and_never_claim_a_total(self):
        # An inference server reports what a LOADED model committed, so this is
        # a floor. Saying "6 GB" would claim a total nobody established.
        assert human_bytes(6_000_000_000) == "6 GB or more"

    def test_zero_bytes_is_not_a_figure(self):
        assert human_bytes(0) == "not sure"

    def test_sources_read_as_plain_words(self):
        assert source_label(Provenance.DETECTED) == "found it"
        assert source_label(Provenance.MEASURED) == "measured"
        assert source_label(Provenance.DECLARED) == "you told me"
        assert source_label(Provenance.UNKNOWN) == "not sure"


class TestSummary:
    def test_states_where_agent_steps_can_run(self):
        summary = summarise([node()])
        rows = {r.label: r.value for r in summary.rows}
        assert rows["Agent steps can run on"] == "Home PC"

    def test_states_the_longest_input_with_both_units(self):
        summary = summarise([node()])
        rows = {r.label: r.value for r in summary.rows}
        assert "about 6,100 words" in rows["Longest input any model takes"]
        assert "8,192 tokens" in rows["Longest input any model takes"]

    def test_the_consequence_is_defensible_and_falsifiable(self):
        summary = summarise([node()])
        assert summary.consequence == (
            "A step needing more than about 6,100 words of input is likely "
            "to fail on these computers."
        )

    def test_nothing_configured_states_what_the_program_does(self):
        summary = summarise([])
        rows = {r.label: r.value for r in summary.rows}
        assert rows["Agent steps can run on"] == "nothing yet"
        assert summary.consequence == (
            "No step can be assigned to an agent. Capture, validation, "
            "promotion and export do not require a computer."
        )

    def test_an_unreachable_computer_counts_as_nothing(self):
        summary = summarise([node(reachable=False)])
        assert "No step can be assigned" in summary.consequence

    def test_no_graphics_card_is_stated_not_predicted(self):
        summary = summarise([node(host=HostCapability(gpu_present=False))])
        rows = {r.label: r.value for r in summary.rows}
        assert rows["Graphics card"] == "none detected"
        assert "slow" not in summary.consequence.lower()

    def test_an_unobserved_graphics_card_is_not_sure_not_absent(self):
        # Present-but-unloaded and absent are different facts.
        summary = summarise([node(host=HostCapability(gpu_present=None))])
        rows = {r.label: r.value for r in summary.rows}
        assert rows["Graphics card"] == "not sure"

    def test_a_model_with_no_context_length_yields_no_consequence(self):
        summary = summarise([node(models=[ModelCapability(name="m")])])
        assert summary.consequence == ""


class TestCopyRules:
    """Sections 3.1.1 and 3.1.2, checked against every branch."""

    BRANCHES = [
        [],
        [node()],
        [node(reachable=False)],
        [node(host=HostCapability(gpu_present=False))],
        [node(host=HostCapability(gpu_present=None))],
        [node(models=[ModelCapability(name="m")])],
        [node(models=[ModelCapability(name="m", context_length=512)])],
    ]

    @pytest.mark.parametrize("nodes", BRANCHES)
    def test_no_branch_judges_the_hardware(self, nodes):
        text = self._render(nodes).lower()
        hits = [w for w in JUDGEMENT if w in text]
        assert not hits, f"verdict words in the panel: {hits} — state the figure instead"

    @pytest.mark.parametrize("nodes", BRANCHES)
    def test_no_branch_asserts_ownership(self, nodes):
        text = self._render(nodes).lower()
        hits = [w for w in OWNERSHIP if w in text]
        assert not hits, f"ownership assumed: {hits}"

    @pytest.mark.parametrize("nodes", BRANCHES)
    def test_no_branch_uses_jargon(self, nodes):
        text = self._render(nodes).lower()
        hits = [w for w in JARGON if w in text]
        assert not hits, f"jargon on screen: {hits}"

    @pytest.mark.parametrize("nodes", BRANCHES)
    def test_every_branch_still_states_a_figure(self, nodes):
        # The other half. A screen must not pass the rules by saying nothing.
        summary = summarise(nodes)
        assert summary.rows, "a branch rendered no rows at all"
        assert all(r.value for r in summary.rows), "a row has no value"

    def _render(self, nodes) -> str:
        summary = summarise(nodes)
        return " ".join(
            [f"{r.label} {r.value} {r.source}" for r in summary.rows]
            + [summary.consequence]
        )
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `.venv/bin/python -m pytest tests/test_node_summary.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.nodes'`

- [ ] **Step 3: Write the implementation**

```python
# src/nodes/__init__.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Inference computers: discovering them, storing them, describing them."""
```

```python
# src/nodes/summary.py
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
    words = _two_significant(int(tokens_per_second * WORDS_PER_TOKEN))
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
        SummaryRow("Fastest measured speed", human_rate(fastest)),
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
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `.venv/bin/python -m pytest tests/test_node_summary.py -q`
Expected: PASS, 36 tests (8 unit + 8 summary + 4 copy rules × 7 branches minus overlap; the exact count is whatever collects — every one must pass).

- [ ] **Step 5: Commit**

```bash
git add src/nodes/__init__.py src/nodes/summary.py tests/test_node_summary.py
git commit -m "feat: the human layer — figures with units, no verdicts"
```

---

