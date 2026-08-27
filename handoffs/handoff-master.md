# Fukasawa Human & Cooperative Workflow Runtime
## Agent Development Master Handoff
**Version:** 1.0  
**Modified:** 2026-07-24  
**Repository:** `Flaveon/Fukasawa-AgentFoundry-Runtime`  
**Target branch:** `feature/human-cooperative-workflow-runtime`  
**Release objective:** Deliver a release-ready Human Workflow Validator/Builder and Cooperative Workflow Builder integrated into the existing mixed Python/TypeScript runtime and CustomTkinter desktop application.

---

## 1. Mission

Extend the existing Fukasawa-AgentFoundry Runtime so a user can:

1. Capture an observed human workflow.
2. Validate its structure, accountability, information requirements, reasoning load, and resilience.
3. Resolve or explicitly accept findings.
4. Promote the workflow into an Accountable Workflow.
5. Assess each step for appropriate human/AI cooperation.
6. Generate an approved Cooperative Workflow.
7. Export bounded agent responsibilities into the existing Fukasawa Workflow Design Brief and Agent Foundry package path.
8. Complete the workflow through both CLI and the existing Phase 5E CustomTkinter desktop application.
9. Preserve existing behavior and pass the current test suite baseline of **113 passed, 4 skipped** before new tests are added.

The governing sequence is:

```text
Observed Human Workflow
        ↓
Validated Accountable Workflow
        ↓
Cooperative Human–AI Workflow
        ↓
Executable Fukasawa Runtime
```

The architectural rule is:

> Human workflow truth comes first. Accountability comes second. Cooperation comes third. Execution comes last.

---

## 2. Definition of Done

The release is complete only when all of the following are true.

### 2.1 Functional

A user can:

- Create or import an observed human workflow.
- Validate it and receive deterministic, location-specific findings.
- View blocking and non-blocking findings.
- Correct a workflow or consciously accept a non-blocking risk with rationale.
- Promote a qualifying workflow to `AccountableWorkflow`.
- Generate a `CooperationAssessment` for every executable step.
- Review and approve executor classifications.
- Build a `CooperativeWorkflow`.
- Export compatible content into the existing `WorkflowDesignBrief` and Agent Foundry pipeline.
- Save, reload, and resume all workflow stages.
- Perform the core lifecycle from the CLI.
- Perform the same core lifecycle from the CustomTkinter desktop app.

### 2.2 Quality

- Existing tests remain green.
- New Python and TypeScript tests cover contracts, validation, transitions, serialization, exports, and failure modes.
- Every blocking validation rule has at least one positive and one negative test.
- Cross-language fixtures prove Python and TypeScript agree on serialized contract shapes.
- No undocumented network dependency is required.
- No LLM is required for deterministic validation.
- AI-assisted suggestions are optional and clearly separated from authoritative validation.
- Invalid state transitions fail explicitly.
- Persisted data is versioned and migration-aware.
- Errors identify the workflow object, step, field, rule, severity, and remediation.
- Security-sensitive permissions and tool boundaries remain explicit.

### 2.3 Release

- Versioned schemas are documented.
- CLI help and examples are complete.
- Desktop workflow is usable without editing YAML manually.
- A complete pilot example is included.
- Release notes and migration notes are written.
- PyInstaller packaging is either verified on a supported target or explicitly deferred with a documented blocker.
- A clean checkout can install, test, build, and run using documented commands.

---

## 3. Existing Technical Context

- **Runtime:** Mixed Python and TypeScript.
- **Desktop:** CustomTkinter Phase 5E application.
- **Optional packaging:** PyInstaller for cross-platform binaries.
- **Tests:** pytest baseline reported as `113 passed, 4 skipped`.
- **Product frame:** Local-first workflow scaffolding and governance runtime.
- **Existing concepts:** Workflow design briefs, process capsules, human gates, state transitions, run traces, non-conformance, agent package generation, simulations, evaluations, and durable history.

Before implementation, agents must inspect the repository rather than assume paths, package managers, framework versions, or entry points.

---

## 4. Non-Goals for This Release

Do not add:

- A generic multi-agent framework.
- Autonomous swarms.
- A visual node-canvas editor.
- Cloud accounts or mandatory hosted infrastructure.
- Organization-wide identity and role management.
- A marketplace.
- LangChain, LangGraph, DSPy, or another orchestration framework as governing architecture.
- LLM-dependent validation rules.
- Broad redesigns of unrelated runtime modules.
- A second desktop framework.
- A new repository.
- Automatic deployment of agents without explicit approval.

