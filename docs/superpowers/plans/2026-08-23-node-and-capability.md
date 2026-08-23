# Node and Capability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a person who did not write this software tell it what inference hardware they have — by asking permission, discovering what it can, and presenting every field for confirmation or edit.

**Architecture:** A new top-level `src/nodes/` package holds contracts-adjacent logic: two backend probes, a consent-gated scanner that **yields events as it learns things**, a YAML store, and a deterministic human-summary layer. The CLI and the desktop are two renderers over the same event stream. The existing `ModelEndpointRegistry` is consumed unchanged by injecting a merged mapping into it.

**Tech Stack:** Python 3.12, Pydantic v2, Typer, Rich, CustomTkinter, PyYAML, pytest. Standard-library `urllib` for HTTP — no new dependency.

**Spec:** `docs/superpowers/specs/2026-08-23-node-and-capability-design.md`. Where this plan and the spec disagree, the spec wins.

## Global Constraints

Every task's requirements implicitly include all of these.

- **No new runtime dependency.** `urllib.request` only. Adding to `pyproject.toml` dependencies is out of scope.
- **FROZEN paths must not be touched:** `src/schemas/graph.py`, `src/schemas/bundle.py`, `src/kernel/*`, `src/security/*`, `src/foundry/generator.py`, `src/runtime/state_machine.py`, `src/runtime/bundle.py`. `.github/workflows/frozen-paths.yml` fails the PR otherwise. **Nothing in this plan needs them.**
- **Every source file starts with:**
  ```python
  # SPDX-License-Identifier: AGPL-3.0-or-later
  # Copyright (C) 2026 ConcordiaPax LLC
  ```
- **Every function has a docstring. Every Pydantic field has a `description=`.** House rule; the suite does not enforce it but review does.
- **Contracts use** `model_config = ConfigDict(extra="forbid")` and `SCHEMA_VERSION = "1"`.
- **Slug pattern**, copied verbatim from `src/schemas/human_workflow.py`: `r"^[a-z0-9]+(-[a-z0-9]+)*$"`
- **Copy rule §3.1.1 — state outputs, never judge them.** No user-facing string contains: *slow*, *fast*, *good*, *bad*, *poor*, *powerful*, *weak*, *adequate*, *plenty*, *enough*, *limited*, *decent*.
- **Copy rule §3.1.2 — never assume who owns the work.** No user-facing string contains: *stays with you*, *your workflow*, *your model*, *your hardware*, *off your hands*, *my network*. Second person only for the reader's own choice or input.
- **Copy rule §3.1 — vocabulary.** No user-facing *sentence* contains *endpoint*, *provenance*, *scope*, *capability*, *VRAM*, or a bare *token*. `node` is permitted only as a CLI command noun (`fukasawa node scan`).
- **Views may import only** `src.gui.services`, sibling views, stdlib and `customtkinter`. Services import no widget library and never `print`. Enforced by `tests/test_gui_workflow.py::TestImportLaw`, which discovers files by glob.
- **Run the suite both ways.** `xvfb-run -a .venv/bin/python -m pytest -q` and `.venv/bin/python -m pytest -q`. The plain run skips ~40 display-gated tests.
- **Baseline at plan start:** 712 passed, 1 skipped (xvfb) / 672 passed, 41 skipped (no display).

---

### Task 1: Node contracts

**Files:**
- Create: `src/schemas/node.py`
- Test: `tests/test_node_contracts.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ScanScope`, `Provenance`, `NodeKind`, `ModelCapability`, `HostCapability`, `InferenceNode`, `ScanConsent`, `SCHEMA_VERSION`, `slugify(label: str) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_node_contracts.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Contracts for an inference node and what it can do."""

import pytest
from pydantic import ValidationError

from src.schemas.node import (
    SCHEMA_VERSION,
    HostCapability,
    InferenceNode,
    ModelCapability,
    NodeKind,
    Provenance,
    ScanConsent,
    ScanScope,
    slugify,
)


class TestSlug:
    @pytest.mark.parametrize(
        "label,expected",
        [
            ("Home PC", "home-pc"),
            ("  Studio   Mac  ", "studio-mac"),
            ("GPU box #2", "gpu-box-2"),
            ("Ollama", "ollama"),
        ],
    )
    def test_labels_become_slugs(self, label, expected):
        assert slugify(label) == expected

    def test_a_label_with_nothing_usable_falls_back(self):
        # An id is required, so an unusable label must still yield one rather
        # than an empty string that fails validation later.
        assert slugify("!!!") == "computer"


class TestInferenceNode:
    def test_minimal_node_is_valid(self):
        node = InferenceNode(node_id="home-pc", label="Home PC",
                             kind=NodeKind.OLLAMA, url="http://localhost:11434")
        assert node.schema_version == SCHEMA_VERSION
        assert node.reachable is False
        assert node.models == []
        assert node.host.gpu_present is None

    def test_node_id_must_be_a_slug(self):
        with pytest.raises(ValidationError):
            InferenceNode(node_id="Home PC", label="x",
                          kind=NodeKind.OLLAMA, url="http://h")

    def test_unknown_field_is_refused_by_name(self):
        with pytest.raises(ValidationError) as exc:
            InferenceNode(node_id="a", label="x", kind=NodeKind.OLLAMA,
                          url="http://h", speed="fast")
        assert "speed" in str(exc.value)

    def test_round_trips_through_json(self):
        node = InferenceNode(
            node_id="home-pc", label="Home PC", kind=NodeKind.OLLAMA,
            url="http://localhost:11434", reachable=True,
            models=[ModelCapability(name="llama3.1:8b", context_length=8192)],
            host=HostCapability(gpu_present=True, vram_bytes=6_000_000_000),
            provenance={"models": Provenance.DETECTED},
        )
        again = InferenceNode.model_validate(node.model_dump(mode="json"))
        assert again == node

    def test_source_of_reports_unknown_for_unrecorded_fields(self):
        node = InferenceNode(node_id="a", label="x", kind=NodeKind.OLLAMA,
                             url="http://h",
                             provenance={"label": Provenance.DECLARED})
        assert node.source_of("label") is Provenance.DECLARED
        assert node.source_of("host.vram_bytes") is Provenance.UNKNOWN


class TestConsent:
    def test_defaults_to_no_scanning(self):
        # The safe default: nothing is scanned until somebody says so.
        assert ScanConsent().scope is ScanScope.NONE

    def test_records_who_and_when(self):
        consent = ScanConsent(scope=ScanScope.THIS_MACHINE, granted_by="sam")
        assert consent.granted_by == "sam"
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `.venv/bin/python -m pytest tests/test_node_contracts.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.schemas.node'`

- [ ] **Step 3: Write the implementation**

