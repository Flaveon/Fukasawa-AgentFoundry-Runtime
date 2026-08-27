# Codex Implementation Directive

**Issued:** 2026-07-25 by `claude-fable-5` acting in the Phase Handoff 02
review role (not Opus 4.8 — see `opus-architecture-review.md` provenance note).
**Authorizes:** phases 1–9 of the Human & Cooperative Workflow Runtime release.
**Branch:** `feature/human-cooperative-workflow-runtime` @ `0ac4b2e`.
**Read before starting:** master handoff → `handoffs/implementation/architecture-audit.md`
→ `adr-proposals/adr-002` → `opus-architecture-review.md` (defects D1–D8) →
`approved-adrs.md` → `file-change-map.md`.

---

## 1. Approved architecture

Build a new capture-and-cooperation layer that terminates in an export to the
**existing** `WorkflowBrief`. The proven runtime — state machine, ledger,
review gates, kernel, package generator, bundle format — is **consumed
unchanged**. You are adding a front end to governance, not a second runtime.

```
HumanWorkflowDraft ──validate──> WorkflowFinding[]
      │                                │
      │ promote (blocking findings must be resolved or accepted)
      ▼
AccountableWorkflow ──assess──> CooperationAssessment[] (per step)
      │                                │  human review/override
      ▼                                ▼
CooperativeWorkflow ──export──> WorkflowBrief ──> [EXISTING: generate_packages,
                                                   state machine, ledger, kernel]
```

Canonical contracts: Pydantic v2 in `src/schemas/` (ADR-001). Persistence:
existing `RunLedger` SQLite, additive tables only. No new dependency, no
server, no LLM in any authoritative path.

## 2. Ordered implementation phases and exact boundaries

Each phase: clean baseline → scoped commits → tests → completion note (§14
template) → no unresolved blocking defects. Merge in this order.

| # | Phase | Boundary — done when | Gate |
|---|---|---|---|
| 1 | contracts | 3 schema modules + JSON Schema export + pilot `observed-workflow.yaml` + `artifacts/test-baseline.txt` committed; contract tests green | B |
| 2 | validator | 16 rules per the table in §4; every rule has positive+negative fixtures; pilot produces `validation-report.{json,md}` | C |
| 3 | promotion/persistence | additive ledger tables; §8 transitions enforced through `RUNTIME_READY`; acceptance requires actor+timestamp+rationale; pilot emits `accountable-workflow.yaml` | D |
| 4 | cooperation assessment | decision table + one-directional floors + override-with-rationale; pilot emits `cooperation-assessment.yaml` | E (part) |
| 5 | builder + export | `CooperativeWorkflow` → `WorkflowBrief`; feeds existing `generate_packages` untouched; pilot emits `cooperative-workflow.yaml` + `workflow-design-brief.yaml` | E |
| 6 | CLI | all §17 commands, `--json`, stable exit codes, no stack traces on user error | F (part) |
| 7 | desktop | §16 items 1–15 via the GUI adapter; worker threads; no logic in views | F |
| 8 | hardening + pilot README/walkthrough | Jules verification; false-positive review closed | G (part) |
| 9 | packaging + release docs | binary smoke-tested on Linux or blocker documented | G |

**Deviation from the audit's file map (defect D2):** the pilot is no longer a
phase-8 lump. Phase 1 authors `observed-workflow.yaml` (a data file); each
later phase emits its own derived artifact. Phase 8 writes only the README and
walkthrough.

## 3. File ownership

One owning phase per file — this is what prevents concurrent-edit collisions
across Codex / Grok Build / Antigravity / Jules. Full table in
`handoffs/implementation/file-change-map.md`; the contested files are:

| File | Sole owner |
|---|---|
| `src/runtime/ledger.py` | phase 3 |
| `src/cli.py` | phase 6 |
| `src/gui/services.py`, `src/gui/app.py` | phase 7 |
| `packaging/*`, `README.md` | phase 9 |
| `tests/test_gui.py` (existing) | nobody — new GUI tests go in `tests/test_gui_workflow.py` |
| `examples/workflows/substack-publication/<artifact>` | the phase that emits that artifact |

**FROZEN — do not edit in any phase:** `src/schemas/graph.py`,
`src/schemas/bundle.py`, `src/kernel/*`, `src/security/*`,
`src/foundry/generator.py`, `src/runtime/state_machine.py`,
`src/runtime/bundle.py`. Touching these is a stop-and-escalate condition (§7).

## 4. Rule blocking policy — authoritative

IDs map 1:1 to master handoff §7 in order and are **never renumbered** (they
persist on findings forever). "Blocking" means **blocks promotion to
`ACCOUNTABLE`** — it never blocks capture, save, or reload.