Optional adapters may be proposed in an ADR, but are not release requirements.

---

## 5. Target Domain Objects

Final names may adapt to repository conventions, but semantics must remain stable.

### 5.1 `HumanWorkflowDraft`

Captures the observed process without pretending it is complete.

Minimum concepts:

- workflow ID, name, version, status
- purpose, trigger, claimed outcome
- actors, systems, artifacts
- steps and transitions
- observed exceptions
- unwritten rules
- known pain points
- source evidence

### 5.2 `WorkflowStep`

Minimum concepts:

- stable step ID
- name and description
- actor or owner
- action
- trigger and preconditions
- inputs and outputs
- entry and exit conditions
- next step or terminal state
- decision authority
- evidence requirements
- exception paths

### 5.3 `WorkflowFinding`

Minimum concepts:

- finding ID
- workflow and optional step reference
- rule ID and rule version
- finding type
- severity
- deterministic message
- evidence/location
- recommended remediation
- blocking status
- acceptance status and rationale when permitted

### 5.4 `AccountableWorkflow`

A promoted workflow with explicit:

- owners
- states
- gates
- handoffs
- exceptions
- completion contract
- evidence requirements
- accepted residual risks

### 5.5 `CooperationAssessment`

Per-step analysis including:

- recommended executor class
- rationale
- human judgment requirement
- repeatability
- determinism
- risk
- reversibility
- data sensitivity
- required tools
- supervision mode
- automation readiness

### 5.6 `CooperativeWorkflow`

Approved assignment of work including:

- executor type and identity
- human owner
- approval gate
- escalation target
- allowed tools
- prohibited actions
- evidence output
- fallback executor
- runtime requirements
- required agent packages
- deployment constraints

---

## 6. Required Executor Classes

Use stable machine-readable values:

- `HUMAN_ONLY`
- `HUMAN_LED_AI_ASSISTED`
- `AGENT_PREPARED_HUMAN_APPROVED`
- `AGENT_EXECUTED_HUMAN_SUPERVISED`
- `DETERMINISTIC_AUTOMATION`
- `BOUNDED_AUTONOMOUS_AGENT`
- `NOT_READY_FOR_AUTOMATION`

The initial UI may emphasize the first four plus deterministic automation, but schemas must not require a breaking change to add the remaining approved classes.

---

## 7. Initial Validator Rule Set

The first release must implement at least these deterministic rules:

1. Undefined workflow trigger.
2. Undefined claimed outcome or terminal completion.
3. Missing step owner.
4. Missing or ambiguous decision authority.
5. Referenced next step does not exist.
6. Unreachable step.
7. Accidental dead-end state.
8. Implicit or incomplete handoff.
9. Missing required input source.
10. Output without artifact type or evidence requirement.
11. Missing exception path for a declared failure mode.
12. Unowned exception.
13. Human memory dependency or unwritten rule.
14. Ambiguous terms such as “ready,” “complete,” or “approved” without criteria.
15. Rejection or approval gate without a next action.
16. Unsupported completion claim.

Each rule requires:

- stable rule ID
- rule description
- severity
- blocking policy
- exact detection logic
- affected object/field location
- remediation guidance
- unit tests
- fixture coverage

Do not hide multiple unrelated defects inside one generic finding.

---

## 8. Promotion State Machine

Minimum maturity states:

```text
OBSERVED
  → MAPPED
  → ACCOUNTABLE
  → COOPERATION_READY
  → COOPERATIVE_DESIGN_APPROVED
  → RUNTIME_READY
  → DEPLOYED
  → VALIDATED
```

Requirements:

- No direct promotion from `OBSERVED` to `RUNTIME_READY`.
- State transitions are explicit, persisted, and tested.
- Blocking findings prevent promotion.
- Non-blocking findings may be accepted only with actor, timestamp, and rationale.
- Promotion produces a traceable artifact rather than mutating the source invisibly.
- Previous artifacts remain available for audit.
- Schema and rule versions are persisted.

---

## 9. Architecture Boundaries

### 9.1 Python responsibilities

Prefer Python for:

- canonical runtime contracts if consistent with current code
- Pydantic or repository-standard validation models
- deterministic validator engine
- promotion service
- cooperation assessment engine
- persistence and migrations
- CLI
- CustomTkinter desktop integration
- Agent Foundry export orchestration
- pytest suite