```python
# src/schemas/node.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""What an inference computer is, and what is known about it.

A person handed this product runs their own hardware, so the runtime has to
learn what they have from them. These contracts hold that knowledge, and one
field of them is unusual enough to call out: ``provenance`` records *where
each value came from* — read from the machine, measured with a clock, or typed
by a person. The screens show it, because a reader needs to know which rows to
check.

Values are flat with a separate ``provenance`` map rather than each value
wrapped in ``{value, source}``. These files are hand-editable and the wrapped
form doubles their depth.
"""

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

#: Reject unknown fields so a typo surfaces loudly rather than being ignored.
STRICT = ConfigDict(extra="forbid")

#: Slug pattern, matching the rest of the repository's identifiers.
SLUG = r"^[a-z0-9]+(-[a-z0-9]+)*$"

#: Contract version for this module. Additive within a major version.
SCHEMA_VERSION = "1"


class ScanScope(str, Enum):
    """How far a person has permitted the scan to reach.

    NONE          — nothing is scanned; no socket is opened at all.
    THIS_MACHINE  — loopback ports, plus this computer's own CPU/RAM/OS.
    NAMED_HOST    — exactly one address, given by the person.
    LOCAL_NETWORK — the primary interface's /24, two known ports.
    """

    NONE = "NONE"
    THIS_MACHINE = "THIS_MACHINE"
    NAMED_HOST = "NAMED_HOST"
    LOCAL_NETWORK = "LOCAL_NETWORK"


class Provenance(str, Enum):
    """Where a value came from. Rendered in plain words on screen."""

    DETECTED = "DETECTED"   # read from the machine's own API
    MEASURED = "MEASURED"   # timed with a clock
    DECLARED = "DECLARED"   # a person typed it
    UNKNOWN = "UNKNOWN"     # nobody has said


class NodeKind(str, Enum):
    """Which inference server is answering."""

    OLLAMA = "ollama"
    LLAMACPP = "llamacpp"


def slugify(label: str) -> str:
    """Turn a human label into a stable identifier.

    Falls back to ``computer`` when a label contains nothing usable, because an
    id is required and an empty string would fail validation somewhere less
    obvious.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", label.strip().lower()).strip("-")
    return slug or "computer"


class ModelCapability(BaseModel):
    """One model an inference computer can serve."""

    model_config = STRICT

    name: str = Field(description="Model identifier, e.g. 'llama3.1:8b'.")
    family: str = Field(default="", description="Model family, e.g. 'llama'.")
    parameter_size: str = Field(
        default="", description="Parameter count as reported, e.g. '8.0B'."
    )
    quantization: str = Field(
        default="", description="Quantisation as reported, e.g. 'Q4_K_M'."
    )
    context_length: int = Field(
        default=0,
        description="Longest input in tokens. 0 means it was not established.",
    )
    supports_tools: bool = Field(
        default=False, description="Whether the model accepts tool definitions."
    )
    supports_vision: bool = Field(
        default=False, description="Whether the model accepts images."
    )
    size_bytes: int = Field(
        default=0, description="On-disk size as reported. 0 means unknown."
    )


class HostCapability(BaseModel):
    """What is known about the machine behind the server.

    ``vram_bytes`` is a **floor, never a total**: an inference server reports
    what a *currently loaded* model committed, so nothing loaded reads as zero
    and that does not mean there is no graphics card. ``gpu_present`` is a true
    tri-state for the same reason.
    """

    model_config = STRICT

    gpu_present: Optional[bool] = Field(
        default=None,
        description=(
            "True when committed video memory was observed, False only when a "
            "backend positively reports no offload, None when unestablished."
        ),
    )
    vram_bytes: int = Field(
        default=0,
        description="Video memory observed in use. A floor, not a total.",
    )
    cpu_count: int = Field(
        default=0, description="Processor count. Local scans only."
    )
    ram_bytes: int = Field(
        default=0, description="System memory. Local scans only."
    )
    platform: str = Field(
        default="", description="Operating system string. Local scans only."
    )
    tokens_per_second: float = Field(
        default=0.0, description="Generation rate, measured. 0.0 means unmeasured."
    )
    latency_ms: float = Field(
        default=0.0, description="Round-trip time to the server, measured."
    )


class InferenceNode(BaseModel):
    """One inference computer and everything known about it."""

    model_config = STRICT

    schema_version: str = Field(
        default=SCHEMA_VERSION, description="Contract version this was written against."
    )
    node_id: str = Field(
        pattern=SLUG, description="Stable identifier, unique within the store."
    )
    label: str = Field(description="What the person calls this computer.")
    kind: NodeKind = Field(description="Which inference server answers here.")
    url: str = Field(description="Base URL the server answers on.")
    is_local: bool = Field(
        default=False, description="Whether this is the machine Fukasawa runs on."
    )
    reachable: bool = Field(
        default=False, description="Whether it answered the last time it was tried."
    )
    backend_version: str = Field(
        default="", description="Server version as reported."
    )
    models: list[ModelCapability] = Field(
        default_factory=list, description="Models this computer can serve."
    )
    host: HostCapability = Field(
        default_factory=HostCapability, description="What is known about the machine."
    )
    provenance: dict[str, Provenance] = Field(
        default_factory=dict,
        description=(
            "Where each value came from, keyed by dotted field path such as "
            "'host.vram_bytes'. A missing key means UNKNOWN."
        ),
    )
    last_probed_at: Optional[datetime] = Field(
        default=None, description="When this computer was last examined (UTC)."
    )
    notes: str = Field(default="", description="Anything else worth recording.")

    def source_of(self, field_path: str) -> Provenance:
        """Where one value came from. UNKNOWN when nothing was recorded."""
        return self.provenance.get(field_path, Provenance.UNKNOWN)

    @property
    def max_context_length(self) -> int:
        """Longest input any model here accepts, in tokens. 0 if unestablished."""
        return max((m.context_length for m in self.models), default=0)


class ScanConsent(BaseModel):
    """A person's standing permission for how far a scan may reach.

    Defaults to NONE: nothing is examined until somebody says so. Attribution
    is self-attested, as everywhere else in this runtime — there is no
    authentication.
    """

    model_config = STRICT

    schema_version: str = Field(
        default=SCHEMA_VERSION, description="Contract version."
    )
    scope: ScanScope = Field(
        default=ScanScope.NONE, description="How far a scan may reach."
    )
    granted_by: str = Field(
        default="", description="Who granted it (self-attested)."
    )
    granted_at: Optional[datetime] = Field(
        default=None, description="When it was granted (UTC)."
    )

    @classmethod
    def granted(cls, scope: ScanScope, by: str) -> "ScanConsent":
        """Record a grant made now."""
        return cls(scope=scope, granted_by=by, granted_at=datetime.now(timezone.utc))
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `.venv/bin/python -m pytest tests/test_node_contracts.py -q`
Expected: PASS, 11 tests.

- [ ] **Step 5: Commit**

```bash
git add src/schemas/node.py tests/test_node_contracts.py
git commit -m "feat: contracts for inference computers and what they can do"
```

---

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

### Task 3: Backend probes

The only new module that touches the network. Pure functions over an injected fetcher, so no test needs a live server.

**Files:**
- Create: `src/nodes/backends.py`
- Test: `tests/test_node_backends.py`

**Interfaces:**
- Consumes: Task 1's contracts.
- Produces: `Fetcher` (`Callable[[str, float], dict]`), `Poster` (`Callable[[str, dict, float], dict]`), `http_get_json(url, timeout) -> dict`, `http_post_json(url, payload, timeout) -> dict`, `probe_ollama(base_url, fetch, post) -> ProbeResult`, `probe_llamacpp(base_url, fetch) -> ProbeResult`, `ProbeResult(kind, backend_version, models, host, ok, note)`, `PORTS = ((11434, NodeKind.OLLAMA), (8081, NodeKind.LLAMACPP))`.

> **Ollama's `/api/show` is a POST with a JSON body**, not a GET with a query
> string. The probe therefore takes an injected `post` alongside `fetch`,
> mirroring the `Poster` the kernel already defines. A GET-only probe passes
> against a fake and fails against a real server — exactly the class of bug a
> test with a hand-written fake will not catch, so the shape is specified here.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_node_backends.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Reading an inference server's own metadata.

The design's key decision is tested here: hardware facts come from the SERVER,
not from the model. A model does not know what it is running on and would
confabulate; the server reports exactly what it committed.

Every test injects a fake fetcher, so no live server is required and no socket
is opened.
"""

import pytest

from src.nodes.backends import PORTS, probe_llamacpp, probe_ollama
from src.schemas.node import NodeKind

OLLAMA_TAGS = {
    "models": [
        {"name": "llama3.1:8b", "size": 4_700_000_000,
         "details": {"family": "llama", "parameter_size": "8.0B",
                     "quantization_level": "Q4_K_M"}},
        {"name": "phi3:mini", "size": 2_200_000_000,
         "details": {"family": "phi3", "parameter_size": "3.8B",
                     "quantization_level": "Q4_0"}},
    ]
}
OLLAMA_SHOW = {
    "model_info": {"llama.context_length": 8192},
    "capabilities": ["completion", "tools"],
}
OLLAMA_PS = {"models": [{"name": "llama3.1:8b", "size": 4_700_000_000,
                         "size_vram": 4_700_000_000}]}


def ollama_fetch(url, timeout=0.0):
    """Answer GETs like an Ollama server."""
    if url.endswith("/api/version"):
        return {"version": "0.5.4"}
    if url.endswith("/api/tags"):
        return OLLAMA_TAGS
    if url.endswith("/api/ps"):
        return OLLAMA_PS
    raise AssertionError(f"unexpected GET {url}")


def ollama_post(url, payload, timeout=0.0):
    """Answer POSTs like an Ollama server. /api/show is a POST."""
    if url.endswith("/api/show"):
        assert "name" in payload, "/api/show needs the model name in the body"
        return OLLAMA_SHOW
    raise AssertionError(f"unexpected POST {url}")


class TestOllama:
    def test_reads_version_models_and_context(self):
        result = probe_ollama("http://h:11434", ollama_fetch, ollama_post)
        assert result.ok
        assert result.kind is NodeKind.OLLAMA
        assert result.backend_version == "0.5.4"
        assert [m.name for m in result.models] == ["llama3.1:8b", "phi3:mini"]
        assert result.models[0].context_length == 8192
        assert result.models[0].quantization == "Q4_K_M"

    def test_tool_support_is_read_not_guessed(self):
        result = probe_ollama("http://h:11434", ollama_fetch, ollama_post)
        assert result.models[0].supports_tools is True
        assert result.models[0].supports_vision is False

    def test_committed_video_memory_proves_a_graphics_card(self):
        result = probe_ollama("http://h:11434", ollama_fetch, ollama_post)
        assert result.host.gpu_present is True
        assert result.host.vram_bytes == 4_700_000_000

    def test_nothing_loaded_leaves_the_card_unestablished(self):
        # size_vram of 0 does NOT mean there is no card — nothing was loaded.
        def fetch(url, timeout=0.0):
            if url.endswith("/api/ps"):
                return {"models": []}
            return ollama_fetch(url, timeout)

        result = probe_ollama("http://h:11434", fetch, ollama_post)
        assert result.host.gpu_present is None, "absent and unobserved are different"

    def test_an_unreachable_server_is_not_ok(self):
        def fetch(url, timeout=0.0):
            raise OSError("connection refused")

        result = probe_ollama("http://h:11434", fetch, ollama_post)
        assert not result.ok
        assert "connection refused" in result.note

    def test_a_failed_model_list_still_yields_a_reachable_server(self):
        def fetch(url, timeout=0.0):
            if url.endswith("/api/tags"):
                raise OSError("boom")
            return ollama_fetch(url, timeout)

        result = probe_ollama("http://h:11434", fetch, ollama_post)
        assert result.ok, "a listing failure must not discard the whole probe"
        assert result.models == []


class TestLlamaCpp:
    def test_reads_context_and_offload(self):
        def fetch(url, timeout=0.0):
            if url.endswith("/health"):
                return {"status": "ok"}
            if url.endswith("/props"):
                return {"default_generation_settings": {"n_ctx": 4096},
                        "model_path": "/models/q4.gguf"}
            if url.endswith("/v1/models"):
                return {"data": [{"id": "q4.gguf"}]}
            raise AssertionError(url)

        result = probe_llamacpp("http://h:8081", fetch)
        assert result.ok
        assert result.kind is NodeKind.LLAMACPP
        assert result.models[0].context_length == 4096


class TestPorts:
    def test_the_two_known_ports_are_declared_once(self):
        assert PORTS == ((11434, NodeKind.OLLAMA), (8081, NodeKind.LLAMACPP))
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `.venv/bin/python -m pytest tests/test_node_backends.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.nodes.backends'`

- [ ] **Step 3: Write the implementation**

```python
# src/nodes/backends.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Reading what an inference server says about itself.

**This module is the only new place in the runtime that opens a socket**, and
it is deliberately narrow. It is config-time, it runs only after a person has
granted permission, and it is not on any authoritative path — validation,
promotion, classification and export never reach it.

The design decision this module embodies: hardware facts come from the
**server**, never from the model. A language model does not know what it is
running on, and asked about its own graphics card it will produce a confident,
plausible, wrong answer. The server knows exactly, and says so for free.

Every function takes an injected ``fetch``, so tests describe a backend's API
shape without a live server and without a socket.
"""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

from src.schemas.node import HostCapability, ModelCapability, NodeKind

#: A fetcher takes (url, timeout) and returns decoded JSON from a GET.
Fetcher = Callable[[str, float], dict]

#: A poster takes (url, payload, timeout) and returns decoded JSON from a POST.
#: Named to match the kernel's existing alias, because it is the same idea.
Poster = Callable[[str, dict, float], dict]

#: The ports each backend conventionally answers on. One declaration, so the
#: scanner and the tests cannot disagree about what is worth trying.
PORTS: tuple[tuple[int, NodeKind], ...] = (
    (11434, NodeKind.OLLAMA),
    (8081, NodeKind.LLAMACPP),
)

#: Models examined in detail per server, so one machine with a large library
#: cannot make a scan run unboundedly long.
MAX_MODELS_EXAMINED = 12


def http_get_json(url: str, timeout: float = 5.0) -> dict:
    """GET a URL and decode JSON. Raises OSError on any failure."""
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    return _send(request, timeout)


def http_post_json(url: str, payload: dict, timeout: float = 10.0) -> dict:
    """POST a JSON body and decode the JSON reply. Raises OSError on failure."""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return _send(request, timeout)


def _send(request: urllib.request.Request, timeout: float) -> dict:
    """Send a prepared request, normalising every failure to OSError.

    One exception type out means callers degrade one stage rather than
    enumerating urllib's error taxonomy at six call sites.
    """
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, ValueError, TimeoutError) as exc:
        raise OSError(str(exc)) from exc


@dataclass
class ProbeResult:
    """What one server reported about itself."""

    kind: NodeKind
    ok: bool = False
    backend_version: str = ""
    models: list[ModelCapability] = field(default_factory=list)
    host: HostCapability = field(default_factory=HostCapability)
    note: str = ""


def probe_ollama(
    base_url: str,
    fetch: Fetcher = http_get_json,
    post: "Poster" = None,  # type: ignore[assignment]  # defaulted below
) -> ProbeResult:
    """Ask an Ollama server what it is and what it can do.

    A failure after the first reachability check degrades that one fact rather
    than the whole probe: a server that answers but cannot list its models is
    still a server worth recording.
    """
    post = post or http_post_json
    result = ProbeResult(kind=NodeKind.OLLAMA)
    try:
        version = fetch(f"{base_url}/api/version", 5.0)
    except OSError as exc:
        result.note = str(exc)
        return result

    result.ok = True
    result.backend_version = str(version.get("version", ""))

    try:
        listing = fetch(f"{base_url}/api/tags", 10.0)
    except OSError as exc:
        result.note = f"could not list the models: {exc}"
        listing = {"models": []}

    for entry in listing.get("models", [])[:MAX_MODELS_EXAMINED]:
        details = entry.get("details", {})
        result.models.append(
            ModelCapability(
                name=entry.get("name", ""),
                family=details.get("family", ""),
                parameter_size=details.get("parameter_size", ""),
                quantization=details.get("quantization_level", ""),
                size_bytes=int(entry.get("size", 0)),
            )
        )

    for model in result.models:
        try:
            # A POST with the name in the body — Ollama's /api/show is not a GET.
            shown = post(f"{base_url}/api/show", {"name": model.name}, 10.0)
        except OSError:
            continue
        info = shown.get("model_info", {})
        for key, value in info.items():
            if key.endswith(".context_length"):
                model.context_length = int(value)
                break
        capabilities = shown.get("capabilities", [])
        model.supports_tools = "tools" in capabilities
        model.supports_vision = "vision" in capabilities

    # A loaded model's committed video memory is the one hardware fact this API
    # gives away. Nothing loaded means nothing observed -- which is NOT the same
    # as no graphics card, so gpu_present stays None.
    try:
        running = fetch(f"{base_url}/api/ps", 5.0)
        loaded = running.get("models", [])
        vram = max((int(m.get("size_vram", 0)) for m in loaded), default=0)
        if vram > 0:
            result.host.gpu_present = True
            result.host.vram_bytes = vram
    except OSError:
        pass

    return result


def probe_llamacpp(base_url: str, fetch: Fetcher = http_get_json) -> ProbeResult:
    """Ask a llama.cpp server what it is and what it can do."""
    result = ProbeResult(kind=NodeKind.LLAMACPP)
    try:
        fetch(f"{base_url}/health", 5.0)
    except OSError as exc:
        result.note = str(exc)
        return result

    result.ok = True

    context = 0
    try:
        props = fetch(f"{base_url}/props", 10.0)
        settings = props.get("default_generation_settings", {})
        context = int(settings.get("n_ctx", 0))
        layers = settings.get("n_gpu_layers")
        if layers is not None:
            result.host.gpu_present = int(layers) > 0
    except OSError as exc:
        result.note = f"could not read the settings: {exc}"

    try:
        listing = fetch(f"{base_url}/v1/models", 10.0)
        for entry in listing.get("data", [])[:MAX_MODELS_EXAMINED]:
            result.models.append(
                ModelCapability(name=entry.get("id", ""), context_length=context)
            )
    except OSError as exc:
        result.note = f"could not list the models: {exc}"

    return result
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `.venv/bin/python -m pytest tests/test_node_backends.py -q`
Expected: PASS, 9 tests.

- [ ] **Step 5: Update the network guard, deliberately**

The phase-8 test asserting `src/kernel/models.py` is the only module reaching the network now has a second module to name. Widen it in the open, with the reason recorded.

In `tests/test_hardening.py::TestOffline::test_only_the_model_adapter_reaches_the_network`, replace the assertion:

```python
        assert offenders == {
            "src/kernel/models.py": ["urllib.error", "urllib.request"],
            "src/nodes/backends.py": ["urllib.error", "urllib.request"],
        }, (
            f"network imports moved: {offenders}. Two modules may reach the "
            f"network and no more: the model adapter, and node discovery. "
            f"Discovery is config-time, runs only after a person grants "
            f"permission, and is not on an authoritative path — validation, "
            f"promotion, classification and export never call it."
        )
