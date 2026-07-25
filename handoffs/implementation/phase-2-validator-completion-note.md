# Agent Completion Note — Phase 2: Validator

**Phase:** 2 of 9 (validator) — targets Gate C.
**Branch:** `feature/human-cooperative-workflow-runtime`.
**Authorized by:** `handoffs/reviews/codex-implementation-directive.md` §2 and §4.
**Implemented by:** `claude-fable-5` acting in the Codex implementation role.

## Scope completed

- **`src/governance/workflow_rules.py`** — the rule registry and all sixteen
  rules `HW-001`…`HW-016`, at exactly the severities and blocking policies
  fixed in directive §4 (14 blocking, 2 advisory). Plus `WorkflowIndex`, which
  precomputes step ids, reachability, and gate lookups once so no rule walks
  the workflow twice, and `validate_workflow()`, which returns a deterministic
  `ValidationReport`.
- **`tests/test_workflow_rules.py`** — 80 tests. Every rule has both halves of
  the required pair.
- **Two fixtures** in `tests/fixtures/workflows/`:
  - `clean-workflow.yaml` — a realistic well-formed workflow that must report
    **zero** findings. This is the false-positive guard and the baseline every
    positive test mutates.
  - `uncharacterized-workflow.yaml` — the adversarial sparse capture flagged in
    the phase-1 note: barely anything filled in, nothing characterized.
- **Pilot artifacts** — `validation-report.json` and `validation-report.md`
  emitted into `examples/workflows/substack-publication/`.
- **`docs/validator-rule-catalog.md`** — generated from the registry, so the
  catalog cannot drift from the code. Includes the contributor guide for adding
  a rule.

## Files changed

Created: `src/governance/workflow_rules.py`;
`tests/test_workflow_rules.py`; `tests/fixtures/workflows/clean-workflow.yaml`;
`tests/fixtures/workflows/uncharacterized-workflow.yaml`;
`docs/validator-rule-catalog.md`;
`examples/workflows/substack-publication/validation-report.{json,md}`; this note.

**No existing file was modified.** No FROZEN file was touched.

## Tests run and results

```
.venv/bin/python -m pytest -q
249 passed, 4 skipped in 7.01s     # phase-1 total 169 + 80 new; 0 regressions
```

Pilot validation, reproduced: **24 findings — 14 blocking, 10 advisory,
promotion BLOCKED.** Twelve of sixteen rules fire; `HW-001`, `HW-007`, and
`HW-016` correctly stay silent because the pilot satisfies them.

## Decisions made

1. **The clean fixture is the baseline for every positive test.** Each rule's
   positive case is a *copy* of the zero-findings workflow with exactly one
   defect introduced, so a fired finding is attributable to that defect and the
   test can assert the exact rule id, location, field, severity, and policy.
   This also makes "no false positive on nearby valid cases" structural rather
   than a separate test I might forget to write.
2. **HW-004 is deliberately narrower than its title.** It demands a decision
   authority only where a decision genuinely exists — the step branches, a gate
   guards it, or its effect is irreversible or high-risk. Requiring one from
   every purely linear step would have put noise on every well-formed workflow.
   Documented in the catalog and covered by an explicit "does not demand
   authority from a purely linear step" test.
3. **HW-007 is narrowed the same way.** A terminal step that produces an output
   is a legitimate ending. A dead end is arriving somewhere that yields nothing
   *and* goes nowhere.
4. **HW-011 matches failure descriptions by word overlap at a 50% threshold.**
   Exact matching would be useless — nobody restates a failure the same way
   twice — and anything cleverer would stop being predictable. The threshold is
   documented rather than tuned in secret.
5. **HW-016 stays silent when the outcome is undefined**, because HW-002 owns
   that defect and reporting both would be two findings for one root cause.
6. **HW-005 ignores a gate's `on_reject`.** That field may legitimately hold a
   stated action rather than a step id, so HW-015 judges it instead.
7. **Finding ids are derived, not counted** — `HW-003:publish-post/actor`.
   Findings are persisted and referenced by risk acceptances, so a stable id is
   a correctness requirement, not a nicety.