### 9.2 TypeScript responsibilities

Use TypeScript where the current project already uses it. Likely responsibilities include:

- shared schema consumers
- TypeScript-side contract validation
- adapters or app components already implemented in TS
- generated types from canonical JSON Schema
- TS unit and integration tests
- cross-language compatibility verification

Do not maintain two hand-written, independently evolving definitions of the same contract. Select one canonical schema source and generate or verify the secondary representation.

### 9.3 Deterministic versus AI-assisted behavior

**Authoritative:**

- schema validation
- graph validation
- rule evaluation
- promotion eligibility
- state transitions
- export compatibility
- persistence

**Optional AI assistance:**

- turning interview notes into a draft workflow
- suggesting clearer descriptions
- proposing exception paths
- explaining findings conversationally
- recommending executor classes

AI suggestions must never silently alter authoritative workflow state.

---

## 10. Pilot Workflow

Use **ConcordiaPax Substack article production** as the end-to-end pilot.

Required artifacts:

```text
examples/workflows/substack-publication/
├── observed-workflow.yaml
├── validation-report.json
├── validation-report.md
├── accountable-workflow.yaml
├── cooperation-assessment.yaml
├── cooperative-workflow.yaml
├── workflow-design-brief.yaml
└── README.md
```

The pilot should include real problems:

- an idea expands beyond article scope
- research or software work becomes a hidden dependency
- publication ownership is implicit
- “ready to publish” initially lacks criteria
- artwork and distribution are separate handoffs
- scope control requires a human gate
- AI can prepare but not authorize publication

---

## 11. Model and Tool Orchestration

The goal is balanced quality and cost. Expensive models make bounded architectural decisions and review high-risk work. Codex performs most implementation. Lower-cost tools handle parallel analysis, documentation, fixtures, and focused review. No model receives permission to rewrite unrelated subsystems.

### 11.1 Fable 5 — architecture and release specification

**Hard budget:** Maximum **$20 total credit use**.

Use Fable 5 first for:

- repository architecture audit
- dependency and boundary discovery
- contract-source decision
- release decomposition
- risk register
- ADR proposals
- acceptance criteria refinement
- identification of ambiguous or contradictory requirements
- first-pass file change map

Fable 5 must not spend the budget implementing bulk code.

Required output:

```text
handoffs/implementation/
├── architecture-audit.md
├── release-plan.md
├── risk-register.md
├── file-change-map.md
└── adr-proposals/
```

Stop conditions:

- stop before $20 is exceeded
- stop if repository inspection is incomplete
- stop if implementation begins expanding beyond the release
- record unresolved questions rather than inventing answers

### 11.2 Opus 4.8 — senior architecture and safety review

Use after Fable 5.

Primary tasks:

- challenge the architecture audit
- review schema ownership and cross-language strategy
- review state machine and promotion invariants
- identify data migration and backward-compatibility risks
- review security, permissions, auditability, and failure handling
- identify overengineering
- approve or revise ADRs
- produce a concise implementation directive for Codex

Opus should review high-risk design and selected diffs, not perform routine bulk coding.

Required output:

```text
handoffs/reviews/
├── opus-architecture-review.md
├── approved-adrs.md
└── codex-implementation-directive.md
```

### 11.3 Codex 5.6 Sol medium — primary implementation

Codex owns the bulk of coding.

Use one branch or worktree per implementation phase. Keep commits small and independently testable.

Codex tasks:

- inspect existing conventions before coding
- implement schemas and generated types
- implement validator rules
- implement promotion and persistence
- implement cooperation assessment and builder
- implement CLI
- integrate CustomTkinter desktop flows
- implement exports
- add tests and fixtures
- update documentation
- fix defects found by review and testing

Codex must:

- run baseline tests before changes
- preserve current passing behavior
- add tests alongside features
- never weaken tests to make a build pass
- avoid broad formatting changes
- avoid unrelated dependency upgrades
- document any required migration
- stop and write a blocked handoff when architecture conflicts are discovered

### 11.4 Grok Build — independent implementation critique

Use for bounded, parallel support:

- identify simpler implementation alternatives
- inspect a proposed module for hidden edge cases
- review CLI and desktop UX friction
- review graph algorithms and failure cases
- propose adversarial workflow fixtures
- inspect performance or packaging failures

