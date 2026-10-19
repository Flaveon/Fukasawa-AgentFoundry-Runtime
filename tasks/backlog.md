# Backlog

> **Reconciled 2026-10-17** against `main` at `95d8867`. A box is ticked only where a
> named carrier exists and a test exercises it; the carrier follows in italics. The
> Phase 0–4 lists were written before Phase 1 and had not been updated since, so most
> of their unticked boxes described shipped work. Items that are partial, proposed,
> or waiting on an owner decision stay unticked and say so. Run record:
> `handoffs/implementation/2026-10-17-backlog-run-plan-v1.0.md`.

## Phase 0

- [ ] Create `docs/glossary.md`. *Not done — no glossary exists (verified 2026-10-17).*
- [x] Create `docs/source-to-contract-map.md`.
- [x] Choose pilot workflow. *Substack publication: `examples/workflows/substack-publication/`, walked through in `docs/pilot-walkthrough.md`.*
- [x] Convert one real workflow into a `WorkflowDesignBrief`. *Carried as `HumanWorkflowDraft` (`src/schemas/human_workflow.py:407`) — renamed, and narrower than the doctrine's brief; see `docs/source-to-contract-map.md`. Pilot draft in `examples/workflows/substack-publication/`.*
- [ ] Identify all required schemas from source doctrine. *Partial: `src/schemas/` carries most, but `docs/source-to-contract-map.md` records doctrine structures still missing or weakened (complexity budget, structured non-conformance diagnosis, per-level output shapes). Reopened by issue #27, not closed by it.*
- [ ] Record open product questions. *Partial: scattered across ADR proposals, `README.md` "still open", completion notes and issue #27 — no single register.*

## Phase 1

- [x] Decide Pydantic vs JSON Schema. *ADR-001, approved with revisions (`handoffs/reviews/approved-adrs.md`): Pydantic v2 canonical, JSON Schema generated (`src/schemas/export_jsonschema.py`).*
- [x] Create runtime source folder. *`src/runtime/`.*
- [x] Implement `WorkflowDesignBrief` model. *As `HumanWorkflowDraft` — see the Phase 0 note above; tests in `tests/test_workflow_contracts.py`.*
- [x] Implement `ProcessCapsule` model. *`src/schemas/process_capsule.py`; exercised by `tests/test_state_machine.py`, `tests/test_review_gate.py`.*
- [x] Implement `ObservationPacket` model. *`src/schemas/observation_packet.py`; `tests/test_schemas.py`. Still flagged draft pending human review.*
- [x] Implement `RuntimeState` model. *`src/schemas/runtime_state.py`; `tests/test_schemas.py`.*
- [x] Implement file-backed run ledger. *SQLite, append-only: `src/runtime/ledger.py`; `tests/test_state_machine.py`.*
- [x] Add CLI validation commands. *`fukasawa validate brief|capsule`, `fukasawa workflow validate|findings` (`src/cli.py`); `tests/test_workflow_cli.py`.*
- [x] Add tests for valid and invalid artifacts. *`tests/test_schemas.py`, `tests/test_workflow_contracts.py`.*

## Phase 2

- [x] Create agent package templates. *Generated rather than static: `src/foundry/generator.py`.*
- [x] Generate sample package for pilot workflow. *`examples/packages/publisher-agent/`, `examples/packages/writer-agent/`.*
- [x] Validate package schema. *`src/schemas/agent_package.py`, `src/foundry/validator.py`; `tests/test_foundry.py`.*
- [x] Add C-Pax numbered directory profile. *`detect_workspace_profile` in `src/foundry/generator.py:73`; `tests/test_foundry.py`.*
- [x] Add deployment method metadata. *`DeploymentMethod` in `src/schemas/agent_spec.py:22`.*
- [x] Add package-generation tests. *`tests/test_foundry.py`.*

## Phase 3