```

- [ ] **Step 6: Run the hardening suite to confirm the guard still guards**

Run: `.venv/bin/python -m pytest tests/test_hardening.py -q`
Expected: PASS. The offline tests must still pass — discovery is not called by the lifecycle.

- [ ] **Step 7: Commit**

```bash
git add src/nodes/backends.py tests/test_node_backends.py tests/test_hardening.py
git commit -m "feat: read an inference server's own metadata, never the model"
```

---

### Task 4: Consent-gated streaming discovery

**Files:**
- Create: `src/nodes/discovery.py`
- Test: `tests/test_node_discovery.py`

**Interfaces:**
- Consumes: Tasks 1 and 3.
- Produces: `DiscoveryEvent(stage, message, ok, node, progress, finished)`, `discover(scope, host="", *, consent=None, fetch=..., connect_timeout=2.0) -> Iterator[DiscoveryEvent]`, `candidate_addresses(scope, host) -> list[tuple[str, NodeKind]]`, `ConsentRefused`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_node_discovery.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Scanning: what it may touch, and how it reports what it finds.

Permission is this feature's privacy promise, so it is tested rather than
trusted. Every test records which addresses were attempted and asserts the
exact set.
"""

import pytest

from src.nodes.discovery import DiscoveryEvent, candidate_addresses, discover
from src.schemas.node import NodeKind, ScanScope


class Recorder:
    """A fetcher that records every URL asked for and answers as Ollama."""

    def __init__(self, answering: set[str] | None = None):
        self.asked: list[str] = []
        self.answering = answering if answering is not None else {"127.0.0.1:11434"}

    def __call__(self, url: str, timeout: float = 0.0) -> dict:
        self.asked.append(url)
        if not any(host in url for host in self.answering):
            raise OSError("connection refused")
        if url.endswith("/api/version"):
            return {"version": "0.5.4"}
        if url.endswith("/api/tags"):
            return {"models": [{"name": "llama3.1:8b", "size": 1,
                                "details": {"family": "llama"}}]}
        if url.endswith("/api/ps"):
            return {"models": []}
        return {"model_info": {"llama.context_length": 8192}, "capabilities": []}

    def hosts(self) -> set[str]:
        """Every distinct host:port attempted."""
        return {u.split("//", 1)[1].split("/", 1)[0] for u in self.asked}


class TestPermissionIsHonoured:
    def test_none_opens_nothing_at_all(self):
        fetch = Recorder()
        events = list(discover(ScanScope.NONE, fetch=fetch))
        assert fetch.asked == [], "NONE must not open a single connection"
        assert events[-1].finished

    def test_this_machine_touches_only_loopback(self):
        fetch = Recorder()
        list(discover(ScanScope.THIS_MACHINE, fetch=fetch))
        for host in fetch.hosts():
            assert host.startswith("127.0.0.1"), f"left the machine: {host}"

    def test_this_machine_tries_both_known_ports(self):
        fetch = Recorder()
        list(discover(ScanScope.THIS_MACHINE, fetch=fetch))
        assert fetch.hosts() == {"127.0.0.1:11434", "127.0.0.1:8081"}

    def test_named_host_touches_only_that_host(self):
        fetch = Recorder(answering={"10.0.0.9:11434"})
        list(discover(ScanScope.NAMED_HOST, "10.0.0.9", fetch=fetch))
        for host in fetch.hosts():
            assert host.startswith("10.0.0.9"), f"touched something else: {host}"

    def test_a_named_host_with_a_port_is_honoured_exactly(self):
        fetch = Recorder(answering={"10.0.0.9:9999"})
        list(discover(ScanScope.NAMED_HOST, "10.0.0.9:9999", fetch=fetch))
        assert fetch.hosts() == {"10.0.0.9:9999"}


class TestCandidates:
    def test_none_has_no_candidates(self):
        assert candidate_addresses(ScanScope.NONE, "") == []

    def test_this_machine_is_loopback_on_both_ports(self):
        assert candidate_addresses(ScanScope.THIS_MACHINE, "") == [
            ("http://127.0.0.1:11434", NodeKind.OLLAMA),
            ("http://127.0.0.1:8081", NodeKind.LLAMACPP),
        ]

    def test_a_bare_named_host_tries_both_ports(self):
        assert candidate_addresses(ScanScope.NAMED_HOST, "box") == [
            ("http://box:11434", NodeKind.OLLAMA),
            ("http://box:8081", NodeKind.LLAMACPP),
        ]

    def test_a_full_url_is_taken_as_given(self):
        assert candidate_addresses(ScanScope.NAMED_HOST, "http://box:1234") == [
            ("http://box:1234", NodeKind.OLLAMA),
            ("http://box:1234", NodeKind.LLAMACPP),
        ]


class TestTheStream:
    def test_events_arrive_before_the_scan_finishes(self):
        fetch = Recorder()
        stream = discover(ScanScope.THIS_MACHINE, fetch=fetch)
        first = next(stream)
        assert isinstance(first, DiscoveryEvent)
        assert not first.finished, "the first event must not be the last"

    def test_each_event_carries_a_human_message(self):
        fetch = Recorder()
        for event in discover(ScanScope.THIS_MACHINE, fetch=fetch):
            assert event.message, f"stage {event.stage} produced no message"
            assert "provenance" not in event.message.lower()
            assert "endpoint" not in event.message.lower()

    def test_a_found_computer_is_carried_on_the_event(self):
        fetch = Recorder()
        events = list(discover(ScanScope.THIS_MACHINE, fetch=fetch))
        found = [e for e in events if e.node is not None]
        assert found, "nothing was reported despite a server answering"
        assert found[-1].node.reachable
        assert found[-1].node.models

    def test_the_last_event_is_marked_finished(self):
        fetch = Recorder()
        events = list(discover(ScanScope.THIS_MACHINE, fetch=fetch))
        assert events[-1].finished
        assert sum(1 for e in events if e.finished) == 1

    def test_a_stage_failure_keeps_what_was_already_found(self):
        class HalfBroken(Recorder):
            def __call__(self, url, timeout=0.0):
                if url.endswith("/api/tags"):
                    self.asked.append(url)
                    raise OSError("boom")
                return super().__call__(url, timeout)

        fetch = HalfBroken()
        events = list(discover(ScanScope.THIS_MACHINE, fetch=fetch))
        nodes = [e.node for e in events if e.node is not None]
        assert nodes, "a listing failure discarded the whole scan"
        assert nodes[-1].reachable, "the server answered and must still be recorded"

    def test_nothing_found_still_finishes_cleanly(self):
        fetch = Recorder(answering=set())
        events = list(discover(ScanScope.THIS_MACHINE, fetch=fetch))
        assert events[-1].finished
        assert all(e.node is None for e in events)
        assert "didn't find" in events[-1].message.lower()
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `.venv/bin/python -m pytest tests/test_node_discovery.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.nodes.discovery'`

- [ ] **Step 3: Write the implementation**

