# Agent Completion Note — Phase 1: Contracts

**Phase:** 1 of 9 (contracts) — targets Gate B.
**Branch:** `feature/human-cooperative-workflow-runtime`.
**Authorized by:** `handoffs/reviews/codex-implementation-directive.md` §2, with
the D1 DoD amendment ratified by the operator on 2026-07-25.
**Implemented by:** `claude-fable-5` acting in the Codex implementation role.

## Scope completed

- **Baseline recorded first** (§15.1) — `artifacts/test-baseline.txt`, taken
  before any feature work: 113 passed, 4 skipped, confirmed against the
  master handoff's expected figure.
- **Three contract modules**, all fields documented, all versioned:
  - `src/schemas/human_workflow.py` — `HumanWorkflowDraft`, `WorkflowStep`,
    `AccountableWorkflow`, `WorkflowMaturity` (8 states), `StepCharacteristics`
    + its six factor enums, `ApprovalGate`, `StepInput`/`StepOutput`,
    `ExceptionPath`, `SourceEvidence`, `PromotionLineage`.
  - `src/schemas/findings.py` — `WorkflowFinding`, `ValidationReport`,
    `RiskAcceptance`, `RuleRef`, `FindingLocation`, `Severity`, `FindingType`.
  - `src/schemas/cooperation.py` — `ExecutorClass` (all 7 values),
    `CooperationAssessment`, `CooperativeWorkflow`, `StepAssignment`,
    `ExecutorOverride`, `SafetyFloor`, `SupervisionMode`, `AutomationReadiness`.
- **JSON Schema export** — `src/schemas/export_jsonschema.py`, 9 exported
  contracts, deterministic sorted-key output. This is the substituted D1
  obligation.
- **Pilot observed workflow moved into phase 1** per review defect D2 —
  `examples/workflows/substack-publication/observed-workflow.yaml`, 8 steps,
  seeding all seven §10 problems plus two structural defects.
- **56 contract tests** — `tests/test_workflow_contracts.py`.
- **Schema reference** — `docs/schema-reference.md`.

## Files changed

Created: `artifacts/test-baseline.txt`; `src/schemas/human_workflow.py`,
`findings.py`, `cooperation.py`, `export_jsonschema.py`;
`tests/test_workflow_contracts.py`; `docs/schema-reference.md`;
`examples/workflows/substack-publication/observed-workflow.yaml`; this note.

**No existing file was modified.** Phase 1 is additive by construction, so it
cannot have broken anything it did not touch. `pyproject.toml` needed no change
— the new modules live inside the already-declared `src.schemas` package.

## Tests run and results

```
.venv/bin/python -m pytest -q
169 passed, 4 skipped in 7.59s      # baseline 113 + 56 new; 0 regressions
```

Pre-existing test modules re-run in isolation: **106 passed** — no behavior
change. The 4 skips remain the display-dependent GUI view tests.

New coverage by area: draft permissiveness and round-trip; unknown-field
rejection; malformed workflow/step/rule ids; finding location and mandatory
message/remediation; acceptance requiring actor + rationale; the promotion
gate (blocking vs non-blocking vs accepted); `AccountableWorkflow` mandatory
fields and the D3 assertion that it declares no states/transitions; enum
stability for all 7 executor classes and all 8 maturity states; autonomy-rank
totality and the two deliberate orderings; override precedence; assignment
requiring a human owner and escalation target; JSON Schema export determinism
and enum presence; and the two ADR-002 tripwires.

## Decisions made

1. **`extra="forbid"` on every new contract.** These are hand-written YAML
   files; a silently-ignored typo is exactly the invisible drift the product
   exists to catch. Documented in the schema reference so the resulting error
   message is predictable.
2. **`RiskAcceptance` is defined once**, in `findings.py`, and imported by
   `human_workflow.py`. My own audit had implied two near-identical models
   (`RiskAcceptance` + `RiskAcceptanceRef`); an accepted risk on a promoted
   workflow is the *same object* that was attached to the finding, not a copy.
3. **`StepCharacteristics` lives on `WorkflowStep`, defined now rather than in
   phase 4.** Cooperation assessment must read observable facts to be
   deterministic, and phase 4 cannot edit `human_workflow.py` under the
   file-ownership rule — so the fields had to be defined here or the boundary
   would have been violated later.