8. **The pilot's JSON report excludes `evaluated_at`** so regenerating an
   unchanged workflow yields a byte-identical file that is diffable in review.
   The exclusion is stated in the report itself.

## A defect the tests caught in my own rule

My first implementation of HW-014 suppressed any text containing a criterion
signal such as "when". That let **"Payment is done when it looks fine"** pass —
a false negative on exactly the phrase the rule exists to catch. The fix splits
vague language into two classes: **perception words** (`looks`, `feels`,
`fine`, …) are always reported because no surrounding grammar makes them
checkable, while **state words** (`ready`, `complete`, `approved`, …) are
reported only when no criterion accompanies them. So
`approved when at least one reviewer has signed it` is accepted and
`approved when it looks right` is not. The clean fixture still reports zero and
the pilot's HW-014 count is unchanged at 4.

## Assumptions

- Directive §4's blocking table is authoritative and not mine to adjust; a test
  (`test_registry_matches_the_approved_blocking_table`) fails if it drifts.
- Severity is derived from policy (blocking → `ERROR`, advisory → `WARNING`);
  also test-enforced.
- The pilot's report artifacts are generated by a throwaway script rather than a
  committed command, because the CLI that will regenerate them
  (`fukasawa workflow validate --json`) belongs to phase 6, which owns
  `src/cli.py`.

## Known limitations

- **The Gate C false-positive review is started, not finished.** The evidence
  so far is one clean fixture reporting zero plus 80 tests. A real review needs
  more genuine workflows than the two fixtures and the pilot — worth Grok
  Build's adversarial fixture pass (master handoff §11.4) before Gate C closes.
- **HW-013's phrase list is English and literal.** It will miss paraphrases
  ("it's all in Dave's head" matches; "Dave is the only one who knows" does
  not). Advisory severity limits the damage.
- **HW-011's 50% threshold is a judgement call.** It works on the pilot and the
  fixtures; it will need tuning against real captures.
- No persistence: findings and acceptances are not stored anywhere yet. That is
  phase 3, which solely owns `src/runtime/ledger.py`.
- No CLI or GUI surface. `validate_workflow()` is importable but has no
  operator-facing entry point until phase 6.
- The catalog is generated by a script run by hand. Wiring that into a test or a
  make target would stop it silently aging; backlogged.

## New risks or defects

- **R9 is now partly measured rather than only feared.** The advisory pair
  produces 10 of the pilot's 24 findings — 42% of the report is non-blocking
  signal. On a messier real workflow that ratio will grow, and a report where
  most lines are advisory trains people to skim. Worth considering a
  `--blocking-only` view when the CLI lands in phase 6.
- New, small: `_describes_same_failure` and the `HW-013` scan are the only two
  rules whose behavior depends on English wording. If the product ever
  validates non-English workflows, those two need rethinking. Recorded rather
  than solved.

## Recommended next action

Phase 3 (promotion and persistence). Add the additive ledger tables, then
implement `src/governance/workflow_promotion.py`: the maturity transition table
enforced through `RUNTIME_READY`, blocking findings gating promotion, risk
acceptance requiring actor + timestamp + rationale, and promotion emitting an
`AccountableWorkflow` artifact that leaves the source draft untouched.

The pilot is ready to promote **once its blocking findings are resolved** — so
phase 3 will also need a repaired copy of the pilot to promote. Recommend
`examples/workflows/substack-publication/observed-workflow.yaml` stays broken
(it is the validator fixture) and the repair happens as the promotion input,
which is exactly what `accountable-workflow.yaml` records.

## Exact starting point for next agent

Branch `feature/human-cooperative-workflow-runtime` @ head.
Read: directive §2 (phase 3 boundary) → `adr-proposals/adr-005` (promotion) →
`docs/schema-reference.md` (`AccountableWorkflow`, `PromotionLineage`,
`RiskAcceptance`) → `docs/validator-rule-catalog.md` (what blocking means).
Import surface you now have: `src.governance.workflow_rules.validate_workflow`
returning a `ValidationReport` with `.promotion_ready`, `.unresolved_blocking`,
and `.blocking_findings`; `RULES` and `BLOCKING_RULE_IDS` for policy lookups.
Current suite: **249 passed, 4 skipped**. Do not touch any file listed FROZEN
in directive §3.