- [x] Define eval case YAML. *`src/schemas/eval_case.py`; examples in `examples/evals/`.*
- [x] Implement handoff completeness scoring. *`check_handoff_completeness`, `src/governance/checks.py:40`; `tests/test_governance.py`.*
- [x] Implement depth compliance scoring. *`check_depth_compliance`, `src/governance/checks.py:105`.*
- [x] Implement escalation correctness scoring. *`check_escalation_correctness`, `src/governance/checks.py:143`.*
- [ ] Implement non-conformance writer. *Partial: `NonConformanceRecord` (`src/schemas/non_conformance.py`) and `fukasawa nonconformance` commands exist, but carry free text where the doctrine's corrective-action template asks for a structured diagnosis — `docs/source-to-contract-map.md`, issue #27.*
- [x] Add maturity transition checks. *Agents: `src/governance/maturity.py`; workflows: `src/governance/workflow_promotion.py`; `tests/test_workflow_promotion.py`, `tests/test_governance.py`.*
- [ ] Collect reviewed examples. *Partial: the Substack pilot exists, but no set of examples has a recorded human review. Issue #27's real Q2C case would be the first.*

## Phase 4

- [x] Keep CLI as baseline interface. *`src/cli.py`; the desktop calls the same services (ADR-007).*
- [x] Decide app wrapper: FastAPI, local web UI, desktop, MCP, or GPT Action backend. *Desktop (CustomTkinter) over a service layer — ADR-007, approved with revisions.*
- [x] Add project initialization command. *`fukasawa workflow init` (`src/cli.py`); `tests/test_workflow_cli.py`.*
- [x] Add run history viewer. *`fukasawa history`, `fukasawa workflow status`; desktop lifecycle "Runs" stage.*
- [x] Add export/import. *`fukasawa bundle export|inspect|import` (signed), `workflow export-agent-brief`; `tests/test_bundle.py`, `tests/test_workflow_export.py`.*
- [x] Write operator docs. *`docs/cli-guide.md`, `docs/desktop-guide.md`, `docs/environment-guide.md`, `docs/pilot-walkthrough.md` and others.*

## Research

- [ ] Prototype LangGraph only after the local state machine becomes cumbersome.
- [ ] Prototype DSPy only after reviewed prompt/module eval examples exist.
- [ ] Compare SQLite and DuckDB for run ledger plus analytics.
- [ ] Evaluate whether existing C-Pax directory standards need a runtime-specific profile. *Open: a C-Pax profile is injected into generated packages, but no evaluation of the standard itself is recorded.*

## Outcome Evaluation (post-release — see ADR-008)

The governance checks measure whether a workflow *behaved* correctly. Nothing
yet measures whether the optimized workflow *produced better work*. Both halves
are needed before "the optimization worked" is a claim rather than a hope.

- [ ] Adopt `smevals` (MIT, external peer tool — no import, no vendoring) as the
      outcome-measurement harness. *Partial: an optional subprocess adapter exists
      (`src/governance/smevals_adapter.py`, `docs/smevals-adapter.md`); it compiles an
      artifact-echo runner and has not run a real A/B loop.*
- [ ] Build the first A/B experiment: identical model and tasks, baseline vs
      Fukasawa-optimized workflow configuration, one grader. Model held constant
      as the control; the workflow configuration is the variable under test.
- [ ] Use the Substack pilot as the first subject — it already has a captured
      observed workflow and will have an optimized export.
- [ ] Update `docs/evaluation-strategy.md` to name the two halves and say which
      tool covers which.
- [ ] Disambiguate vocabulary in docs: "workflow run" vs "smevals run",
      "governance eval" vs "outcome eval".
- [ ] Only after outcome metrics exist: revisit whether outcome evidence should
      inform agent maturity promotion (separate ADR; deterministic checkers
      only — never an LLM judge in an authoritative path).
- [ ] Never use outcome grades to select a model. That is not what they measure.

## Validator rule policy — from the Gate C false-positive review (2026-08-21)

Recorded rather than done: both are decisions about *detection policy*, which
belongs to whoever owns the rule set, not to a review pass. Full reasoning and
the evidence in `handoffs/reviews/gate-c-false-positive-review.md`.