4. **`ExecutorClass.autonomy_rank`** added as a contract-level primitive so
   phase 4's one-directional override rule is checkable by comparing integers
   rather than trusted to convention.
5. **`DETERMINISTIC_AUTOMATION` ranks below `AGENT_EXECUTED_HUMAN_SUPERVISED`.**
   Ranking follows *delegated judgment*, not *absence of humans*: a script has
   no latitude to misjudge. This is an explicit, tested, documented choice
   because the opposite ordering is the intuitive one.
6. **`SafetyFloor` enum records *which* fact forced a floor**, not just that
   one applied — an operator needs the reason to argue with it.
7. **The docs describe the Python export API, not a CLI command.** The
   `fukasawa schema dump` wrapper belongs to phase 6, which owns `src/cli.py`;
   promising it now would have documented something that does not exist.

## Assumptions

- The D1 amendment as ratified means: no TypeScript deliverables, JSON Schema
  export + golden tests substitute, and Gate B reads "schemas versioned; JSON
  Schema artifacts exported and golden-tested; migrations planned; contract
  tests green."
- `WorkflowStep`, `StepAssignment`, and `RiskAcceptance` are nested pieces that
  version with their parent artifact rather than carrying their own
  `schema_version` (asserted explicitly in the versioning test).
- Rule IDs `HW-001`…`HW-016` map 1:1 to master handoff §7 in order; phase 2
  implements the detection logic against the blocking table in directive §4.

## Known limitations

- **Contracts only.** No rule fires yet, nothing is persisted, no CLI or GUI
  surface exists. `ValidationReport`, `CooperationAssessment`, and
  `CooperativeWorkflow` are shapes with no producer until phases 2, 4, and 5.
- The pilot's derived artifacts (validation report, accountable workflow,
  cooperation assessment, cooperative workflow, workflow design brief) are not
  present — each is emitted by the phase that can genuinely produce it.
- No ledger tables yet: persistence is phase 3, which solely owns
  `src/runtime/ledger.py`.
- The golden JSON Schema test pins *determinism and enum presence*, not a
  byte-exact snapshot file. A snapshot would be stronger; it is cheap to add in
  phase 2 once the rule set stops moving.
- `docs/schema-reference.md` is hand-written from the models. It can drift.
  Generating the field tables from `model_fields` is a worthwhile phase-8
  hardening task, backlogged rather than done.

## New risks or defects

- **No new risks introduced.** Phase 1 modified no existing file.
- Risk R1 is now *instrumented*: `TestFrozenSchemaFingerprints` pins
  `q2c-pipeline-graph` at `33baa1b0…` and `oldowan-pipeline-graph` at
  `dabc6399…`, and a companion test proves the fingerprint moves when any
  field changes. If the golden test fails, **do not update the hashes** —
  every `.sig` in the field and every hash-pinned resume just broke; stop and
  escalate per directive §7.
- Minor observation for phase 2: `StepCharacteristics` has six factors that
  all default to `UNKNOWN`, so the pilot's steps are fully characterized only
  because I characterized them by hand. Real captured workflows will arrive
  mostly `UNKNOWN`, and rule/assessment output must stay useful in that state —
  worth an adversarial fixture (a wholly uncharacterized workflow).

## Recommended next action

Phase 2 (validator). Implement `src/governance/workflow_rules.py` — the
registry plus HW-001…HW-016 with the severities fixed in directive §4 — and
emit the pilot's `validation-report.{json,md}`. Every blocking rule needs a
positive and a negative fixture; the pilot already contains a live subject for
HW-003, HW-004, HW-005, HW-006, HW-008, HW-009, HW-010, HW-011, HW-012,
HW-013, HW-014, and HW-015.

## Exact starting point for next agent

Branch `feature/human-cooperative-workflow-runtime` @ head.
Read: directive §4 (blocking table) → `docs/schema-reference.md` (finding
contract + what "blocking" means) → the pilot YAML header comment, which maps
each seeded defect to the rule expected to catch it.
Import surface you now have: `src.schemas.findings` (`WorkflowFinding`,
`ValidationReport`, `RuleRef`, `FindingLocation`, `Severity`, `FindingType`)
and `src.schemas.human_workflow` (`HumanWorkflowDraft`, `WorkflowStep`,
helpers `step()`, `step_ids()`, `entry_step`).
Current suite: **169 passed, 4 skipped**. Do not touch any file listed FROZEN
in directive §3.