```python
# src/nodes/discovery.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Finding inference computers, with permission, one finding at a time.

**Discovery is a stream, not a return value.** ``discover()`` yields an event
each time it learns something, so a person watches it happen instead of
staring at a frozen window. The command line renders each event as a line; the
desktop fills a card row by row. Same service, two renderers.

It also means a stage that fails costs one row rather than the whole scan: a
server that answers but cannot list its models is still worth recording, and
the event carrying it says so plainly.

**Permission is checked before anything opens.** ``ScanScope.NONE`` opens no
connection at all, and each rung reaches exactly as far as it was granted.
That is the privacy promise this feature makes, and it is enforced here rather
than in the interface, so no caller can skip it.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterator, Optional

from src.nodes.backends import (
    PORTS,
    Fetcher,
    Poster,
    http_get_json,
    http_post_json,
    probe_llamacpp,
    probe_ollama,
)
from src.schemas.node import (
    InferenceNode,
    NodeKind,
    Provenance,
    ScanScope,
    slugify,
)


class ConsentRefused(Exception):
    """Raised when a scan is attempted beyond what was permitted."""


@dataclass
class DiscoveryEvent:
    """One thing learned, as it is learned."""

    stage: str
    message: str
    ok: bool = True
    node: Optional[InferenceNode] = None
    progress: tuple[int, int] = (0, 0)
    finished: bool = False


def _normalise(host: str) -> str:
    """Turn what a person typed into a base URL, without inventing a port."""
    host = host.strip()
    if host.startswith("http://") or host.startswith("https://"):
        return host.rstrip("/")
    return f"http://{host}"


def candidate_addresses(scope: ScanScope, host: str) -> list[tuple[str, NodeKind]]:
    """Every address this permission allows, and which backend to try there.

    A bare host is tried on both known ports. A host that already names a port,
    or a full URL, is taken exactly as given and tried as both backends — the
    one that answers wins.
    """
    if scope is ScanScope.NONE:
        return []
    if scope is ScanScope.THIS_MACHINE:
        return [(f"http://127.0.0.1:{port}", kind) for port, kind in PORTS]
    if scope is ScanScope.NAMED_HOST:
        base = _normalise(host)
        tail = base.split("//", 1)[1]
        if ":" in tail:
            return [(base, kind) for _port, kind in PORTS]
        return [(f"{base}:{port}", kind) for port, kind in PORTS]
    raise ConsentRefused(f"{scope.value} is not scannable by this function")


def _describe(node: InferenceNode) -> list[tuple[str, str]]:
    """The human lines for what one probe established, in the order learned."""
    lines = [("backend", f"It's {node.kind.value} {node.backend_version}".rstrip())]
    if node.models:
        biggest = max(node.models, key=lambda m: m.size_bytes)
        lines.append(("models", f"{len(node.models)} models available"))
        lines.append(("biggest", f"Biggest is {biggest.name}"))
        if node.max_context_length:
            from src.nodes.summary import human_words

            lines.append(
                ("context", f"Longest input — {human_words(node.max_context_length)}")
            )
    else:
        lines.append(("models", "Couldn't list the models"))
    if node.host.gpu_present is True:
        from src.nodes.summary import human_bytes

        lines.append(
            ("hardware", f"Graphics card in use — {human_bytes(node.host.vram_bytes)}")
        )
    elif node.host.gpu_present is False:
        lines.append(("hardware", "No graphics card doing the work"))
    else:
        lines.append(("hardware", "Couldn't tell whether there's a graphics card"))
    return lines


def discover(
    scope: ScanScope,
    host: str = "",
    *,
    fetch: Fetcher = http_get_json,
    post: Poster = http_post_json,
    connect_timeout: float = 2.0,
) -> Iterator[DiscoveryEvent]:
    """Look for inference computers, yielding each finding as it is made.

    Opens nothing when the permission is ``NONE``. Every other rung reaches
    exactly as far as it was granted and no further.
    """
    if scope is ScanScope.NONE:
        yield DiscoveryEvent(
            stage="permission",
            message="Not looking — nothing was permitted.",
            finished=True,
        )
        return

    candidates = candidate_addresses(scope, host)
    total = len(candidates)
    found = 0
    seen_urls: set[str] = set()

    for index, (base_url, kind) in enumerate(candidates, start=1):
        if base_url in seen_urls:
            continue
        port = base_url.rsplit(":", 1)[-1]
        yield DiscoveryEvent(
            stage="trying",
            message=f"Looking on port {port}...",
            progress=(index, total),
        )

        result = (
            probe_ollama(base_url, fetch, post)
            if kind is NodeKind.OLLAMA
            else probe_llamacpp(base_url, fetch)
        )
        if not result.ok:
            continue

        seen_urls.add(base_url)
        found += 1
        node = InferenceNode(
            node_id=slugify(f"{result.kind.value}-{port}"),
            label=f"{result.kind.value} on {'this computer' if '127.0.0.1' in base_url else host}".strip(),
            kind=result.kind,
            url=base_url,
            is_local="127.0.0.1" in base_url,
            reachable=True,
            backend_version=result.backend_version,
            models=result.models,
            host=result.host,
            last_probed_at=datetime.now(timezone.utc),
            provenance={
                "backend_version": Provenance.DETECTED,
                "models": Provenance.DETECTED,
                "host.gpu_present": Provenance.DETECTED,
                "host.vram_bytes": Provenance.DETECTED,
                "url": Provenance.DETECTED,
            },
        )

        yield DiscoveryEvent(
            stage="reachable",
            message=f"Something's listening on port {port}",
            node=node,
            progress=(index, total),
        )
        for stage, message in _describe(node):
            yield DiscoveryEvent(
                stage=stage, message=message, node=node, progress=(index, total)
            )

    if found:
        noun = "computer" if found == 1 else "computers"
        yield DiscoveryEvent(
            stage="done", message=f"Found {found} {noun}.", finished=True
        )
    else:
        yield DiscoveryEvent(
            stage="done",
            message="Didn't find anything answering. You can type it in instead.",
            ok=False,
            finished=True,
        )
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `.venv/bin/python -m pytest tests/test_node_discovery.py -q`
Expected: PASS, 15 tests.

- [ ] **Step 5: Prove the permission guard actually guards**

A guard nobody has watched fail is not a guard. Temporarily make `discover` ignore its scope:

```bash
# In src/nodes/discovery.py, comment out the `if scope is ScanScope.NONE:` block.
.venv/bin/python -m pytest tests/test_node_discovery.py -q -k none_opens_nothing
# Expected: FAIL — "NONE must not open a single connection"
# Then restore the block and re-run: PASS
```

- [ ] **Step 6: Commit**

```bash
git add src/nodes/discovery.py tests/test_node_discovery.py
git commit -m "feat: consent-gated discovery that streams each finding"
```

---

### Task 5: Storage and endpoint resolution

**Files:**
- Create: `src/nodes/store.py`, `src/nodes/registry.py`
- Test: `tests/test_node_store.py`

**Interfaces:**
- Consumes: Tasks 1 and 4.
- Produces: `NodeStore(path)` with `.load() -> tuple[list[InferenceNode], ScanConsent]`, `.save(nodes, consent) -> None`, `.upsert(node) -> InferenceNode`, `.forget(node_id) -> bool`, `.default_path() -> Path`; and `merged_endpoints(store) -> dict[str, dict]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_node_store.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Where what a person told us is kept, and how it reaches the runtime."""

import pytest
import yaml

from src.nodes.registry import merged_endpoints
from src.nodes.store import NodeStore
from src.schemas.node import (
    HostCapability,
    InferenceNode,
    ModelCapability,
    NodeKind,
    Provenance,
    ScanConsent,
    ScanScope,
)


def node(**kw) -> InferenceNode:
    base = dict(node_id="home-pc", label="Home PC", kind=NodeKind.OLLAMA,
                url="http://localhost:11434", reachable=True)
    base.update(kw)
    return InferenceNode(**base)


@pytest.fixture()
def store(tmp_path) -> NodeStore:
    return NodeStore(tmp_path / "nodes.yaml")


class TestEmptyStore:
    def test_a_missing_file_is_no_computers_and_no_permission(self, store):
        nodes, consent = store.load()
        assert nodes == []
        assert consent.scope is ScanScope.NONE

    def test_saving_creates_the_file(self, store):
        store.save([node()], ScanConsent())
        assert store.path.exists()


class TestRoundTrip:
    def test_a_computer_survives_save_and_load(self, store):
        original = node(models=[ModelCapability(name="m", context_length=8192)],
                        host=HostCapability(gpu_present=True, vram_bytes=6_000_000_000),
                        provenance={"models": Provenance.DETECTED})
        store.save([original], ScanConsent.granted(ScanScope.THIS_MACHINE, "sam"))
        loaded, consent = store.load()
        assert loaded == [original]
        assert consent.scope is ScanScope.THIS_MACHINE
        assert consent.granted_by == "sam"

    def test_the_file_is_readable_yaml(self, store):
        store.save([node()], ScanConsent())
        raw = yaml.safe_load(store.path.read_text(encoding="utf-8"))
        assert raw["nodes"]["home-pc"]["label"] == "Home PC"

    def test_an_unknown_field_is_refused_by_name(self, store):
        store.path.write_text(
            "schema_version: '1'\nnodes:\n  a:\n    label: x\n    kind: ollama\n"
            "    url: http://h\n    bogus: 1\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError) as exc:
            store.load()
        assert "bogus" in str(exc.value)


class TestUpsert:
    def test_a_new_computer_is_added(self, store):
        store.upsert(node())
        assert [n.node_id for n in store.load()[0]] == ["home-pc"]

    def test_rediscovering_the_same_address_updates_in_place(self, store):
        store.upsert(node())
        store.upsert(node(node_id="other", label="Other",
                          backend_version="0.5.5"))
        nodes, _ = store.load()
        assert len(nodes) == 1, "the same URL must not become two computers"
        assert nodes[0].backend_version == "0.5.5"

    def test_a_rescan_preserves_what_a_person_typed(self, store):
        # This is what makes "Check again" safe to press.
        store.upsert(node(label="Kitchen Box",
                          provenance={"label": Provenance.DECLARED}))
        store.upsert(node(label="ollama on this computer", backend_version="0.6"))
        nodes, _ = store.load()
        assert nodes[0].label == "Kitchen Box", "a rescan overwrote a typed value"
        assert nodes[0].backend_version == "0.6", "a detected value was not refreshed"

    def test_forget_removes_one(self, store):
        store.upsert(node())
        assert store.forget("home-pc") is True
        assert store.load()[0] == []

    def test_forgetting_an_unknown_id_reports_it(self, store):
        assert store.forget("nope") is False


class TestEndpointResolution:
    def test_defaults_survive_with_no_computers(self, store):
        endpoints = merged_endpoints(store)
        assert "local-ollama" in endpoints
        assert "local-llama" in endpoints

    def test_a_computer_becomes_a_usable_endpoint(self, store):
        store.upsert(node())
        endpoints = merged_endpoints(store)
        assert endpoints["home-pc"] == {"kind": "ollama",
                                        "url": "http://localhost:11434"}

    def test_the_mapping_fits_the_existing_registry(self):
        # The kernel is FROZEN and consumed unchanged: the merged mapping is
        # injected into the registry it already accepts.
        from src.kernel.models import ModelEndpointRegistry

        registry = ModelEndpointRegistry(
            {"home-pc": {"kind": "ollama", "url": "http://h:11434"}}
        )
        assert registry.get("home-pc").url == "http://h:11434"
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `.venv/bin/python -m pytest tests/test_node_store.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.nodes.store'`

- [ ] **Step 3: Write the implementation**

```python
# src/nodes/store.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Where what a person told us about their computers is kept.

One file, ``$FUKASAWA_HOME/nodes.yaml``, holding both the computers and the
standing permission — a permission with no computers beside it is a thing
people lose track of.

**This file describes somebody's house.** It is per-operator, never committed,
never bundled into a distribution, and never written into an exported brief. A
shared workflow references a computer by name; the address stays here.

The upsert rule is what makes "Check again" safe to press: rediscovering an
address already stored refreshes the values that were *detected* and preserves
every value a person *typed*.
"""

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import ValidationError

from src.schemas.node import InferenceNode, Provenance, ScanConsent

#: Matches the trust store's location, so everything local lives together.
DEFAULT_HOME = Path(os.environ.get("FUKASAWA_HOME", "~/.fukasawa")).expanduser()


