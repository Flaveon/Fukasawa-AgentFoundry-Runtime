# Agent Completion Note — Phase 4: Cooperation Assessment

**Phase:** 4 of 9 — targets Gate E (first half).
**Branch:** `feature/human-cooperative-workflow-runtime`.
**Implemented by:** `claude-fable-5` in the Codex implementation role.

## Scope completed

- **`src/governance/cooperation.py`** — the deterministic decision table,
  safety floors as one-directional ceilings, `assess_step`, `assess_workflow`,
  `apply_override`, and the two gate helpers (`unassessed_steps`,
  `steps_not_ready`).
- **`COOPERATION_READY` gate wired** — the placeholder criterion phase 3 left
  behind is replaced with real checks, and `assessments` now threads through
  `assess()` / `promote()`.
- **`docs/cooperation-classification-guide.md`** — generated from the live
  table, so the published policy cannot drift from the one that runs.
- **`examples/workflows/substack-publication/cooperation-assessment.yaml`** —
  the pilot's stage-4 artifact, including one recorded human override.
- **`tests/test_cooperation.py`** — 40 tests.

## Files changed

Created: `src/governance/cooperation.py`, `tests/test_cooperation.py`,
`docs/cooperation-classification-guide.md`,
`examples/workflows/substack-publication/cooperation-assessment.yaml`, this
note. Modified: `src/governance/workflow_promotion.py` (gate + threading),
`src/runtime/ledger.py` (see the defect below).

## Tests run and results

```
.venv/bin/python -m pytest -q
376 passed, 5 skipped      # 336 before + 40 new; 0 regressions
```

## The pilot's assessment

| Step | Executor | Floor | Readiness |
|---|---|---|---|
| capture-idea | HUMAN_LED_AI_ASSISTED | — | PILOT |
| scope-check | HUMAN_ONLY | — | NOT_READY |
| deep-research | HUMAN_LED_AI_ASSISTED | — | PILOT |
| draft-article | HUMAN_ONLY | — | NOT_READY |
| request-artwork | AGENT_EXECUTED_HUMAN_SUPERVISED → *overridden* to HUMAN_LED_AI_ASSISTED | — | READY |
| review-and-approve | HUMAN_ONLY | IRREVERSIBLE | NOT_READY |
| **publish-post** | **AGENT_PREPARED_HUMAN_APPROVED** | **IRREVERSIBLE** | PILOT |
| archive-notes | DETERMINISTIC_AUTOMATION | — | READY |

`publish-post` is the one to look at: an agent may **prepare** the publication,
but a human authorizes it, because an email to subscribers cannot be unsent.
That is the seeded pilot problem "AI can prepare but not authorize publication",
reached by the table rather than hand-placed. Scope control stayed human, and
only genuinely mechanical work automated.

## Decisions made

1. **Floors are ceilings, applied after the base recommendation.** Risk,
   reversibility and sensitivity are deliberately *not* read by the base table,
   so raising one can only ever restrict a recommendation. A test asserts the
   same step is never more autonomous with a floor than without.
2. **A floor is recorded even when the base was already more cautious.** The
   floor governs what an override may later do, so losing it would quietly
   unlock the step.
3. **`DETERMINISTIC_AUTOMATION` ranks below `AGENT_EXECUTED_HUMAN_SUPERVISED`.**
   Ranking follows delegated judgment, not absence of humans — a script has no
   latitude to misjudge. Documented and tested because the opposite ordering is
   the intuitive one.
4. **A second override is judged against the first**, so an override cannot be
   used to climb back toward autonomy in two hops.
5. **`apply_override` returns a copy.** The caller's assessment is left alone;
   a refused override must not leave a half-mutated object behind.
6. **Assessments are not persisted this phase.** The file map gives phase 4 no
   ledger table, and the gate takes assessments as an argument instead. Noted
   as a limitation rather than quietly expanded into.
7. **`required_tools` is matched, never inferred.** With no declared systems it
   reports none — guessing what a step touches would put unearned confidence
   into an agent's permissions at export.

## A defect this phase found in phase 3

Promoting the pilot to `COOPERATION_READY` was refused with "version 1 has
already been promoted". The phase-3 dedupe keyed the artifact table on
`(workflow_id, version)`, but a workflow climbs several maturity steps at the
**same draft version**, and each step is its own artifact — the maturity
contract requires previous artifacts to remain available. Keying on version
alone made the second promotion look like a duplicate of the first.

Fixed: the key is now `(workflow_id, version, maturity)`,
`load_accountable_workflow` filters on both independently, and a new
`has_accountable_artifact()` backs the dedupe check. The pilot now stores
`('1', ACCOUNTABLE)` and `('1', COOPERATION_READY)` side by side.

**This changed a table added in the previous commit.** It is unreleased, so no
migration is required for anyone, but `docs/migration-notes.md` describes that
table and should be re-read next time it changes.

## Assumptions

- The base table reads three factors and the floors read three others. That
  split is a judgement call: it is what makes floors monotonic, but it means a
  low-risk one-off and a high-risk one-off get the same base recommendation and
  differ only by floor.
- Gating tightens `SPOT_CHECK` to `APPROVAL_REQUIRED` and leaves other modes
  alone, on the reasoning that a gate is evidence a human already wanted eyes on
  it.

## Known limitations

- **No persistence for assessments.** They are produced, returned, and written
  to the pilot artifact, but nothing stores them in the ledger. Save/reload of
  this stage is not yet possible — a table is needed, and phase 4 does not own
  `ledger.py` for that purpose.
- **No CLI surface** until phase 6.
- **`required_tools` is substring matching** against declared system names. It
  will miss a system referred to by a synonym.
- **The `COOPERATION_READY` gate refuses while any step is
  `NOT_READY_FOR_AUTOMATION`.** That is arguably too strict: a workflow may
  legitimately keep a step permanently with a person. Today the operator must
  override such a step to something explicit. Worth revisiting with real
  workflows before Gate E closes.
- No LLM-assisted classification, deliberately. It remains a non-feature.

## New risks or defects

- Nothing new for the register.
- For phase 5: the export must respect `effective_executor`, not
  `recommended_executor` — an override is the human's decision and is what
  governs. Easy to get wrong, so it deserves an explicit test there.
- Also for phase 5: `BOUNDED_AUTONOMOUS_AGENT` exports **only** with an
  explicit approval gate, and `NOT_READY_FOR_AUTOMATION` steps must not export
  to an agent at all.

## Recommended next action

Phase 5 (cooperative builder + export): `src/foundry/workflow_export.py`,
mapping executor classes onto `TaskDepth` and `AgentSpec`, and feeding the
existing `generate_packages`. The pilot has everything it needs — accountable
workflow, assessments, and one override to prove the export honours human
decisions over table output.

## Exact starting point for next agent

Branch `feature/human-cooperative-workflow-runtime` @ head.
Read: `docs/cooperation-classification-guide.md` → `adr-proposals/adr-006`
§"Export mapping" → `docs/schema-reference.md` (`StepAssignment`,
`CooperativeWorkflow`).
Import surface: `assess_workflow`, `assess_step`, `apply_override`,
`steps_not_ready`, `unassessed_steps`; `promote(..., assessments=...)`.
Current suite: **376 passed, 5 skipped**. Do not touch any file listed FROZEN
in directive §3.