Grok Build should normally return review notes or a narrow patch, not own the canonical architecture.

### 11.5 Google Antigravity — integration and UX support

Use for:

- tracing integration points across Python, TypeScript, CLI, and desktop
- reviewing UI state flow
- checking that desktop actions map to authoritative runtime services
- checking persistence/resume behavior
- reviewing packaging configuration
- producing focused integration fixes

Do not let Antigravity create a parallel service layer inside the UI.

### 11.6 OpenCode with `glm-5.1:cloud` — low-cost support

Command available:

```bash
ollama launch opencode --model glm-5.1:cloud
```

Use for:

- repository reconnaissance
- test fixture generation
- documentation drafts
- docstring and type-hint completion
- simple refactors after tests exist
- reviewing rule messages for clarity
- generating negative test cases
- checking TODOs and dead code
- summarizing diffs for the next agent

Do not assign it final authority over schemas, migrations, state transitions, or security boundaries.

### 11.7 Jules — testing and verification

Jules owns independent test expansion and release verification.

Tasks:

- reproduce baseline
- create adversarial fixtures
- test every validator rule
- test promotion invariants
- test serialization round trips
- test old persisted data behavior
- test Python/TypeScript fixture compatibility
- test CLI happy paths and failure paths
- test desktop service integration
- test offline behavior
- test PyInstaller packaging where supported
- produce a release verification report

Jules must not “fix” production code without writing a defect report first. Fixes should be returned to Codex unless explicitly delegated.

---

## 12. Cost-Control Protocol

1. Never ask an expensive model to rediscover information already recorded in a handoff.
2. Every agent begins by reading:
   - this master handoff
   - the latest architecture decision records
   - the current phase handoff
   - the latest test report
   - the previous agent’s completion note
3. Provide file paths and bounded questions rather than the whole repository when possible.
4. Use Fable 5 only until the $20 cap.
5. Use Opus only for architecture review, high-risk decisions, and final critical-diff review.
6. Use Codex for implementation and fixes.
7. Use GLM, Grok Build, and Antigravity for parallel bounded work.
8. Use Jules for independent verification.
9. Do not have multiple agents edit the same files simultaneously.
10. Do not ask three models to produce competing full implementations.
11. Prefer reviews of a diff over repeated greenfield rewrites.
12. Stop a model when it begins proposing non-goal features.

---

## 13. Branch and Worktree Strategy

Suggested structure:

```text
feature/human-cooperative-workflow-runtime
├── phase/contracts
├── phase/validator
├── phase/promotion
├── phase/cooperation
├── phase/cli
├── phase/desktop
├── phase/export
└── phase/release-hardening
```

Implementation may use sequential branches or worktrees, but only one branch should own a file group at a time.

Merge order:

1. contracts
2. validator
3. promotion/persistence
4. cooperation assessment
5. cooperative builder/export
6. CLI
7. desktop
8. testing and hardening
9. packaging and release documentation

Each phase requires:

- clean baseline
- scoped commits
- tests
- completion note
- no unresolved blocking defects

---

## 14. Required Agent Completion Note

Every agent must leave a file or handoff comment containing:

```markdown
# Agent Completion Note

## Scope completed

## Files changed

## Tests run and results

## Decisions made

## Assumptions

## Known limitations

## New risks or defects

## Recommended next action

## Exact starting point for next agent
```

Do not report “done” without test evidence.

---

## 15. Test Strategy

### 15.1 Baseline gate

Before feature work:

- record Python version
- record Node version
- record package managers
- run all existing tests
- confirm or explain the reported `113 passed, 4 skipped`
- save output to `artifacts/test-baseline.txt`

If baseline fails, do not attribute failure to new code. Record it separately.

### 15.2 Contract tests

- required and optional fields
- enum stability
- version fields
- unknown fields policy
- malformed IDs
- invalid references
- serialization round trip
- deterministic output ordering where applicable
- generated TS type compatibility

### 15.3 Validator tests

For each rule:

- valid fixture
- invalid fixture
- exact rule ID
- exact object location
- expected severity
- blocking policy
- remediation message
- no duplicate finding
- no false positive on nearby valid cases

### 15.4 State tests

- valid promotion path
- forbidden transition
- blocked promotion
- accepted non-blocking risk
- audit metadata
- persisted resume
- interrupted write recovery
- old-version load behavior

### 15.5 Cooperation tests

