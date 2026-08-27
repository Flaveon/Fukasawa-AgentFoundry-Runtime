# Fukasawa-AgentFoundry Runtime

[![build](https://github.com/Flaveon/Fukasawa-AgentFoundry-Runtime/actions/workflows/build.yml/badge.svg)](https://github.com/Flaveon/Fukasawa-AgentFoundry-Runtime/actions/workflows/build.yml)

A local-first workflow governance runtime for work shared between people and AI
agents. It captures a workflow as it actually happens, tells you
deterministically where the accountability holes are, refuses to promote it
until they are closed, and only then decides which steps an agent should touch.

```
map → validate → repair → cooperate → export
```

Not a LangChain clone, not a prompt manager, not a multi-agent swarm. **No model
is involved in any authoritative path** — validation, promotion eligibility,
executor classification, export and persistence are all deterministic, which is
what makes the result auditable and arguable.

## What it does

| | |
|---|---|
| **Capture** | record a process including the parts nobody wrote down — unwritten rules, observed exceptions, pain points. A draft full of gaps still saves. |
| **Validate** | 16 deterministic rules across structure, accountability, information, reasoning load and resilience. Every finding names a rule, a location, a severity and a remedy. |
| **Repair or accept** | fix it, or consciously accept an advisory finding with a name, a time and a reason — all three mandatory. |
| **Promote** | an eight-state maturity ladder, one step at a time, producing a traceable artifact rather than mutating the source. |
| **Assess cooperation** | seven executor classes chosen by a published decision table. Safety floors are one-directional: you may always pull work back toward a person. |
| **Export** | flatten the approved result into a `WorkflowBrief` the existing runtime executes, preserving human approval as a state the ledger records. |

Built on the runtime that was already here and is consumed unchanged: typed
workflow briefs, task-depth classification, process capsules, handoff contracts,
human review gates, non-conformance review, agent package generation, simulation
and eval loops, durable run history, and optional model adapters.

## Origins

Two GPT knowledge packs, distilled into executable infrastructure. **FukasawaGPT**
owns workflow architecture and complexity control; **Agent Foundry** owns agent
package generation, simulations, maturity tracking and deployment packaging.
This repository is the layer that makes them run.

Their source material lives beside this repository (`../FukasawaGPT/`,
`../agent_foundry_gpt_builder_brief_v_1 (1).md`,
`../Project_Directory_Standard.md`) and is **historical input, not a
dependency** — nothing here reads them at build or run time.

LangGraph and DSPy are useful comparison points, not governing architecture.
Borrow the runtime ideas, not the worldview.

## Quick start

Requires Python 3.11+ (3.12 recommended).

```bash
uv venv --python 3.12 .venv
uv pip install -e '.[dev,gui]'
```

Walk the pilot — a real workflow with real problems:

```bash
.venv/bin/python -m src.cli workflow validate examples/workflows/substack-publication/observed-workflow.yaml
```

```
substack-publication — 24 finding(s), rule set v1
...
14 unresolved blocking finding(s).
```

That is the expected result. The capture is honest and honest captures have
holes in them — and it still saved. **"Blocking" means blocking promotion**, not
capture. `docs/pilot-walkthrough.md` runs the whole sequence with real output.

For the desktop app:

```bash
.venv/bin/python -m src.gui.app
```

### The commands

```bash
fukasawa workflow init <workflow-id>            # a draft skeleton to fill in
fukasawa workflow validate <draft.yaml>         # the 16 deterministic rules
fukasawa workflow findings <draft.yaml>         # what is outstanding
fukasawa workflow accept-risk <draft.yaml>      # accept an advisory finding, with a reason
fukasawa workflow promote <draft.yaml>          # one step up the maturity ladder
fukasawa workflow assess-cooperation <workflow-id>   # who should perform each step
fukasawa workflow build-cooperative <workflow-id>    # assign executors, approve them
fukasawa workflow export-agent-brief <workflow-id>   # flatten to a runnable brief
fukasawa workflow status <workflow-id>               # where am I
```

The split is not arbitrary: the first five take a **file**, because the draft's
content lives on disk and you are still editing it. The last four take a
**workflow id**, because by then the artifact they act on is in the ledger.

Add `--json` to any of them. Exit codes: `0` ok, `1` user error, `2` blocking
findings, `3` a doctrine refusal.

### Tests

```bash
xvfb-run -a .venv/bin/python -m pytest -q     # 694 passed, 1 skipped
.venv/bin/python -m pytest -q                 # 654 passed, 41 skipped
```

Run it **both ways** — the plain invocation skips 40 view tests that need a
display, and one desktop defect only ever appeared under Xvfb.

### A standalone binary

```bash
uv pip install -e '.[build]'
PYTHON=.venv/bin/python ./packaging/build.sh
./dist/fukasawa --help     # CLI mode; no arguments opens the desktop app
```

One file, ~30 MB, no Python needed by the recipient. See
`docs/packaging-guide.md`.

## Documentation

Start with **`docs/lifecycle-overview.md`** — what this is and why the stages
are in that order.

| | |
|---|---|
| `docs/lifecycle-overview.md` | the product in one page |
| `docs/pilot-walkthrough.md` | the whole lifecycle, run for real |
| `docs/validator-rule-catalog.md` | what the 16 rules check |
| `docs/schema-reference.md` | the contracts |
| `docs/promotion-state-reference.md` | what each maturity state means |
| `docs/cooperation-classification-guide.md` | how executors are chosen |
| `docs/cli-guide.md` · `docs/desktop-guide.md` | the two surfaces |
| `docs/migration-notes.md` · `docs/packaging-guide.md` · `docs/release-notes.md` | shipping it |

Contributor guides live inside the reference they extend:
`validator-rule-catalog.md` § *Adding a rule*, and
`cooperation-classification-guide.md` § *Adding or changing a classification
policy*.

### Documents that are historical, not current

These date from the 2026-07-19 planning package and have **not** been updated
across the nine implementation phases. They record what was intended before the
code existed, and where they disagree with the code, **the code is right**:

`AGENTS.md` · `roadmap.md` · `brief/project-brief.md` · `specs/*.md` ·
`docs/architecture.md` · `docs/product-principles.md` · `docs/dependencies.md` ·
`docs/evaluation-strategy.md` · `registry/prompt-module-registry.yaml`

One thing they describe is a draft that no code reads: the **prompt/module
registry** (`registry/prompt-module-registry.yaml`, `schema_version: 0.1`).
`roadmap.md` also uses a *different* phase numbering from the one this release
followed — see `handoffs/handoff-master.md`.

The **node library** those documents mention is a different matter: it is
**missing, not obsolete**. See [Known gaps](#known-gaps).

`docs/source-to-contract-map.md` exists to detect exactly this kind of drift.

## Directory map

```text
Fukasawa-AgentFoundry-Runtime/
|-- src/
|   |-- cli.py                 # the CLI, including the workflow sub-app
|   |-- resources.py           # bundled-file resolution for the binary
|   |-- schemas/               # canonical Pydantic contracts
|   |-- governance/            # validator rules, promotion, cooperation
|   |-- runtime/               # state machine, ledger, review gates
|   |-- foundry/               # agent package generation, export
|   |-- gui/                   # CustomTkinter desktop + its service layer
|   |-- kernel/                # model adapters (the only network surface)
|   `-- security/              # signing and trust
|-- tests/                     # 695 tests
|-- examples/workflows/substack-publication/   # the pilot, all 8 artifacts
|-- docs/                      # the documentation above
|-- handoffs/                  # the master handoff, ADRs, phase notes, reviews
|-- packaging/                 # PyInstaller spec, build script, runtime hook
`-- tasks/backlog.md
```

## Known gaps

### Bring your own inference nodes

This is built to be handed to someone else, and that person runs their own
hardware. Today the runtime resolves **named model endpoints** — a graph says
`endpoint: gpu-node` and each operator's config decides what that means, so a
shared workflow never carries anyone's IP addresses:

```bash
fukasawa model list          # what is configured
fukasawa model test gpu-node # does it answer
```

Two limits, and they matter most for exactly the audience this is for:

**Adding a node means hand-editing YAML at a path nothing tells you about.**
Endpoints live in `$FUKASAWA_HOME/model_endpoints.yaml` (default
`~/.fukasawa/model_endpoints.yaml`), modelled on
`config/model_endpoints.example.yaml`. There is no `model add`, and no desktop
screen for it. A person who was handed the binary has neither the repository nor
that path.

**An endpoint has no capabilities.** It is a name, a kind (`ollama` or
`llamacpp`) and a URL — nothing about which models it serves, how much context
it has, what hardware is behind it, or what work it is fit for. So nothing can
answer the question the cooperation layer implicitly raises: *this step could be
automated, but can this operator's hardware actually run it?*
`CooperationAssessment.required_tools` and `StepAssignment.runtime_requirements`
are free strings today, checked by nobody.

Until both are closed, "an agent may perform this step" is a judgement about the
**work**, not a promise that your machines can do it. Tracked in
`tasks/backlog.md`.

## Status

**v1.0 release candidate.** The human & cooperative workflow lifecycle is
complete across both surfaces: capture, validate, repair, promote, assess
cooperation, build, export. Release gates A–F are met.

Gate G is open on two items that need a person rather than an agent — an
independent verification pass, and a review of three commits on phase-owned
files. Both are recorded in `docs/release-notes.md` under *Known limitations*
and in `handoffs/implementation/release-verification-report.md`.

The governing specification is `handoffs/handoff-master.md`. Every document
derived from it is a lossy summary; when they disagree, the master handoff wins.
