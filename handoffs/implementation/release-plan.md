# Release Plan — Human & Cooperative Workflow Runtime

**Anchored to the master handoff's Definition of Done (§2) and release gates
(§19). Companion to `architecture-audit.md`; file-level detail in
`file-change-map.md`. Status: proposed, pending Opus review (Gate A).**

## 1. Gap analysis: master DoD §2.1 vs current repository

Every §2.1 functional item is NEW capability — none exists today. What DOES
exist is the machinery each item should be built on:

| DoD §2.1 item | Existing foundation to reuse (paths) |
|---|---|
| Create/import observed workflow | YAML-in, Pydantic-validate pattern (`WorkflowRuntime.load_brief`, `src/cli.py validate brief`) |
| Deterministic, location-specific findings | finding-list pattern (`src/foundry/validator.py`, `GraphSpec.validate_against_brief`) — needs typing (ADR-003) |
| Blocking vs non-blocking + accepted risk | severity precedent: retryable vs freezing non-conformance (`src/runtime/state_machine.py` two failure modes) |
| Promote to `AccountableWorkflow` | evidence-gated promotion pattern (`src/governance/maturity.py` `assess`/`promote`/`PromotionRefusedError`) |
| `CooperationAssessment` per step | depth doctrine (`TaskDepth`, `depth_of`, CONSCIOUS-owner rule in `src/schemas/workflow_brief.py`) |
| Build `CooperativeWorkflow` | `AgentSpec` (escalation, forbidden, deployment) in `src/schemas/agent_spec.py` |
| Export to `WorkflowDesignBrief` + Agent Foundry | `WorkflowBrief` schema + `generate_packages` (`src/foundry/generator.py`) — the export TARGET already works |
| Save/reload/resume all stages | `RunLedger` (`src/runtime/ledger.py`) SQLite persistence + resume doctrine |
| Core lifecycle from CLI | Typer sub-app conventions (`src/cli.py`) |
| Same lifecycle from desktop | `src/gui/services.py` seam + `src/gui/app.py` tab pattern |

## 2. Smallest release architecture

Nine NEW modules, three EDITED files, zero rewrites of existing subsystems:

```
src/schemas/human_workflow.py     HumanWorkflowDraft, WorkflowStep,
                                  AccountableWorkflow, WorkflowMaturity (§8 states)
src/schemas/findings.py           WorkflowFinding, Severity, RuleRef, RiskAcceptance
src/schemas/cooperation.py        ExecutorClass (§6, all 7 values), 
                                  CooperationAssessment, CooperativeWorkflow
src/governance/workflow_rules.py  rule registry + the 16 deterministic rules (§7)
src/governance/workflow_promotion.py  promotion service enforcing §8 invariants
src/governance/cooperation.py     deterministic assessment engine + override
src/foundry/workflow_export.py    CooperativeWorkflow → WorkflowBrief YAML
src/gui/workflow_views.py         new desktop tabs (client of services only)
examples/workflows/substack-publication/   pilot (§10, 8 artifacts)

EDITED: src/runtime/ledger.py     new tables (drafts, findings, assessments,
                                  workflow promotions) — additive only
EDITED: src/cli.py                new `workflow` sub-app (§17 commands)
EDITED: src/gui/services.py, src/gui/app.py   new service functions + tabs
```

Design rules that keep it smallest:
- **No new persistence engine** — the existing `RunLedger`/SQLite gets new
  tables; append-only audit discipline extends to promotion history.
- **No second state-machine framework** — §8's workflow maturity is a new
  transition table using the same enforce-refuse-record idiom as
  `state_machine.py` and `maturity.py`.
- **Export, don't rebuild** — `AccountableWorkflow` + `CooperativeWorkflow`
  export into the EXISTING `WorkflowBrief`, so the entire proven runtime
  (state machine, ledger, gates, kernel, packages, bundles) executes the
  result unchanged. The new layer feeds the old one; it does not fork it.
- **UI is a client** — desktop calls `services.py` functions; the validator
  runs only in `src/governance/workflow_rules.py` (§16: no second validator).

## 3. Required vs optional

**Required (blocks a DoD §2 item or a §19 gate):**
1. The three contract modules, versioned from birth (`schema_version` field, ADR-002).
2. Rule registry with all 16 §7 rules, each with stable ID, severity,
   blocking policy, location, remediation, positive+negative tests.
3. Promotion state machine (§8), persisted + audited; blocking-finding gate;
   risk acceptance with actor/timestamp/rationale.
4. Cooperation assessment engine + human-override-with-rationale; all 7
   executor classes in the schema (UI may surface 5).
5. Cooperative builder + export to `WorkflowBrief`/Agent Foundry.
6. CLI `workflow` sub-app (§17): init/validate/findings/promote/
   assess-cooperation/build-cooperative/export-agent-brief/status, with
   `--json`, stable exit codes.
7. Desktop lifecycle (§16 items 1–15) via services.
8. Save/reload/resume at every stage (ledger tables).
9. Substack pilot with the §10 seeded problems.
10. Docs (§18) + migration notes; baseline preserved (113 passed, 4 skipped).

**Optional (explicitly not release-blocking):**
- TypeScript type generation from exported JSON Schema (see the Gate A
  conflict, risk R8 — recommendation: ship `fukasawa schema dump` emitting
  JSON Schema as the future-TS seam and amend DoD §2.2's cross-language
  fixture requirement to apply *when a TS consumer exists*).
- AI-assisted drafting/suggestions (§9.3 — optional by definition; keep out
  of the release-critical path entirely).
- Carrying workflow projects inside `.fkz` bundles (Phase 5C integration).
- FastAPI/MCP surfaces; DuckDB analytics; PyInstaller verification beyond
  one supported target (§2.3 allows explicit deferral with documented blocker).

## 4. Phase order and gates

Implementation follows master handoff §13 merge order; each phase maps to a
gate and to a disjoint file group (see `file-change-map.md`):

| # | Phase | Gate | Proves |
|---|---|---|---|
| 1 | contracts | B | schemas versioned, round-trip, unknown-field policy |
| 2 | validator | C | 16 rules, actionable reports, false-positive review |
| 3 | promotion/persistence | D | §8 invariants, audit trail, resume |
| 4 | cooperation assessment | E (partial) | classes, rationale, override |
| 5 | builder + export | E | approved cooperative workflow → brief → packages |
| 6 | CLI | F (partial) | full lifecycle scriptable, JSON output |
| 7 | desktop | F | same lifecycle, same services, no UI logic fork |
| 8 | hardening + pilot | G | Jules verification, baseline intact, docs |
| 9 | packaging + release docs | G | binary verified or deferral documented |

Branching: master handoff §13 targets `feature/human-cooperative-workflow-runtime`
with per-phase branches. (This audit itself is committed to the session's
designated branch; the feature branch is created when implementation starts.)

## 5. What this release deliberately does not do

Per §4 non-goals and §21 restraint: no multi-agent framework, no node-canvas
editor, no second desktop framework, no LLM-dependent validation, no broad
refactors of `src/runtime/`, `src/kernel/`, `src/security/`, or
`src/foundry/generator.py` — those modules are consumed, not modified
(except the additive `ledger.py` tables and the export module beside the
generator).