class NodeStore:
    """Read and write the computers a person has told us about."""

    def __init__(self, path: Optional[Path] = None) -> None:
        """Bind to a file. Defaults to `$FUKASAWA_HOME/nodes.yaml`."""
        self.path = Path(path) if path else self.default_path()

    @staticmethod
    def default_path() -> Path:
        """Where this file lives when nobody says otherwise."""
        return DEFAULT_HOME / "nodes.yaml"

    def load(self) -> tuple[list[InferenceNode], ScanConsent]:
        """Everything stored. A missing file is no computers and no permission."""
        if not self.path.exists():
            return [], ScanConsent()
        raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        try:
            nodes = [
                InferenceNode.model_validate({**spec, "node_id": node_id})
                for node_id, spec in (raw.get("nodes") or {}).items()
            ]
            consent = ScanConsent.model_validate(raw.get("consent") or {})
        except ValidationError as exc:
            raise ValueError(f"{self.path} does not match the contract — {exc}") from exc
        return nodes, consent

    def save(self, nodes: list[InferenceNode], consent: ScanConsent) -> None:
        """Write every computer and the standing permission."""
        payload = {
            "schema_version": "1",
            "consent": consent.model_dump(mode="json", exclude={"schema_version"}),
            "nodes": {
                node.node_id: node.model_dump(
                    mode="json", exclude={"node_id", "schema_version"}
                )
                for node in nodes
            },
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            yaml.safe_dump(payload, sort_keys=False, width=100, allow_unicode=True),
            encoding="utf-8",
        )

    def upsert(self, node: InferenceNode) -> InferenceNode:
        """Add a computer, or refresh one already stored at the same address.

        Values a person typed are preserved; values that were detected are
        replaced. Two computers may never share a URL.
        """
        nodes, consent = self.load()
        for index, existing in enumerate(nodes):
            if existing.url != node.url:
                continue
            # Everything a person typed wins over anything just detected. Only
            # top-level fields are editable (see EDITABLE in the GUI service),
            # so a dotted key cannot be DECLARED and none is looked for.
            typed = {
                key: source
                for key, source in existing.provenance.items()
                if source is Provenance.DECLARED
            }
            merged = node.model_copy(update={
                "node_id": existing.node_id,
                "provenance": {**node.provenance, **typed},
            })
            for key in typed:
                setattr(merged, key, getattr(existing, key))
            nodes[index] = merged
            self.save(nodes, consent)
            return merged

        nodes.append(node)
        self.save(nodes, consent)
        return node

    def forget(self, node_id: str) -> bool:
        """Remove one computer. False when there was nothing by that name."""
        nodes, consent = self.load()
        remaining = [n for n in nodes if n.node_id != node_id]
        if len(remaining) == len(nodes):
            return False
        self.save(remaining, consent)
        return True

    def set_consent(self, consent: ScanConsent) -> None:
        """Record a new standing permission, leaving the computers alone."""
        nodes, _ = self.load()
        self.save(nodes, consent)
```

```python
# src/nodes/registry.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Making stored computers usable by the runtime that already exists.

`src/kernel/models.py` is FROZEN, and it does not need changing:
``ModelEndpointRegistry`` already accepts an explicit mapping. So the merge
happens here and the result is injected — the kernel is consumed unchanged,
exactly as the rest of this release consumes it.

Resolution order, later winning:

    built-in defaults  ->  model_endpoints.yaml  ->  nodes.yaml

An existing endpoint file keeps working untouched, and a computer becomes a
usable endpoint under its own id, so a graph says ``endpoint: home-pc`` and
never carries an address.
"""

from pathlib import Path
from typing import Optional

import yaml

from src.kernel.models import DEFAULT_ENDPOINTS
from src.nodes.store import DEFAULT_HOME, NodeStore


def merged_endpoints(
    store: Optional[NodeStore] = None,
    legacy_path: Optional[Path] = None,
) -> dict[str, dict]:
    """Every named endpoint the runtime should know about."""
    store = store or NodeStore()
    legacy_path = legacy_path or (DEFAULT_HOME / "model_endpoints.yaml")

    endpoints: dict[str, dict] = dict(DEFAULT_ENDPOINTS)

    if legacy_path.exists():
        raw = yaml.safe_load(legacy_path.read_text(encoding="utf-8")) or {}
        endpoints.update(raw.get("endpoints") or {})

    nodes, _consent = store.load()
    for node in nodes:
        endpoints[node.node_id] = {"kind": node.kind.value, "url": node.url}

    return endpoints
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `.venv/bin/python -m pytest tests/test_node_store.py -q`
Expected: PASS, 14 tests.

- [ ] **Step 5: Confirm no FROZEN file was touched**

```bash
git status --short | grep -E "kernel/|security/|schemas/graph|schemas/bundle|generator\.py|state_machine|runtime/bundle" || echo "no frozen path touched"
```
Expected: `no frozen path touched`

- [ ] **Step 6: Commit**

```bash
git add src/nodes/store.py src/nodes/registry.py tests/test_node_store.py
git commit -m "feat: store computers locally, and resolve them as endpoints"
```

---

### Task 6: The `node` CLI sub-app

**Files:**
- Modify: `src/cli.py` (add a `node_app` Typer sub-app and register it beside the existing `model_app`)
- Test: `tests/test_node_cli.py`

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces: commands `node scan`, `node list`, `node show`, `node add`, `node forget`, `node consent`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_node_cli.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""The command line, in the same voice as the desktop.

Not terse. A person who reached for a terminal still deserves sentences, and
the copy rules of the design apply here exactly as they do on screen.
"""

import json

import pytest
from typer.testing import CliRunner

from src.cli import app
from src.nodes.store import NodeStore
from src.schemas.node import (
    InferenceNode,
    ModelCapability,
    NodeKind,
    ScanConsent,
    ScanScope,
)

JUDGEMENT = ["slow", "fast", "good", "poor", "powerful", "weak", "adequate"]
OWNERSHIP = ["stays with you", "your workflow", "your model", "off your hands"]


@pytest.fixture()
def store_path(tmp_path, monkeypatch):
    path = tmp_path / "nodes.yaml"
    monkeypatch.setattr("src.nodes.store.NodeStore.default_path",
                        staticmethod(lambda: path))
    return path


def seed(store_path, **kw):
    store = NodeStore(store_path)
    base = dict(node_id="home-pc", label="Home PC", kind=NodeKind.OLLAMA,
                url="http://localhost:11434", reachable=True,
                models=[ModelCapability(name="llama3.1:8b", context_length=8192)])
    base.update(kw)
    store.save([InferenceNode(**base)],
               ScanConsent.granted(ScanScope.THIS_MACHINE, "sam"))
    return store


class TestList:
    def test_nothing_configured_says_what_the_program_does(self, store_path):
        result = CliRunner().invoke(app, ["node", "list"])
        assert result.exit_code == 0
        assert "nothing yet" in result.output
        assert "do not require a computer" in result.output

    def test_a_stored_computer_is_shown_with_its_figures(self, store_path):
        seed(store_path)
        result = CliRunner().invoke(app, ["node", "list"])
        assert result.exit_code == 0
        assert "Home PC" in result.output
        assert "words" in result.output

    def test_json_output_is_machine_readable(self, store_path):
        seed(store_path)
        result = CliRunner().invoke(app, ["node", "list", "--json"])
        payload = json.loads(result.output)
        assert payload["nodes"][0]["node_id"] == "home-pc"


class TestScan:
    def test_scanning_without_permission_is_refused_not_crashed(self, store_path):
        result = CliRunner().invoke(app, ["node", "scan", "--scope", "none", "--yes"])
        assert result.exit_code == 3, result.output
        assert "permission" in result.output.lower()

    def test_an_unknown_scope_is_a_user_error(self, store_path):
        result = CliRunner().invoke(app, ["node", "scan", "--scope", "wat", "--yes"])
        assert result.exit_code == 1

    def test_a_scan_prints_each_finding_as_it_arrives(self, store_path, monkeypatch):
        from src.nodes.discovery import DiscoveryEvent

        def fake(scope, host="", **kw):
            yield DiscoveryEvent("trying", "Looking on port 11434...")
            yield DiscoveryEvent("reachable", "Something's listening on port 11434")
            yield DiscoveryEvent("done", "Found 1 computer.", finished=True)

        monkeypatch.setattr("src.cli._discover", fake)
        result = CliRunner().invoke(
            app, ["node", "scan", "--scope", "this-machine", "--yes"]
        )
        assert result.exit_code == 0, result.output
        assert "Looking on port 11434" in result.output
        assert "Found 1 computer." in result.output


class TestAddAndForget:
    def test_a_computer_can_be_added_by_hand(self, store_path):
        result = CliRunner().invoke(app, [
            "node", "add", "--label", "Kitchen Box", "--kind", "ollama",
            "--url", "http://10.0.0.9:11434",
        ])
        assert result.exit_code == 0, result.output
        nodes, _ = NodeStore(store_path).load()
        assert nodes[0].node_id == "kitchen-box"
        assert nodes[0].source_of("url").value == "DECLARED"

    def test_forgetting_something_absent_is_a_user_error(self, store_path):
        result = CliRunner().invoke(app, ["node", "forget", "nope"])
        assert result.exit_code == 1
        assert "nope" in result.output


class TestConsent:
    def test_the_current_permission_is_shown(self, store_path):
        seed(store_path)
        result = CliRunner().invoke(app, ["node", "consent"])
        assert result.exit_code == 0
        assert "this computer" in result.output.lower()

    def test_permission_can_be_changed(self, store_path):
        seed(store_path)
        result = CliRunner().invoke(app, ["node", "consent", "--set", "none"])
        assert result.exit_code == 0
        _nodes, consent = NodeStore(store_path).load()
        assert consent.scope is ScanScope.NONE


class TestCopyRules:
    @pytest.mark.parametrize("argv", [
        ["node", "list"],
        ["node", "consent"],
    ])
    def test_no_command_judges_or_assumes_ownership(self, store_path, argv):
        seed(store_path)
        output = CliRunner().invoke(app, argv).output.lower()
        assert not [w for w in JUDGEMENT if w in output]
        assert not [w for w in OWNERSHIP if w in output]
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `.venv/bin/python -m pytest tests/test_node_cli.py -q`
Expected: FAIL — no `node` command registered.

- [ ] **Step 3: Write the implementation**

Add to `src/cli.py`. Place the sub-app registration beside the existing `model_app` registration, and the commands after the `model` section.

