# Backlog

## Phase 0

- [ ] Create `docs/glossary.md`.
- [x] Create `docs/source-to-contract-map.md`.
- [ ] Choose pilot workflow.
- [ ] Convert one real workflow into a `WorkflowDesignBrief`.
- [ ] Identify all required schemas from source doctrine.
- [ ] Record open product questions.

## Phase 1

- [ ] Decide Pydantic vs JSON Schema.
- [ ] Create runtime source folder.
- [ ] Implement `WorkflowDesignBrief` model.
- [ ] Implement `ProcessCapsule` model.
- [ ] Implement `ObservationPacket` model.
- [ ] Implement `RuntimeState` model.
- [ ] Implement file-backed run ledger.
- [ ] Add CLI validation commands.
- [ ] Add tests for valid and invalid artifacts.

## Phase 2

- [ ] Create agent package templates.
- [ ] Generate sample package for pilot workflow.
- [ ] Validate package schema.
- [ ] Add C-Pax numbered directory profile.
- [ ] Add deployment method metadata.
- [ ] Add package-generation tests.

## Phase 3

- [ ] Define eval case YAML.
- [ ] Implement handoff completeness scoring.
- [ ] Implement depth compliance scoring.
- [ ] Implement escalation correctness scoring.
- [ ] Implement non-conformance writer.
- [ ] Add maturity transition checks.
- [ ] Collect reviewed examples.

## Phase 4

- [ ] Keep CLI as baseline interface.
- [ ] Decide app wrapper: FastAPI, local web UI, desktop, MCP, or GPT Action backend.
- [ ] Add project initialization command.
- [ ] Add run history viewer.
- [ ] Add export/import.
- [ ] Write operator docs.

## Research

- [ ] Prototype LangGraph only after the local state machine becomes cumbersome.
- [ ] Prototype DSPy only after reviewed prompt/module eval examples exist.
- [ ] Compare SQLite and DuckDB for run ledger plus analytics.
- [ ] Evaluate whether existing C-Pax directory standards need a runtime-specific profile.

## Outcome Evaluation (post-release — see ADR-008)

The governance checks measure whether a workflow *behaved* correctly. Nothing
yet measures whether the optimized workflow *produced better work*. Both halves
are needed before "the optimization worked" is a claim rather than a hope.

- [ ] Adopt `smevals` (MIT, external peer tool — no import, no vendoring) as the
      outcome-measurement harness.
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

- [ ] **No way to add a node from the product.** Adding one means hand-writing
      YAML at a path that, until phase 9, appeared in exactly one line of source
      and no user-facing document. There is no `model add`, no `model remove`,
      no desktop screen. Someone handed the binary has neither the repository
      nor the path. *(Phase 9 made `model list` print the path and a template —
      that is a stopgap, not the feature.)*
- [ ] **An endpoint carries no capabilities.** It is `name`, `kind`
      (`ollama` | `llamacpp`), `url`. Nothing about which models it serves,
      context length, VRAM, quantisation, throughput, or what work it is fit
      for. A capability model is the substantive half of this item.
- [ ] **Capabilities are not connected to cooperation assessment.**
      `CooperationAssessment.required_tools` and
      `StepAssignment.runtime_requirements` are free strings that nothing
      checks. So the runtime can classify a step
      `AGENT_EXECUTED_HUMAN_SUPERVISED` and hand the operator a workflow no
      machine they own can run.
- [ ] **Nothing discovers what a node can do.** Both backends can be asked —
      Ollama's `/api/tags`, llama.cpp's `/v1/models` — so a `model discover`
      that populates capabilities from a live node is achievable without
      asking the user to type model names by hand.

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
