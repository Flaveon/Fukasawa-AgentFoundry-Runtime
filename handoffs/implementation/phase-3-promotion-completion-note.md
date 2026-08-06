# Agent Completion Note — Phase 3: Promotion and Persistence

**Phase:** 3 of 9 — targets Gate D.
**Branch:** `feature/human-cooperative-workflow-runtime`.
**Implemented by:** `claude-fable-5` in the Codex implementation role.

## Scope completed

- **Ledger (additive only)** — five new tables: `workflow_drafts` (editable),
  and `validation_reports`, `risk_acceptances`, `workflow_promotions`,
  `accountable_workflows` (append-only, trigger-enforced). Plus save/load
  accessors matching the existing style.
- **`src/governance/workflow_promotion.py`** — the 8-state ladder, the
  transition table, `assess()`, `accept_risk()`, `promote()`, and the
  refusal/audit machinery.
- **Pilot artifacts** — `repaired-workflow.yaml` (stage 2) and
  `accountable-workflow.yaml` (stage 3).
- **`tests/test_workflow_promotion.py`** — 39 tests.
- **Docs** — `promotion-state-reference.md`, `migration-notes.md`.

## Files changed

Created: `src/governance/workflow_promotion.py`,
`tests/test_workflow_promotion.py`, `docs/promotion-state-reference.md`,
`docs/migration-notes.md`,
`examples/workflows/substack-publication/{repaired,accountable}-workflow.yaml`,
this note. Modified: `src/runtime/ledger.py` (phase 3 is its sole owner).

## Tests run and results

```
.venv/bin/python -m pytest -q
336 passed, 5 skipped      # 297 before + 39 new; 0 regressions
```

Migration claim verified separately against a **simulated pre-phase-3
database**: opening it with the new build gained the new tables, preserved the
existing ledger row, and lost nothing.

## Decisions made

1. **`promote()` returns a `PromotionOutcome`, not an artifact.** My first
   implementation returned `AccountableWorkflow` for every target, which is
   wrong: `OBSERVED → MAPPED` produces no artifact. Reaching `MAPPED` advances
   the draft in place; reaching `ACCOUNTABLE` produces a separate immutable
   artifact and leaves the draft alone. One dataclass carries both cases.
2. **Advancing to `MAPPED` mutates the draft, and that is deliberate.** The
   append-only promotion row, citing the report it was based on, is the
   traceable record of the move — so nothing moves invisibly without inventing
   a second artifact type for a structural checkpoint.
3. **`workflow_drafts` is the one mutable new table.** A draft is a working
   document people edit as they learn more; forbidding that would make honest
   capture impossible. Everything derived from a draft is immutable.
4. **Refusals are recorded before the exception is raised.** A history showing
   only successful promotions is an advertisement, not an audit.
5. **The append-only trigger list is now generated** from a table tuple rather
   than twelve literal SQL blocks — the same data-driven direction the upstream
   `_ensure_schema` refactor took.
6. **Owners default to the step actors.** By `ACCOUNTABLE`, HW-003 guarantees
   every step names one, so the actors are the owners unless a caller says
   otherwise.
7. **Gates stop at `RUNTIME_READY`.** Later targets refuse with a stated reason
   naming the phase that will supply the evidence, rather than being silently
   permitted.

## A defect the tests caught

Promoting the same version twice leaked a raw
`sqlite3.IntegrityError: UNIQUE constraint failed`. That is a normal user
mistake, and the release requires no stack traces for those. It now refuses
cleanly with instructions to bump the draft version — and refusing is the right
behaviour beyond tidiness, because overwriting would destroy an artifact an
audit may already cite. The earlier version stays readable; a test asserts it.

## The pilot, end to end

The observed pilot stays **deliberately broken** — it is the validator fixture,
and a test asserts it still fails. The repair is therefore a separate artifact:

| Stage | Artifact | Result |
|---|---|---|
| observed | `observed-workflow.yaml` | 24 findings, 14 blocking — promotion **refused**, refusal audited |
| repaired | `repaired-workflow.yaml` | 6 findings, **0 blocking** — all 14 fixed |
| accepted | — | 6 advisory findings accepted, each with actor + rationale |
| promoted | `accountable-workflow.yaml` | `OBSERVED → MAPPED → ACCOUNTABLE`, 8 steps, 6 accepted risks |

## Assumptions

- `repaired-workflow.yaml` is a **deviation from the master handoff's §10
  artifact list**, which names no artifact for the "repair" verb even though
  repair is one of the five the release proves. Adding it makes the lineage
  legible: observed → repaired → accountable. Flagged rather than silently
  introduced.
- The `MAPPED` gate checks structural rules (HW-001, 002, 005, 006, 007);
  `ACCOUNTABLE` requires all blocking findings clear. The split is a judgement
  call — the handoff says blocking findings prevent promotion without saying
  which gate each belongs to.

## Known limitations

- **No CLI or GUI surface.** `promote()` is importable but has no operator
  entry point until phase 6 owns `src/cli.py`.
- **Interrupted-write recovery is ordering, not a transaction.** The artifact
  is written before the audit row, so a crash between them leaves no phantom
  promotion — the safe direction — but the two writes are not atomic. A real
  transaction would need `sqlite_utils` transaction scoping; the test asserts
  the current guarantee honestly rather than claiming more.
- **Attribution is self-attested**, as documented. No authentication exists.
- **`accept_risk()` mutates the in-memory report** to attach the acceptance.
  Callers reusing a report object across promotions see accumulated
  acceptances, which is intended but undocumented in the function signature.

## New risks or defects

- Nothing new to the register. R5 (persistence) is now partly discharged:
  additive DDL verified against an old database, append-only enforced by
  triggers, interrupted-write ordering tested.
- Minor, for phase 6: `assess()` returns criteria whose `detail` strings are
  written for humans. If the CLI renders them with Rich, they need
  `markup.escape` like the rest of the CLI does.

## Recommended next action

Phase 4 (cooperation assessment): `src/governance/cooperation.py`, the
deterministic decision table over `StepCharacteristics`, one-directional safety
floors, and override-with-rationale. The pilot's accountable workflow is ready
as input, and its steps already carry characteristics.

Note for phase 4: the `COOPERATION_READY` gate currently refuses with "not
implemented yet (phase 4)". Replacing that criterion is phase 4's job, and
`_criteria_for()` in `workflow_promotion.py` is where it goes.

## Exact starting point for next agent

Branch `feature/human-cooperative-workflow-runtime` @ head.
Read: `docs/promotion-state-reference.md` → `adr-proposals/adr-006` (cooperation
engine) → `docs/schema-reference.md` (`StepCharacteristics`, `ExecutorClass`,
`autonomy_rank`, `SafetyFloor`).
Import surface you now have: `promote`, `assess`, `accept_risk`,
`next_maturity`, `is_valid_transition`, `PROMOTION_PATH`, `LAST_ENFORCED`;
ledger accessors for drafts, reports, acceptances, promotions and artifacts.
Current suite: **336 passed, 5 skipped**. Do not touch any file listed FROZEN
in directive §3.