| ID | Rule | Policy |
|---|---|---|
| HW-001 | Undefined workflow trigger | **BLOCKING** |
| HW-002 | Undefined claimed outcome / terminal completion | **BLOCKING** |
| HW-003 | Missing step owner | **BLOCKING** |
| HW-004 | Missing or ambiguous decision authority | **BLOCKING** |
| HW-005 | Referenced next step does not exist | **BLOCKING** |
| HW-006 | Unreachable step | **BLOCKING** |
| HW-007 | Accidental dead-end state | **BLOCKING** |
| HW-008 | Implicit/incomplete handoff (cross-actor with no artifact or evidence requirement) | **BLOCKING** |
| HW-009 | Missing required input source | **BLOCKING** |
| HW-010 | Output without artifact type or evidence requirement | **BLOCKING** |
| HW-011 | Missing exception path for a declared failure mode | **BLOCKING** |
| HW-012 | Unowned exception | **BLOCKING** |
| HW-013 | Human memory dependency / unwritten rule | non-blocking |
| HW-014 | Ambiguous terms ("ready", "complete", "approved") without criteria | non-blocking |
| HW-015 | Rejection or approval gate without a next action | **BLOCKING** |
| HW-016 | Unsupported completion claim | **BLOCKING** |

HW-013 and HW-014 are the heuristic pair — non-blocking by design because they
carry real false-positive risk. Every blocking rule needs a positive and a
negative fixture (DoD §2.2). One defect per finding: never bundle unrelated
problems into one message.

## 5. Test gates

- **Before any feature work (phase 1):** record Python version, package
  manager, and full pytest output to `artifacts/test-baseline.txt`. Expected
  **113 passed, 4 skipped**. The 4 skips are GUI-view tests needing a display;
  run them with `xvfb-run -a .venv/bin/python -m pytest tests/test_gui*.py`.
  There is no Node version to record — this repo has no TypeScript (D1).
- Per phase: tests land **with** the feature, never after.
- Validator: per rule — exact rule ID, exact object/field location, expected
  severity, blocking policy, remediation text, no duplicate finding, no false
  positive on a nearby valid fixture.
- Promotion: valid path, forbidden transition, blocked-by-finding, accepted
  risk with audit metadata, persisted resume, interrupted-write recovery,
  old-version load.
- Cooperation: the nine §15.5 cases, **plus** an explicit test that an
  override cannot move a floored step toward greater autonomy.
- Boundary tests (mechanical enforcement of ADR-007): `src/cli.py` never
  imports from `src/gui/`; no rule/promotion/classification logic under
  `src/gui/`.
- Contracts: golden-file tests pinning exported JSON Schema, and golden-hash
  tests pinning `graph_fingerprint` of the existing example graphs (the
  ADR-002 tripwire).

## 6. Prohibited shortcuts

1. Do not weaken, skip, or `xfail` an existing test to make a build pass.
2. Do not edit any FROZEN file (§3). Signatures and hash-pinned resumes depend
   on their exact serialized bytes.
3. Do not put a rule, a promotion decision, or an executor classification
   anywhere under `src/gui/`.
4. Do not let the CLI import from `src/gui/`.
5. Do not call an LLM in any authoritative path (validation, promotion
   eligibility, classification, export, persistence).
6. Do not refuse to save or reload a draft because it has findings.
7. Do not renumber rule IDs or change persisted enum string values.
8. Do not perform destructive DDL. Additive only; the ledger is append-only.
9. Do not add a dependency, a DSL, a plugin loader, FastAPI, a graph library,
   or a second desktop framework.
10. Do not widen generated-package permissions beyond what the executor class
    authorizes.
11. Do not emit stack traces for normal user errors; no bare exceptions across
    the CLI boundary.
12. Do not put real hosts, IPs, or private paths in fixtures — placeholders
    only (this repo has had one LAN-IP leak).
13. Do not broadly reformat, and do not upgrade unrelated dependencies.

## 7. Stop and escalate conditions

Write a blocked handoff and stop — do not improvise — when:

- a phase appears to require editing a FROZEN file;
- a required behavior conflicts with the master handoff, an approved ADR, or
  this directive;
- the baseline does not reproduce (record it separately; do not attribute it
  to your changes);
- the D1 DoD amendment has not been ratified and you have reached **Gate B**
  evaluation (phase 1 implementation may proceed; Gate B cannot be judged);
- a rule's detection logic cannot be made deterministic;
- implementing a §16 desktop item seems to require business logic in a view;
- you find yourself designing for a §4 non-goal (multi-agent framework,
  swarms, node canvas, marketplace, identity management, auto-deployment).

## 8. Known risks carried into implementation

From `handoffs/implementation/risk-register.md`, the four that will actually
bite during coding:

- **R1 / ADR-002 (highest):** signature canonicalization. Adding any field to
  `GraphSpec`/`BundleManifest` — even optional with a default — invalidates
  field signatures and hash-pinned resumes. Frozen; golden-hash test is the
  tripwire.
- **R5:** persistence. Additive DDL only; promotion must write artifact and
  state in one transaction so an interrupted write cannot strand a workflow
  between states.
- **R3:** UI duplication. Highest-volume phase (15 requirements) with the
  easiest failure mode; boundary tests are mandatory, not optional.
- **R9:** validator false positives. HW-013/HW-014 are heuristic; tune them
  against the pilot's seeded problems and close the Gate C false-positive
  review before declaring the validator done.

Open, not resolvable by Codex: **D1** (operator must ratify the DoD amendment)
and the reviewer-substitution question in `approved-adrs.md` Gate A.