- human-only safety case
- deterministic automation case
- AI-assisted case
- supervised agent case
- not-ready case
- high-risk irreversible action
- sensitive-data handling
- fallback executor
- approval and escalation requirements

### 15.6 Integration tests

- observed workflow to validation report
- validation to accountable promotion
- accountable workflow to cooperation assessment
- assessment to approved cooperative workflow
- cooperative workflow to Workflow Design Brief export
- save/reload at every stage
- CLI and desktop call the same service layer
- no duplicated business logic in UI

### 15.7 Packaging tests

- module import from clean environment
- CLI entry point
- desktop startup
- bundled schemas and examples
- writable data directory behavior
- PyInstaller hidden imports and data files
- meaningful failure if packaging is unsupported

---

## 16. Desktop Requirements

The CustomTkinter application must provide:

1. Workflow project list.
2. Create/import observed workflow.
3. Guided step editor.
4. Findings view grouped by severity and workflow location.
5. Finding detail and remediation.
6. Accept non-blocking risk with rationale.
7. Promote to Accountable Workflow.
8. Cooperation assessment table.
9. Executor override with required rationale.
10. Cooperative workflow preview.
11. Export to Workflow Design Brief/Agent Foundry.
12. Save, reload, and resume.
13. Visible maturity state.
14. Visible validation/rule version.
15. No blocking of the UI thread during long operations.

The desktop app is a client of the runtime services. It must not implement a second validator.

---

## 17. CLI Requirements

Exact names may follow current CLI conventions, but capabilities must include:

```bash
fukasawa workflow init
fukasawa workflow validate <path>
fukasawa workflow findings <workflow-id>
fukasawa workflow promote <path>
fukasawa workflow assess-cooperation <path>
fukasawa workflow build-cooperative <path>
fukasawa workflow export-agent-brief <path>
fukasawa workflow status <workflow-id>
```

Requirements:

- useful `--help`
- machine-readable JSON output option
- non-zero exit code for blocking validation failure
- stable error codes
- no stack trace for normal user errors
- explicit paths to generated artifacts
- offline operation

---

## 18. Documentation Deliverables

- product lifecycle overview
- schema reference
- validator rule catalog
- promotion-state reference
- cooperation classification guide
- CLI guide
- desktop guide
- pilot walkthrough
- migration notes
- release notes
- contributor guide for adding a validator rule
- contributor guide for adding executor classification policy
- packaging guide

---

## 19. Release Gates

### Gate A — Architecture approved

- Fable audit complete within budget
- Opus review complete
- canonical schema strategy selected
- ADRs accepted
- no unresolved architecture blocker

### Gate B — Contracts stable

- schemas versioned
- Python/TS agreement verified
- migrations planned
- contract tests green

### Gate C — Validator complete

- initial rule set implemented
- all rule tests green
- reports are actionable
- false-positive review complete

### Gate D — Accountable promotion complete

- state machine enforced
- persisted audit trail
- blocking and accepted-risk behavior verified

### Gate E — Cooperation builder complete

- all steps classified
- human authority and fallback preserved
- approved cooperative workflow generated
- export path works

### Gate F — Interfaces complete

- CLI lifecycle works
- CustomTkinter lifecycle works
- same authoritative services used

### Gate G — Release verified

- full test suite green
- no regression from baseline
- Jules verification complete
- selected critical diffs reviewed by Opus
- docs complete
- packaging verified or explicitly deferred
- release candidate tag approved

---

## 20. Immediate Execution Order

1. Fable 5 performs architecture audit and release decomposition, capped at $20.
2. Opus 4.8 reviews architecture and issues the Codex directive.
3. Codex establishes the baseline and implements contracts.
4. Jules verifies contracts and cross-language fixtures.
5. Codex implements validator and promotion.
6. Grok Build performs adversarial validator review.
7. Codex implements cooperation assessment and builder.
8. Antigravity reviews integration boundaries and desktop flow.
9. Codex implements CLI, desktop integration, and export.
10. Jules performs full integration and packaging verification.
11. Codex fixes verified defects.
12. Opus reviews only the critical final diffs and release invariants.
13. Generate release candidate, release notes, and final verification report.

---

## 21. Final Restraint

This release proves:

```text
map → validate → repair → cooperate → export
```

It does not attempt to model every organization, replace every worker, or automate every decision.

When tempted to expand scope, preserve the release boundary and record the idea in the backlog.
