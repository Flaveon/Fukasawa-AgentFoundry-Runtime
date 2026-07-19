# Roadmap

## Phase 0: Discovery And Contract Audit

Goal: turn existing Fukasawa and Agent Foundry doctrine into a complete runtime contract inventory.

Deliverables:

- canonical glossary
- list of runtime objects
- source-to-schema trace map
- one selected pilot workflow
- first non-conformance examples from real agent handoff failures

Candidate pilot workflows:

- Oldowan Articles cataloging and review
- Q2C production handoff review
- Agent package creation from a Fukasawa Workflow Design Brief

Exit criteria:

- one pilot workflow is chosen
- every required runtime object has a draft schema owner
- missing source doctrine is listed as open questions
- no major contradiction remains between Fukasawa and Agent Foundry responsibilities

## Phase 1: Schema And State Runtime

Goal: implement the local state and validation layer.

Deliverables:

- `WorkflowDesignBrief` schema
- `ProcessCapsule` schema
- `ObservationPacket` schema
- `NonConformanceRecord` schema
- `RuntimeState` schema
- file-backed run ledger
- validation CLI prototype

Runtime behavior:

- validate a workflow brief
- reject incomplete handoffs
- persist run state outside chat
- record state transitions
- produce human-readable status summaries

Exit criteria:

- a real workflow brief can validate or fail with clear errors
- a run can be resumed from persisted state
- handoff files include artifact paths, next action, and review gate status

## Phase 2: Agent Package Generator

Goal: make Agent Foundry consume validated workflow briefs and produce bounded agent packages.

Deliverables:

- agent package template
- process capsule generator
- `SKILL.md`, `SOUL.md`, `CONTRACT.md`, `evals.yaml`, `simulations.yaml`, `learning_log.md` templates
- package validation command
- C-Pax path profile injection
- deployment method metadata

Runtime behavior:

- read an approved workflow brief
- generate one or more agent package directories
- enforce depth-level boundaries
- require escalation and evaluation fields
- emit a build handoff for implementation or review

Exit criteria:

- generated packages pass schema validation
- package output can be used by a human or Codex without hidden context
- generated agents cannot silently exceed declared depth level

## Phase 3: Evaluation And Governance Loop

Goal: make promotion, prompt changes, and workflow changes evidence-based.

Deliverables:

- eval case format
- handoff quality checks
- scope compliance checks
- escalation correctness checks
- non-conformance capture CLI
- learning log integration
- prompt/module registry draft

Runtime behavior:

- score handoff completeness
- detect missing evidence
- detect unsupported completion claims
- compare output schema conformance
- recommend simplification before adding process
- mark maturity: draft, tested, validated

Exit criteria:

- a process can be promoted or blocked based on evidence
- non-conformance records produce concrete process changes
- repeated failures are visible in the run ledger

## Phase 4: Orchestration Kernel

Goal: add a small state graph for workflows that need multiple nodes, retries, or human gates.

Deliverables:

- node interface
- transition rules
- checkpoint/resume behavior
- human approval gate
- retry and blocked-state handling
- adapter interface
- pilot workflow graph

Runtime behavior:

- run deterministic nodes
- call agent nodes through adapters
- pause at human gates
- resume after approval or correction
- emit final handoff and trace

Exit criteria:

- one pilot workflow runs end-to-end through persisted states
- failed nodes produce non-conformance records or blocked-state artifacts
- state graph remains inspectable without needing a framework UI

## Phase 5: Distributable Application

Goal: wrap the proven runtime in a user-facing tool.

Possible forms:

- CLI first
- local FastAPI service
- lightweight web dashboard
- desktop app later
- optional MCP server or GPT Action bridge

Deliverables:

- installable package
- local project database
- workflow editor
- run history viewer
- schema validation UI
- agent package builder UI
- export/import format

Exit criteria:

- new user can create a workflow brief, validate it, generate an agent package, run an eval, and review a trace without editing raw files
- core runtime remains usable without the UI

## Phase 6: Optional Advanced Optimization

Goal: add DSPy-like prompt optimization only after enough reviewed examples exist.

Deliverables:

- prompt/module registry
- reviewed examples dataset
- metrics for each module
- optimizer experiment report
- promote/reject decision record

Exit criteria:

- optimized module outperforms baseline on held-out reviewed cases
- cost and complexity are justified
- fallback baseline remains available
