# File Change Map — phase-by-phase, for Codex

**Rule: every file has exactly one owning phase. A file listed under phase N
is edited/created ONLY in phase N. This is what prevents simultaneous-edit
conflicts across Codex / Grok Build / Antigravity / Jules (master handoff
§12.9, §13). Jules adds tests only in files marked (Jules-extendable) or in
new `tests/verification_*` files.**

Branching per master handoff §13: work happens on
`feature/human-cooperative-workflow-runtime` with one `phase/*` branch (or
worktree) per row-group below, merged in order 1→9.

## Phase 1 — contracts (Gate B)

| Action | File |
|---|---|
| NEW | `src/schemas/human_workflow.py` (`HumanWorkflowDraft`, `WorkflowStep`, `AccountableWorkflow`, `WorkflowMaturity` enum — §8 states) |
| NEW | `src/schemas/findings.py` (`WorkflowFinding`, `Severity`, `RuleRef`, `RiskAcceptance`) |
| NEW | `src/schemas/cooperation.py` (`ExecutorClass` — all 7 §6 values, `CooperationAssessment`, `CooperativeWorkflow`) |
| NEW | `tests/test_workflow_contracts.py` (round-trip, versioning, unknown-field policy, enum stability, golden `graph_fingerprint` guard for R1) (Jules-extendable) |
| NEW | `docs/schema-reference.md` (stub grows with later phases? NO — single owner: fully written here for the three new modules; later phases do not edit it, they add sibling docs) |
| NEW | CLI-independent JSON Schema export helper: `src/schemas/export_jsonschema.py` (used by phase 6's CLI command; created here so contracts phase owns all schema surface) |

Constraint: does NOT touch any existing file. Zero-conflict by construction.

## Phase 2 — validator (Gate C)

| Action | File |
|---|---|
| NEW | `src/governance/workflow_rules.py` (registry + rules HW-001…HW-016 per master handoff §7) |
| NEW | `tests/test_workflow_rules.py` (per rule: valid fixture, invalid fixture, exact ID/location/severity/blocking/remediation; no-duplicate, no-false-positive-nearby) (Jules-extendable) |
| NEW | `tests/fixtures/workflows/` (valid + per-rule invalid YAML fixtures; adversarial fixtures from Grok Build land here too) |
| NEW | `docs/validator-rule-catalog.md` (generated-or-written catalog; contributor guide section for adding a rule) |

## Phase 3 — promotion + persistence (Gate D)

| Action | File |
|---|---|
| **EDIT** | `src/runtime/ledger.py` (additive tables: workflow_drafts, workflow_findings, risk_acceptances, workflow_promotions, cooperation_assessments, cooperative_workflows; save/load methods) — **sole phase allowed to edit this file** |
| NEW | `src/governance/workflow_promotion.py` (§8 transition table, blocking-finding gate, acceptance-with-rationale, artifact-producing promotion) |
| NEW | `tests/test_workflow_promotion.py` (§15.4: valid path, forbidden transition, blocked promotion, accepted risk audit metadata, persisted resume, interrupted write, old-version load) (Jules-extendable) |
| NEW | `docs/promotion-state-reference.md` |
| NEW | `docs/migration-notes.md` (DB additive-DDL statement; schema_version policy) |

## Phase 4 — cooperation assessment (Gate E, first half)

| Action | File |
|---|---|
| NEW | `src/governance/cooperation.py` (deterministic per-step assessment engine; executor-class recommendation + rationale; human override requires rationale) |
| NEW | `tests/test_cooperation.py` (§15.5 cases: human-only safety, deterministic automation, AI-assisted, supervised, not-ready, irreversible, sensitive-data, fallback, escalation) (Jules-extendable) |
| NEW | `docs/cooperation-classification-guide.md` (+ contributor guide for classification policy) |

## Phase 5 — cooperative builder + export (Gate E)

| Action | File |
|---|---|
| NEW | `src/foundry/workflow_export.py` (`CooperativeWorkflow` → `WorkflowBrief` YAML: executor classes → `TaskDepth`/`AgentSpec` mapping; feeds existing `generate_packages` untouched) |
| NEW | `tests/test_workflow_export.py` (export → `WorkflowBrief.model_validate` → `generate_packages` round-trip on fixture) (Jules-extendable) |

## Phase 6 — CLI (Gate F, first half)

| Action | File |
|---|---|
| **EDIT** | `src/cli.py` (additive: `workflow_app` sub-app with §17 commands — init, validate, findings, promote, assess-cooperation, build-cooperative, export-agent-brief, status; `--json`; stable exit codes; no edits to existing commands) — **sole phase allowed to edit this file** |
| NEW | `tests/test_workflow_cli.py` (Typer runner: happy paths, blocking-failure exit codes, JSON output, no-stack-trace-on-user-error) (Jules-extendable) |
| NEW | `docs/cli-guide.md` |

## Phase 7 — desktop (Gate F)

| Action | File |
|---|---|
| **EDIT** | `src/gui/services.py` (additive typed service functions: list/create/import/validate/accept-risk/promote/assess/override/build/export/save/reload) — **sole phase allowed to edit** |
| **EDIT** | `src/gui/app.py` (mount new tabs from workflow_views; keep 2 existing tabs untouched) — **sole phase allowed to edit** |
| NEW | `src/gui/workflow_views.py` (§16 items 1–15; worker-thread pattern for long ops, UI thread never blocked; views import services ONLY) |
| NEW | `tests/test_gui_workflow.py` (headless-driven per existing `test_gui.py` idiom; asserts views delegate to services — R3 guard) (Jules-extendable) |
| NEW | `docs/desktop-guide.md` |

## Phase 8 — hardening + pilot (Gate G, verification)

| Action | File |
|---|---|
| NEW | `examples/workflows/substack-publication/` — all 8 §10 artifacts (observed-workflow.yaml, validation-report.json/.md, accountable-workflow.yaml, cooperation-assessment.yaml, cooperative-workflow.yaml, workflow-design-brief.yaml, README.md) with the 7 seeded real problems |
| NEW | `docs/pilot-walkthrough.md`, `docs/lifecycle-overview.md` |
| NEW | `artifacts/test-baseline.txt` (actually recorded at phase 1 start per §15.1; committed here) |
| NEW | `tests/verification_*` (Jules-owned release verification suite) |
| NEW | `handoffs/implementation/release-verification-report.md` (Jules) |

## Phase 9 — packaging + release docs (Gate G, release)

| Action | File |
|---|---|
| **EDIT** | `packaging/fukasawa.spec` (data files for new schemas/examples; hidden imports if any) — **sole phase allowed to edit** |
| **EDIT** | `packaging/README.md`, `README.md` (feature section + commands) |
| NEW | `docs/release-notes.md`, `docs/packaging-guide.md` |

## Shared-file ownership summary (the conflict-prevention table)

| Contested file | Sole owner |
|---|---|
| `src/runtime/ledger.py` | Phase 3 |
| `src/cli.py` | Phase 6 |
| `src/gui/services.py`, `src/gui/app.py` | Phase 7 |
| `packaging/*`, `README.md` | Phase 9 |
| `tests/test_gui.py` (existing) | **nobody** — new GUI tests go in `tests/test_gui_workflow.py` |
| `src/schemas/graph.py`, `src/schemas/bundle.py`, `src/kernel/*`, `src/security/*`, `src/foundry/generator.py`, `src/runtime/state_machine.py` | **frozen this release** (R1; release-plan §5) |