- [ ] `MEMORY_PHRASES` contains `undocumented`, a bare adjective that attaches
      to anything — it fires on "the API returns an undocumented field" and
      "undocumented behaviour in the vendor firmware", neither of which is a
      human memory dependency. Every other phrase in the list names a human
      relationship to knowledge. Removing it would also drop a real true
      positive ("the threshold is undocumented"), so this is a trade, not a fix.
- [ ] `MEMORY_PHRASES` also contains `remembers`, which fires on machines
      ("the test rig remembers the last calibration", "the cache remembers the
      previous response").
- [ ] HW-013's phrase list is English and literal — it matches "it's all in
      Dave's head" but not "Dave is the only one who knows". Carried from
      phase 2, unchanged by the Gate C review.
- [ ] Grok Build's adversarial fixture pass (master handoff §11.4) has still
      not happened. It would cheaply strengthen the four-domain guard set the
      Gate C review established.

## Node library — user-supplied inference nodes and capabilities

**Recorded 2026-08-23, operator-stated.** Not stale planning text: a missing
requirement, and the reason it is missing matters.

> "The node library is missing because we are building a consumer-facing
> product that is not intended solely for private use. The user needs to input
> local inference nodes and capabilities."

A private tool can hardcode its operator's hardware. A product that ships to
other people cannot: the person who receives it runs their own machines, and
the runtime has to learn what they have from them.

### What exists today

`ModelEndpointRegistry` resolves **named endpoints** from
`$FUKASAWA_HOME/model_endpoints.yaml` (default `~/.fukasawa/`), merged over two
localhost defaults. A graph says `endpoint: gpu-node`; each operator's config
decides what that resolves to, so a shared workflow never carries anyone's IP
addresses. `fukasawa model list` and `model test` inspect it.

That naming indirection is the right foundation and should be kept.

### What is missing

- [x] **No way to add a node from the product.** Adding one means hand-writing
      YAML at a path that, until phase 9, appeared in exactly one line of source
      and no user-facing document. There is no `model add`, no `model remove`,
      no desktop screen. Someone handed the binary has neither the repository
      nor the path. *(Phase 9 made `model list` print the path and a template —
      that is a stopgap, not the feature.)*
- [x] **An endpoint carries no capabilities.** It is `name`, `kind`
      (`ollama` | `llamacpp`), `url`. Nothing about which models it serves,
      context length, VRAM, quantisation, throughput, or what work it is fit
      for. A capability model is the substantive half of this item.
- [ ] **Capabilities are not connected to cooperation assessment.**
      `CooperationAssessment.required_tools` and
      `StepAssignment.runtime_requirements` are free strings that nothing
      checks. So the runtime can classify a step
      `AGENT_EXECUTED_HUMAN_SUPERVISED` and hand the operator a workflow no
      machine they own can run.
- [x] **Nothing discovers what a node can do.** Both backends can be asked —
      Ollama's `/api/tags`, llama.cpp's `/v1/models` — so a `model discover`
      that populates capabilities from a live node is achievable without
      asking the user to type model names by hand.

**Closed by phase 10a, 2026-09-11** — three of the four boxes above:
`fukasawa node scan|list|show|add|forget|consent`, the desktop's Environment
tab, and computers usable as endpoints by name (`docs/environment-guide.md`).
The third box — capabilities connected to cooperation assessment — is phase
10b and remains open. So does sweeping a whole network, which is offered and
answered as not built yet.

### Why this is the honest framing

The cooperation layer's promise today is a judgement about the **work**: this
step needs this much judgment, carries this much risk, is this reversible. It is
*not* a promise that the operator's hardware can execute the result. Those are
different claims and the product currently blurs them. Closing this gap is what
would let `AutomationReadiness` mean "ready **here**, on your machines" rather
than "ready in principle".

### Constraints to preserve

- Endpoints stay **named**, never addressed by IP in a shared artifact.
- Capability data is **per-operator local config**, never committed and never in
  an exported brief — it describes someone's house.
- No LLM in the matching path. Whether a node can run a step is a deterministic
  comparison, and it must stay explainable.
- The runtime must still work with **zero** configured nodes: every step stays
  with a person, which is already the correct default.
