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
