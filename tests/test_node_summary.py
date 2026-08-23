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