```python
# --- near the other sub-app definitions -------------------------------------
node_app = typer.Typer(help="Tell Fukasawa what computers can run AI for it.")
app.add_typer(node_app, name="node")


# --- indirection so tests can substitute the scanner -------------------------
def _discover(scope, host="", **kwargs):
    """Run a scan. Named so a test can replace it without a live network."""
    from src.nodes.discovery import discover

    return discover(scope, host, **kwargs)


def _node_store():
    """Open the store at its configured location."""
    from src.nodes.store import NodeStore

    return NodeStore()


#: Both directions of the scope vocabulary, declared once. The CLI flag values
#: are hyphenated; the enum values are not; the sentence is neither.
_SCOPE_FLAGS = {
    "none": "NONE",
    "this-machine": "THIS_MACHINE",
    "named-host": "NAMED_HOST",
    "local-network": "LOCAL_NETWORK",
}
_SCOPE_WORDS = {
    "NONE": "Not looking at anything",
    "THIS_MACHINE": "Just this computer",
    "NAMED_HOST": "One computer, named",
    "LOCAL_NETWORK": "Every computer on this network",
}


def _scope_from(text: str):
    """Turn a --scope value into a ScanScope, or exit 1 naming the choices."""
    from src.schemas.node import ScanScope

    if text not in _SCOPE_FLAGS:
        console.print(
            f"[red]'{text}' is not one of the choices.[/red] "
            f"Use one of: {', '.join(_SCOPE_FLAGS)}"
        )
        raise typer.Exit(1)
    return ScanScope(_SCOPE_FLAGS[text])


def _render_summary(nodes) -> None:
    """Print the panel: figures with units, and at most one consequence."""
    from src.nodes.summary import summarise

    summary = summarise(nodes)
    console.print("\n[bold]What this means when steps run[/bold]")
    for row in summary.rows:
        source = f"   [dim]{row.source}[/dim]" if row.source else ""
        console.print(f"  {row.label:<32} {row.value}{source}")
    if summary.consequence:
        console.print(f"\n  {summary.consequence}")


@node_app.command("scan")
def node_scan(
    scope: str = typer.Option(
        "", "--scope", help="none | this-machine | named-host | local-network"
    ),
    host: str = typer.Option("", "--host", help="Address, for --scope named-host."),
    label: str = typer.Option("", "--label", help="What to call what is found."),
    yes: bool = typer.Option(False, "--yes", help="Skip the prompts."),
    as_json: bool = typer.Option(False, "--json", help="One event per line, as JSON."),
) -> None:
    """Look for computers that can run AI, and record what is found.

    Nothing is examined until a permission is chosen. Findings are printed as
    they arrive rather than in a block at the end, because a scan takes time
    and a person watching one deserves to see it happening.
    """
    from src.schemas.node import ScanConsent, ScanScope

    store = _node_store()
    _nodes, existing = store.load()

    if scope:
        chosen = _scope_from(scope)
    elif yes:
        chosen = existing.scope
    else:
        console.print(
            "\nFukasawa can run some workflow steps automatically, using AI\n"
            "on a computer you point it at.\n"
        )
        console.print("[bold]Where should I look?[/bold]")
        console.print("  1  Just this computer            nothing leaves this machine")
        console.print("  2  A computer I'll name")
        console.print("  3  Every computer on this network  takes about a minute; some")
        console.print("                                     workplaces disallow this")
        console.print("  4  Don't look — I'll type it in")
        answer = typer.prompt("Choose", default="1")
        chosen = {
            "1": ScanScope.THIS_MACHINE,
            "2": ScanScope.NAMED_HOST,
            "3": ScanScope.LOCAL_NETWORK,
            "4": ScanScope.NONE,
        }.get(answer.strip(), ScanScope.THIS_MACHINE)

    if chosen is ScanScope.NONE:
        console.print(
            "[yellow]Refused:[/yellow] no permission to look. "
            "Choose a different option, or add a computer with "
            "[cyan]fukasawa node add[/cyan]."
        )
        raise typer.Exit(3)

    if chosen is ScanScope.NAMED_HOST and not host:
        host = typer.prompt("Address of the computer")

    store.set_consent(ScanConsent.granted(chosen, "operator"))

    console.print("")
    found = []
    for event in _discover(chosen, host):
        if as_json:
            # NOTE: src/cli.py imports the json module as `jsonlib`.
            console.print(jsonlib.dumps({
                "stage": event.stage, "message": event.message,
                "ok": event.ok, "finished": event.finished,
            }))
        else:
            mark = "  [green]OK[/green]" if event.ok else "  [yellow]--[/yellow]"
            console.print(f"{mark}  {event.message}")
        if event.node is not None and event.node not in found:
            found.append(event.node)

    for node in found:
        if label:
            node.label = label
        store.upsert(node)

    if found:
        _render_summary(store.load()[0])


@node_app.command("list")
def node_list(
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Show every computer Fukasawa has been told about."""
    nodes, _consent = _node_store().load()
    if as_json:
        console.print(jsonlib.dumps(
            {"nodes": [n.model_dump(mode="json") for n in nodes]}, indent=2
        ))
        return

    from src.nodes.summary import human_words, source_label

    for node in nodes:
        console.print(f"\n[bold]{node.label}[/bold]  [dim]{node.url}[/dim]")
        console.print(f"  Models it can run    {len(node.models)}")
        if node.max_context_length:
            console.print(
                f"  Longest input        {human_words(node.max_context_length)}"
                f"   [dim]{source_label(node.source_of('models'))}[/dim]"
            )
    _render_summary(nodes)


@node_app.command("show")
def node_show(node_id: str = typer.Argument(..., help="Which computer.")) -> None:
    """Show one computer and every model it can serve."""
    nodes, _ = _node_store().load()
    match = next((n for n in nodes if n.node_id == node_id), None)
    if match is None:
        console.print(f"[red]Nothing stored called '{node_id}'.[/red]")
        raise typer.Exit(1)

    from src.nodes.summary import human_bytes, human_rate, human_words

    console.print(f"\n[bold]{match.label}[/bold]  [dim]{match.url}[/dim]")
    console.print(f"  Answering            {'yes' if match.reachable else 'no'}")
    console.print(f"  Speed                {human_rate(match.host.tokens_per_second)}")
    console.print(f"  Graphics card        {human_bytes(match.host.vram_bytes)}")
    for model in match.models:
        console.print(
            f"    {model.name:<28} {human_words(model.context_length)}"
        )


@node_app.command("add")
def node_add(
    label: str = typer.Option(..., "--label", help="What to call it."),
    kind: str = typer.Option(..., "--kind", help="ollama | llamacpp"),
    url: str = typer.Option(..., "--url", help="Base URL it answers on."),
) -> None:
    """Add a computer by hand, without looking for it."""
    from src.schemas.node import InferenceNode, NodeKind, Provenance, slugify

    if kind not in {k.value for k in NodeKind}:
        console.print(f"[red]'{kind}' is not one of: ollama, llamacpp[/red]")
        raise typer.Exit(1)

    node = InferenceNode(
        node_id=slugify(label), label=label, kind=NodeKind(kind), url=url,
        provenance={
            "label": Provenance.DECLARED,
            "url": Provenance.DECLARED,
            "kind": Provenance.DECLARED,
        },
    )
    _node_store().upsert(node)
    console.print(f"Added [bold]{label}[/bold].")


@node_app.command("forget")
def node_forget(node_id: str = typer.Argument(..., help="Which computer.")) -> None:
    """Remove a computer."""
    if not _node_store().forget(node_id):
        console.print(f"[red]Nothing stored called '{node_id}'.[/red]")
        raise typer.Exit(1)
    console.print(f"Removed {node_id}.")


@node_app.command("consent")
def node_consent(
    set_to: str = typer.Option("", "--set", help="none | this-machine | named-host | local-network"),
) -> None:
    """Show or change how far a scan may reach."""
    from src.schemas.node import ScanConsent

    store = _node_store()
    _nodes, consent = store.load()
    if not set_to:
        console.print(f"Currently: {_SCOPE_WORDS[consent.scope.value]}")
        return
    chosen = _scope_from(set_to)
    store.set_consent(ScanConsent.granted(chosen, "operator"))
    console.print(f"Changed to: {_SCOPE_WORDS[chosen.value]}")
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `.venv/bin/python -m pytest tests/test_node_cli.py -q`
Expected: PASS, 13 tests.

- [ ] **Step 5: Run the whole suite — `src/cli.py` is shared**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS, no regression in `tests/test_workflow_cli.py`.

- [ ] **Step 6: Commit**

```bash
git add src/cli.py tests/test_node_cli.py
git commit -m "feat: a node sub-app that speaks in sentences"
```

---

### Task 7: GUI service layer

**Files:**
- Create: `src/gui/services/nodes.py`
- Modify: `src/gui/services/__init__.py` (re-export)
- Test: `tests/test_gui_nodes.py`

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces: `NodeListResult`, `ScanResult`, `NodeRowView`, `list_nodes(store=None) -> NodeListResult`, `scan(scope, host="", store=None, fetch=None) -> Iterator[ScanEventView]`, `save_consent(scope, actor, store=None) -> Outcome`, `add_node(label, kind, url, store=None) -> Outcome`, `forget_node(node_id, store=None) -> Outcome`, `update_field(node_id, field, value, store=None) -> Outcome`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gui_nodes.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""The desktop's half of node management. Tk-free, always runs."""

import pytest

from src.gui.services import nodes as service
from src.nodes.store import NodeStore
from src.schemas.node import (
    InferenceNode,
    ModelCapability,
    NodeKind,
    Provenance,
    ScanScope,
)


@pytest.fixture()
def store(tmp_path) -> NodeStore:
    return NodeStore(tmp_path / "nodes.yaml")


def seed(store):
    store.upsert(InferenceNode(
        node_id="home-pc", label="Home PC", kind=NodeKind.OLLAMA,
        url="http://localhost:11434", reachable=True,
        models=[ModelCapability(name="llama3.1:8b", context_length=8192)],
        provenance={"models": Provenance.DETECTED},
    ))


class TestListing:
    def test_empty_store_is_not_a_failure(self, store):
        result = service.list_nodes(store)
        assert result.ok
        assert result.rows == []
        assert "do not require a computer" in result.consequence

    def test_rows_carry_plain_language_sources(self, store):
        seed(store)
        result = service.list_nodes(store)
        row = result.rows[0]
        assert row.label == "Home PC"
        fields = {f.label: f for f in row.fields}
        assert fields["Longest input"].source == "found it"


class TestEditing:
    def test_editing_a_field_marks_it_as_typed(self, store):
        seed(store)
        assert service.update_field("home-pc", "label", "Kitchen Box", store).ok
        nodes, _ = store.load()
        assert nodes[0].label == "Kitchen Box"
        assert nodes[0].source_of("label") is Provenance.DECLARED

    def test_editing_an_unknown_computer_is_a_refusal_not_a_crash(self, store):
        result = service.update_field("nope", "label", "x", store)
        assert not result.ok
        assert "nope" in result.refusal

    def test_an_unknown_field_is_refused(self, store):
        seed(store)
        result = service.update_field("home-pc", "bogus", "x", store)
        assert not result.ok


class TestConsent:
    def test_consent_is_recorded(self, store):
        assert service.save_consent(ScanScope.THIS_MACHINE, "sam", store).ok
        _nodes, consent = store.load()
        assert consent.scope is ScanScope.THIS_MACHINE


class TestScanning:
    def test_scanning_without_permission_refuses(self, store):
        events = list(service.scan(ScanScope.NONE, store=store))
        assert events[-1].finished
        assert not events[-1].ok

    def test_events_are_view_shaped(self, store):
        def fetch(url, timeout=0.0):
            if "11434" not in url:
                raise OSError("refused")
            if url.endswith("/api/version"):
                return {"version": "0.5.4"}
            if url.endswith("/api/tags"):
                return {"models": [{"name": "m", "size": 1, "details": {}}]}
            if url.endswith("/api/ps"):
                return {"models": []}
            return {"model_info": {}, "capabilities": []}

        events = list(service.scan(ScanScope.THIS_MACHINE, store=store, fetch=fetch))
        assert all(hasattr(e, "message") for e in events)
        assert events[-1].finished
        nodes, _ = store.load()
        assert nodes, "a discovered computer was not saved"


class TestServicesStayTkFree:
    def test_no_widget_import(self):
        source = (
            __import__("pathlib").Path("src/gui/services/nodes.py")
            .read_text(encoding="utf-8")
        )
        assert "customtkinter" not in source
        assert "import tkinter" not in source
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `.venv/bin/python -m pytest tests/test_gui_nodes.py -q`
Expected: FAIL — `ImportError: cannot import name 'nodes'`

- [ ] **Step 3: Write the implementation**

```python
# src/gui/services/nodes.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""The desktop's half of telling Fukasawa what computers it can use.

Tk-free by rule (ADR-007 §1): dataclasses in, dataclasses out, no widget
imports, no printing. The view renders what these return and decides nothing.

Scanning is exposed as a **generator of view-shaped events**, because the
design requires findings to appear one at a time. The view runs it on the
phase-7 worker thread and pushes each event onto the queue the tab already
drains — no new threading machinery.
"""

from dataclasses import dataclass, field
from typing import Iterator, Optional

from src.gui.services.workflow import Outcome
from src.nodes.discovery import discover
from src.nodes.store import NodeStore
from src.nodes.summary import human_bytes, human_rate, human_words, source_label, summarise
from src.schemas.node import (
    InferenceNode,
    NodeKind,
    Provenance,
    ScanConsent,
    ScanScope,
    slugify,
)

#: Fields a person may edit from the tab, and how each is rendered.
EDITABLE = ("label", "url", "kind")


@dataclass
class FieldView:
    """One row of a computer's card."""

    name: str
    label: str
    value: str
    source: str
    editable: bool = False


@dataclass
class NodeRowView:
    """One computer, flattened for display."""

    node_id: str
    label: str
    url: str
    fields: list[FieldView] = field(default_factory=list)


@dataclass
class NodeListResult(Outcome):
    """Every computer, plus the panel that says what follows."""

    rows: list[NodeRowView] = field(default_factory=list)
    summary_rows: list[tuple[str, str, str]] = field(default_factory=list)
    consequence: str = ""


@dataclass
class ScanEventView:
    """One discovery event, ready to render."""

    stage: str
    message: str
    ok: bool = True
    finished: bool = False
    done: int = 0
    total: int = 0


def _store(store: Optional[NodeStore]) -> NodeStore:
    """Use the store given, else the configured one."""
    return store or NodeStore()


def _row(node: InferenceNode) -> NodeRowView:
    """Flatten one computer into display rows with plain-language sources."""
    return NodeRowView(
        node_id=node.node_id,
        label=node.label,
        url=node.url,
        fields=[
            FieldView("label", "Call it", node.label,
                      source_label(node.source_of("label")), editable=True),
            FieldView("url", "Address", node.url,
                      source_label(node.source_of("url")), editable=True),
            FieldView("models", "Models it can run", str(len(node.models)),
                      source_label(node.source_of("models"))),
            FieldView("context", "Longest input",
                      human_words(node.max_context_length),
                      source_label(node.source_of("models"))),
            FieldView("speed", "Speed", human_rate(node.host.tokens_per_second),
                      source_label(node.source_of("host.tokens_per_second"))),
            FieldView("gpu", "Graphics card", human_bytes(node.host.vram_bytes),
                      source_label(node.source_of("host.vram_bytes"))),
        ],
    )


def list_nodes(store: Optional[NodeStore] = None) -> NodeListResult:
    """Every computer, and what follows from having them. Never refuses."""
    nodes, _consent = _store(store).load()
    summary = summarise(nodes)
    return NodeListResult(
        ok=True,
        summary=f"{len(nodes)} computer(s) recorded." if nodes else "None recorded yet.",
        rows=[_row(n) for n in nodes],
        summary_rows=[(r.label, r.value, r.source) for r in summary.rows],
        consequence=summary.consequence,
    )


def save_consent(
    scope: ScanScope, actor: str, store: Optional[NodeStore] = None
) -> Outcome:
    """Record how far a scan may reach."""
    _store(store).set_consent(ScanConsent.granted(scope, actor))
    return Outcome(ok=True, summary="Saved.")


def scan(
    scope: ScanScope,
    host: str = "",
    store: Optional[NodeStore] = None,
    fetch=None,
) -> Iterator[ScanEventView]:
    """Look for computers, yielding each finding, and save what is found."""
    target = _store(store)
    if scope is ScanScope.NONE:
        yield ScanEventView(
            stage="permission",
            message="Not looking — nothing was permitted.",
            ok=False,
            finished=True,
        )
        return

    kwargs = {"fetch": fetch} if fetch is not None else {}
    for event in discover(scope, host, **kwargs):
        if event.node is not None:
            target.upsert(event.node)
        yield ScanEventView(
            stage=event.stage,
            message=event.message,
            ok=event.ok,
            finished=event.finished,
            done=event.progress[0],
            total=event.progress[1],
        )


def add_node(
    label: str, kind: str, url: str, store: Optional[NodeStore] = None
) -> Outcome:
    """Add a computer by hand. Every field is marked as typed."""
    if not label.strip() or not url.strip():
        return Outcome(
            ok=False,
            summary="Missing details",
            refusal="A computer needs a name and an address.",
        )
    if kind not in {k.value for k in NodeKind}:
        return Outcome(
            ok=False,
            summary="Unknown kind",
            refusal=f"'{kind}' is not one of: {', '.join(k.value for k in NodeKind)}",
        )
    _store(store).upsert(InferenceNode(
        node_id=slugify(label), label=label, kind=NodeKind(kind), url=url,
        provenance={
            "label": Provenance.DECLARED,
            "url": Provenance.DECLARED,
            "kind": Provenance.DECLARED,
        },
    ))
    return Outcome(ok=True, summary=f"Added {label}.")


def forget_node(node_id: str, store: Optional[NodeStore] = None) -> Outcome:
    """Remove a computer."""
    if not _store(store).forget(node_id):
        return Outcome(
            ok=False, summary="Not found",
            refusal=f"Nothing stored called '{node_id}'.",
        )
    return Outcome(ok=True, summary=f"Removed {node_id}.")


def update_field(
    node_id: str, field_name: str, value: str, store: Optional[NodeStore] = None
) -> Outcome:
    """Change one field, marking it as typed by a person."""
    if field_name not in EDITABLE:
        return Outcome(
            ok=False, summary="Not editable",
            refusal=f"'{field_name}' cannot be edited here.",
        )
    target = _store(store)
    nodes, consent = target.load()
    match = next((n for n in nodes if n.node_id == node_id), None)
    if match is None:
        return Outcome(
            ok=False, summary="Not found",
            refusal=f"Nothing stored called '{node_id}'.",
        )
    if field_name == "kind" and value not in {k.value for k in NodeKind}:
        return Outcome(
            ok=False, summary="Unknown kind",
            refusal=f"'{value}' is not one of: {', '.join(k.value for k in NodeKind)}",
        )
    setattr(match, field_name, NodeKind(value) if field_name == "kind" else value)
    match.provenance[field_name] = Provenance.DECLARED
    target.save(nodes, consent)
    return Outcome(ok=True, summary="Saved.")
```

Then add to `src/gui/services/__init__.py`, beside the existing imports:

```python
from src.gui.services.nodes import (
    EDITABLE,
    FieldView,
    NodeListResult,
    NodeRowView,
    ScanEventView,
    add_node,
    forget_node,
    list_nodes,
    save_consent,
    scan,
    update_field,
)
```

and to `__all__`:

```python
    # node management
    "EDITABLE",
    "FieldView",
    "NodeListResult",
    "NodeRowView",
    "ScanEventView",
    "add_node",
    "forget_node",
    "list_nodes",
    "save_consent",
    "scan",
    "update_field",
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `.venv/bin/python -m pytest tests/test_gui_nodes.py tests/test_gui_workflow.py -q`
Expected: PASS. The import-law tests discover the new service file by glob and must accept it.

- [ ] **Step 5: Commit**

```bash
git add src/gui/services/nodes.py src/gui/services/__init__.py tests/test_gui_nodes.py
git commit -m "feat: GUI service layer for node management"
```

---

### Task 8: The Environment tab

**Files:**
- Create: `src/gui/environment_views.py`
- Modify: `src/gui/app.py` (add the tab)
- Test: append to `tests/test_gui_workflow.py`

**Interfaces:**
- Consumes: Task 7.
- Produces: `EnvironmentTab` with `run_list()`, `run_scan(scope, host)`, `on_look()`, `on_add()`, `shown()`, `cards()`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_gui_workflow.py`:

```python
# ------------------------------------------------------- the Environment tab


class TestEnvironmentTab:
    """The fourth tab: telling Fukasawa what computers it can use."""

    def test_the_tab_is_mounted(self, app_window):
        assert hasattr(app_window, "environment_tab")

    def test_empty_state_invites_a_look(self, app_window):
        tab = app_window.environment_tab
        tab.render(services.NodeListResult(ok=True, summary="", rows=[],
                                           consequence="No step can be assigned "
                                                       "to an agent."))
        assert "Look for it" in tab.shown() or "look" in tab.shown().lower()

    def test_the_summary_panel_is_rendered(self, app_window):
        tab = app_window.environment_tab
        tab.render(services.NodeListResult(
            ok=True, summary="", rows=[],
            summary_rows=[("Agent steps can run on", "nothing yet", "")],
            consequence="No step can be assigned to an agent.",
        ))
        assert "nothing yet" in tab.shown()

    def test_a_scan_event_appends_a_line(self, app_window):
        tab = app_window.environment_tab
        tab.append_event(services.ScanEventView(
            stage="reachable", message="Something's listening on port 11434"
        ))
        assert "port 11434" in tab.shown()

    def test_the_tab_never_judges_or_assumes_ownership(self, app_window):
        tab = app_window.environment_tab
        tab.render(services.list_nodes())
        text = tab.shown().lower()
        for word in ["slow", "fast", "powerful", "adequate",
                     "stays with you", "your hardware"]:
            assert word not in text, f"{word!r} on screen"
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `xvfb-run -a .venv/bin/python -m pytest tests/test_gui_workflow.py -q -k Environment`
Expected: FAIL — `AttributeError: 'FukasawaApp' object has no attribute 'environment_tab'`

- [ ] **Step 3: Write the implementation**

```python
# src/gui/environment_views.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""The Environment tab — what computers can run AI for this workflow.

**This module decides nothing.** Every question it can ask is answered by
`src.gui.services`; the code here reads widgets, calls a service, and renders
what comes back.

Two rules from the design govern every string this file produces, and both are
checked by tests:

* **State outputs, never judge them.** Figures with units. No verdicts about
  anybody's hardware.
* **Never assume who owns the work.** The reader may be setting a machine up
  for somebody else.

Scanning runs on the phase-7 worker and its events arrive through the same
queue the Workflow tab drains, so findings appear one at a time rather than as
a block at the end.
"""

import queue
import threading

import customtkinter as ctk

from src.gui import services

PRIMARY = "#A855F7"
MUTED = ("gray45", "gray60")

#: The permission rungs, in the words the design specifies.
SCOPES = [
    ("Just this computer", "I'll check whether AI is running here. "
                           "Nothing leaves this machine."),
    ("A computer I'll name", "You give me its address; I check that one only."),
    ("Every computer on this network", "I'll look at other computers on the same "
                                       "network. Takes about a minute. Some "
                                       "workplaces don't allow this — check first."),
    ("Don't look at anything", "I'll type it in myself."),
]

_POLL_MS = 40


class EnvironmentTab(ctk.CTkFrame):
    """Capture and edit what computers are available."""

    def __init__(self, parent) -> None:
        """Build the tab. Reads nothing until an action runs."""
        super().__init__(parent, fg_color="transparent")
        self.pack(fill="both", expand=True)
        self._results: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._poll_id = None
        self._build()
        self._schedule_poll()

    def _build(self) -> None:
        """Lay out the intro, the actions, and the log."""
        ctk.CTkLabel(
            self,
            text="Fukasawa can run some workflow steps automatically, using AI\n"
                 "on a computer you point it at. Nothing here talks to the cloud.",
            justify="left", anchor="w", wraplength=680,
        ).pack(fill="x", padx=12, pady=(12, 6))

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=12)
        ctk.CTkButton(row, text="Look for it", command=self.on_look).pack(side="left")
        ctk.CTkButton(
            row, text="I'll type it in", command=self.on_add,
            fg_color="transparent", border_width=1,
        ).pack(side="left", padx=8)

        self.log = ctk.CTkTextbox(self, wrap="word", height=200)
        self.log.pack(fill="both", expand=True, padx=12, pady=10)

    # ------------------------------------------------- synchronous operations

    def run_list(self) -> services.NodeListResult:
        """Read every stored computer."""
        return services.list_nodes()

    def run_scan(self, scope, host: str = "") -> list:
        """Run a scan to completion, returning every event."""
        return list(services.scan(scope, host))

    # ------------------------------------------------------------- rendering

    def render(self, result: services.NodeListResult) -> None:
        """Show every computer and the panel that says what follows."""
        self.log.delete("1.0", "end")
        if not result.rows:
            self.log.insert("end", "No computers recorded yet.\n"
                                   "Press \"Look for it\" and I'll check.\n\n")
        for row in result.rows:
            self.log.insert("end", f"{row.label}   {row.url}\n")
            for field in row.fields:
                self.log.insert(
                    "end", f"    {field.label:<22} {field.value:<28} {field.source}\n"
                )
            self.log.insert("end", "\n")

        self.log.insert("end", "What this means when steps run\n")
        for label, value, source in result.summary_rows:
            self.log.insert("end", f"    {label:<32} {value}   {source}\n")
        if result.consequence:
            self.log.insert("end", f"\n    {result.consequence}\n")

    def append_event(self, event: services.ScanEventView) -> None:
        """Add one discovery finding as it arrives."""
        mark = "OK" if event.ok else "--"
        self.log.insert("end", f"  {mark}  {event.message}\n")
        self.log.see("end")

    # -------------------------------------------------------------- handlers

    def on_look(self) -> None:
        """Ask permission, then scan, showing findings as they arrive."""
        from src.schemas.node import ScanScope

        self.log.delete("1.0", "end")
        self.log.insert("end", "Looking on this computer...\n")
        services.save_consent(ScanScope.THIS_MACHINE, "desktop-operator")
        self._in_worker(
            lambda: self.run_scan(ScanScope.THIS_MACHINE), self._show_events
        )

    def on_add(self) -> None:
        """Show what a manual entry needs."""
        self.log.delete("1.0", "end")
        self.log.insert(
            "end",
            "To add one by hand, use:\n"
            "  fukasawa node add --label \"Kitchen Box\" --kind ollama "
            "--url http://10.0.0.9:11434\n",
        )

    def _show_events(self, events) -> None:
        """Render a completed scan, then the current picture."""
        for event in events:
            self.append_event(event)
        self.render(self.run_list())

    # ------------------------------------------------------------- threading

    def _in_worker(self, work, done) -> None:
        """Run work off the UI thread; deliver through the queue."""
        def runner() -> None:
            try:
                result = work()
            except Exception as exc:  # noqa: BLE001 — surfaced, not swallowed
                result = [services.ScanEventView(
                    stage="error", message=f"Something went wrong: {exc}",
                    ok=False, finished=True,
                )]
            self._results.put((result, done))

        self._worker = threading.Thread(target=runner, daemon=True)
        self._worker.start()

    def _schedule_poll(self) -> None:
        """Arm the next queue check. UI thread only."""
        self._poll_id = self.after(_POLL_MS, self._poll)

    def _poll(self) -> None:
        """Deliver finished work, then re-arm."""
        try:
            if not self.winfo_exists():
                self._poll_id = None
                return
        except Exception:  # noqa: BLE001 — a dead interpreter is not alive
            self._poll_id = None
            return
        self.drain()
        self._schedule_poll()

    def drain(self) -> None:
        """Deliver every finished result. Public so tests can flush."""
        while True:
            try:
                result, done = self._results.get_nowait()
            except queue.Empty:
                return
            done(result)

    def destroy(self) -> None:
        """Cancel the poller and let any worker finish."""
        if self._poll_id is not None:
            try:
                self.after_cancel(self._poll_id)
            except Exception:  # noqa: BLE001 — teardown must not raise
                pass
            self._poll_id = None
        worker, self._worker = self._worker, None
        if worker is not None and worker.is_alive():
            worker.join(timeout=5.0)
        super().destroy()

    # ------------------------------------------------------------ test hooks

    def shown(self) -> str:
        """Whatever is currently in the log."""
        return self.log.get("1.0", "end")
```

Then in `src/gui/app.py`, beside the existing tabs:

```python
from src.gui.environment_views import EnvironmentTab
```

```python
        self.tabs.add("Environment")
```

```python
        self.environment_tab = EnvironmentTab(self.tabs.tab("Environment"))
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `xvfb-run -a .venv/bin/python -m pytest tests/test_gui_workflow.py -q`
Expected: PASS, including `TestImportLaw`, which discovers `environment_views.py` by glob and checks it imports only services, stdlib and customtkinter.

- [ ] **Step 5: Commit**

```bash
git add src/gui/environment_views.py src/gui/app.py tests/test_gui_workflow.py
git commit -m "feat: an Environment tab that fills in as it discovers"
```

---

### Task 9: Doctrine tests, documentation, and the phase note

**Files:**
- Modify: `tests/test_hardening.py` (doctrine tests)
- Create: `docs/environment-guide.md`
- Modify: `README.md` (replace the "Known gaps" section), `tasks/backlog.md` (close the node-library item), `docs/release-notes.md`
- Create: `handoffs/implementation/phase-10a-node-capability-completion-note.md`

**Interfaces:**
- Consumes: everything.
- Produces: no code interfaces.

- [ ] **Step 1: Write the failing doctrine tests**

Append to `tests/test_hardening.py`:

```python
class TestNodeDoctrine:
    """What must remain true of node data however the feature evolves."""

    def test_an_exported_brief_never_contains_an_address(self, tmp_path):
        """A shared artifact references a computer by name, never by address."""
        import yaml as _yaml

        from src.foundry.workflow_export import (
            build_cooperative_workflow,
            export_workflow,
        )
        from src.governance.cooperation import assess_workflow
        from src.governance.workflow_promotion import promote
        from src.runtime.ledger import RunLedger

        ledger = RunLedger(str(tmp_path / "d.db"))
        draft = _draft()
        for _ in range(2):
            report = validate_workflow(draft)
            outcome = promote(ledger, draft, report, promoted_by="t")
            draft.maturity = outcome.to_maturity
        accountable = ledger.load_accountable_workflow(draft.workflow_id)
        assessments = assess_workflow(accountable, systems=list(draft.systems))
        cooperative = build_cooperative_workflow(accountable, assessments,
                                                 approved_by="t")
        brief = export_workflow(cooperative, accountable)
        text = _yaml.safe_dump(brief.model_dump(mode="json"))

        for marker in ["http://", "https://", ":11434", ":8081"]:
            assert marker not in text, (
                f"an exported brief carries {marker!r} — addresses are local, "
                f"and a shared artifact must reference a computer by name"
            )

    def test_no_private_address_ships_in_the_tree(self):
        """Nothing about any operator's network is baked into the product."""
        import re

        pattern = re.compile(
            r"\b(192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+"
            r"|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)\b"
        )
        allowed = {"192.168.1.50", "10.0.0.9"}  # documentation examples only
        offenders = []
        for path in ROOT.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".md", ".yaml", ".yml"}:
                continue
            if any(part in {".git", ".venv", "build", "dist"} for part in path.parts):
                continue
            for found in pattern.findall(path.read_text(encoding="utf-8", errors="ignore")):
                literal = found if isinstance(found, str) else found[0]
                if literal not in allowed:
                    offenders.append(f"{path.relative_to(ROOT)}: {literal}")
        assert not offenders, f"private addresses in the shipped tree: {offenders[:5]}"

    def test_the_store_defaults_to_no_permission(self):
        """Nothing is scanned until somebody says so."""
        from src.schemas.node import ScanConsent, ScanScope

        assert ScanConsent().scope is ScanScope.NONE
```

- [ ] **Step 2: Run them and fix whatever they catch**

Run: `.venv/bin/python -m pytest tests/test_hardening.py -q`
Expected: PASS. If `test_no_private_address_ships_in_the_tree` fails, the address it names must be removed or added to `allowed` with a comment saying why it is a documentation example.

- [ ] **Step 3: Write the operator guide**

Create `docs/environment-guide.md` covering, in the design's register: what the Environment tab is for, the four permission rungs and what each opens, what "found it / measured / you told me / not sure" mean, how to add a computer by hand, that the store is local and never shared, and the CLI equivalents. Include the note that video memory is reported as a floor and why.

- [ ] **Step 4: Update the README**

Replace the "Bring your own inference nodes" text under `## Known gaps` with a short section under `## Documentation` pointing at `docs/environment-guide.md`, and delete the two bullets that are now closed. Leave the third — capability matching — and move it under a `### Still open` heading naming it as phase 10b.

- [ ] **Step 5: Close the backlog item**

In `tasks/backlog.md`, under "Node library", tick the first two boxes and add a line: `Closed by phase 10a, 2026-08-23. The third item (capability matching) is phase 10b and remains open.`

- [ ] **Step 6: Add a release-notes entry**

Under `### Known limitations` in `docs/release-notes.md`, replace the node-library bullet with one that says registering computers is now supported, and that matching capabilities to steps is not yet.

- [ ] **Step 7: Write the completion note**

Create `handoffs/implementation/phase-10a-node-capability-completion-note.md` using the §14 template: scope completed, files changed, tests run and results, decisions made, assumptions, known limitations, new risks or defects, recommended next action, exact starting point for the next agent.

- [ ] **Step 8: Run the whole suite both ways**

```bash
xvfb-run -a .venv/bin/python -m pytest -q
.venv/bin/python -m pytest -q
```
Expected: PASS both ways, with roughly 100 more tests than the 712/672 baseline and no regressions.

- [ ] **Step 9: Confirm no FROZEN file was touched across the whole branch**

```bash
git diff --name-only main...HEAD | grep -E "src/kernel/|src/security/|src/schemas/graph|src/schemas/bundle|src/foundry/generator|src/runtime/state_machine|src/runtime/bundle" || echo "no frozen path touched"
```
Expected: `no frozen path touched`

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "docs: environment guide, doctrine tests, and the phase 10a note"
```

---

## Self-Review

**Spec coverage.** §3.2 → Task 8 Step 3. §3.3 → Tasks 4, 6, 8. §3.4 → Task 4 (stream) rendered by Tasks 6 and 8. §3.5 → Task 7 `_row`. §3.6 → Task 2. §3.7 → Task 6. §4 → Task 1. §4.1 → Tasks 1, 2, 3. §5.0 → Tasks 3–5 file locations, verified in Tasks 5 and 9. §5.1 → Task 4. §5.2 → Task 4 `candidate_addresses`. §5.3 → Task 3. §5.4 → Task 3 docstring. §5.5 → Task 3 Step 5. §6 → Task 5. §6.0 → Task 5 `upsert`. §6.1 → Task 9. §7 → Task 6. §8 → Tasks 7, 8. §9 → distributed, with the copy rules in Tasks 2, 6, 8 and doctrine in Task 9.

**Gap found and closed:** §5.2's `LOCAL_NETWORK` sweep is *declared* in `ScanScope` and offered in the CLI and desktop, but no task implements the sweep itself — `candidate_addresses` raises `ConsentRefused` for it. This is deliberate and must be stated plainly to the operator rather than discovered: **the /24 sweep is not implemented in this plan.** Choosing it currently yields a refusal. Implementing it is a self-contained follow-on (derive the local /24, bounded concurrency, progress events) and belongs in its own task once the three simpler rungs are proven. Task 6's `_scope_from` accepts it, so the refusal is legible rather than a crash.

**Placeholder scan:** no TBD/TODO. Every code step has real code. Task 9 Steps 3 and 7 describe documents rather than showing them in full — acceptable, since they are prose deliverables whose required content is enumerated.

**Type consistency:** `InferenceNode.source_of` used in Tasks 2, 6, 7. `max_context_length` used in Tasks 2, 6, 7. `Provenance` values consistent throughout. `Outcome` imported from `src.gui.services.workflow` in Task 7, matching the existing dataclass. `ScanEventView` produced in Task 7 and consumed in Task 8. `DiscoveryEvent.progress` is a tuple in Task 4 and unpacked into `done`/`total` in Task 7.
