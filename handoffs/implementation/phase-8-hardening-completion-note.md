# Agent Completion Note — Phase 8: hardening and pilot

**Phase:** 8 of 9 — targets Gate G (part). **Closes Gate C.**
**Branch:** `claude/handoff-master-verification-37e5d2` @ `8e5ab14` onward.
**Implemented by:** `claude-opus-5` in the Codex implementation role.

## Scope completed

| Deliverable | Status |
|---|---|
| Gate C false-positive review | **done** — `handoffs/reviews/gate-c-false-positive-review.md` |
| `examples/workflows/substack-publication/README.md` | **done** — §10's last artifact |
| `docs/pilot-walkthrough.md` | **done** |
| `docs/lifecycle-overview.md` | **done** |
| `artifacts/test-baseline.txt` | already committed at phase 1 |
| Release verification report | **done, with a stated limitation** — see below |
| Jules's independent verification | **not done — cannot be** |

§10 is now complete: **8 of 8 pilot artifacts**. §18 is at **9 of 13**; the
remaining four (release notes, packaging guide, and the two contributor guides)
are phase 9's, and the two contributor guides already exist as sections inside
`validator-rule-catalog.md` and `cooperation-classification-guide.md` — phase 9
should decide whether §18 wants them as separate files or whether the sections
satisfy it.

## Tests run and results

```
xvfb-run -a .venv/bin/python -m pytest -q     # as CI runs it
682 passed, 1 skipped

.venv/bin/python -m pytest -q                 # no display
642 passed, 41 skipped
```

From 622 / 582+40 at phase 7b. **60 new tests, zero regressions, zero tests
weakened.**

## What the Gate C review actually found

Phase 2 left this open honestly: "the evidence so far is one clean fixture
reporting zero plus 80 tests. A real review needs more genuine workflows."

Three new workflows were written in unrelated domains — incident response,
hiring, board assembly — as a practitioner would write them rather than tuned to
satisfy the rules, and chosen for the classic traps: a legitimate terminal step
reading as a dead end, same-actor steps reading as a handoff, a cycle reading as
unreachable, `next_step: null` reading as an unhandled failure.

**All three report zero findings.** The twelve structural rules are not a
false-positive risk on this evidence, and phase 2's deliberate narrowing of
HW-004 and HW-007 holds up.

### The defect

HW-014's term regex anchored `\b` on the **leading edge only**, so an ambiguous
term matched as a prefix of a longer, precise word: `good` in "goods receipt",
`clean` in "cleanroom", `ok` in "okra", `complete` in "completeness". Eight
confirmed cases, all reporting precise exit conditions as vague.

Not a policy question — the match was wrong by the rule's own stated intent.
Fixed, with eight regression cases plus one that the terms still fire as whole
words, so the fix cannot buy silence by breaking detection.

The committed pilot artifacts are byte-identical before and after. The pilot
happened to contain no substring collisions, which is precisely why this
survived to phase 8.

### The residual, measured and accepted

Three perception terms have precise non-perceptual senses — "wiped **clean**
with IPA", "the **quality** inspection report QA-114", "the last **good**
self-check". Two memory phrases fire on machines — "the cache **remembers**",
"an **undocumented** field".

Neither is fixable by a deterministic keyword scan, because telling them apart
requires knowing what the sentence is about. The alternatives were considered
and rejected in writing: dropping the terms loses the common true positives, an
unbounded exception list destroys the predictability the catalog promises, and a
model is forbidden in an authoritative path.

**Accepted and documented** rather than papered over — HW-013 and HW-014 are
non-blocking exactly so this is survivable, and the finding names the term it
matched so an operator can accept it in one action with a reason. Recorded in
`tasks/backlog.md` as a rule-policy decision for whoever owns the rule set.

## Two things found that were not on the list

### The rule catalog claimed to be generated. There is no generator.

`docs/validator-rule-catalog.md` said it was "generated from
`src/governance/workflow_rules.py`, so this catalog cannot drift" and told the
reader to "regenerate it when the registry changes". No generator exists in this
repository and none ever did — the no-drift claim rested entirely on whoever
edited a rule remembering to edit the catalog.

`TestRuleCatalogMatchesTheRegistry` now enforces what the document promised:
every rule's id, title, dimension, blocking policy, description and remediation,
plus the published HW-013 and HW-014 term lists. Verified by three mutations —
flip a blocking policy, reword a remediation, add a term — each caught, each
naming what moved. The explanatory prose stays hand-written, which is why
generating the whole document would have been a step backwards.

### `examples/` is not in the wheel

Found by the clean-install check. The PyInstaller spec bundles it so the
end-user binary is fine; only the wheel is affected, and §15.7 names "bundled
schemas and examples" as a check that had never been made either way.
**Phase 9 should decide and document it rather than discover it.**

## Decisions made

1. **Gate C closes on measured residual, not zero residual.** A review that
   demanded zero false positives from a keyword heuristic would either never
   close or would close by deleting the rule's usefulness. Quantifying what
   remains, and why each alternative is worse, is what the gate can honestly ask
   for.
2. **The boundary bug was fixed; the phrase lists were not touched.** Fixing an
   objectively wrong match is a different act from narrowing a published rule's
   detection policy. The catalog is a contract and that decision belongs to its
   owner.
3. **The walkthrough was written by running it.** Every command executed, every
   output pasted from the real run. This caught two errors prose alone would
   have shipped.
4. **Guard fixtures are discovered by glob, not listed.** The next fixture added
   is guarded automatically, and a companion test fails if the set ever drops
   below four domains.
5. **The verification report states that it is not independent.** §11.7 assigns
   verification to Jules *for the independence*, and an agent that wrote the
   code cannot supply that by asserting it. Better to hand Jules evidence and a
   clear statement of what is still missing than to file a report that reads as
   complete.

## Assumptions

- `uncharacterized-workflow.yaml` is meant to report findings and is skipped by
  the clean-fixture guard by name. If it is ever repaired into a clean workflow,
  that skip becomes wrong.

## Known limitations

- **Jules's independent pass has not happened**, and this agent cannot invoke
  it. Operator action, still open against Gate G.
- **Grok Build's adversarial fixture pass (§11.4) has not happened.** The three
  hand-written fixtures close Gate C; generated adversarial ones would be a
  cheap strengthening the plan budgeted for.
- **No pytest coverage of PyInstaller packaging.** CI builds and smoke-tests a
  binary on three OSes; that is evidence, but not in the suite. Phase 9.
- **The `examples/` wheel question is stated, not decided.** Phase 9.
- **Old-version load is now tested, but there is only one schema version.** The
  tests pin the current behaviour — missing `schema_version` defaults, a future
  version loads and is recorded, unknown fields are refused by name — so the
  first real migration has a baseline to change deliberately.

## New risks or defects

Unchanged and still the most substantive item on the list:

- **Three Jules commits on FROZEN or phase-owned files remain unreviewed.**
  `src/runtime/ledger.py` (241 lines, `301ca83`) is the largest. The
  `state_machine.py` review found a real latent hazard behind a change that
  preserved behaviour and passed 559 tests, so "the suite is green" is already
  known not to settle this.
- **The FROZEN list is unenforced prose.** Branch protection or a CI check on
  the seven paths. Phase 9.

## Recommended next action

**Phase 9 — packaging and release documentation**, the last phase:

- `docs/release-notes.md`, `docs/packaging-guide.md`, and a decision on whether
  §18's two contributor guides need to be separate files;
- `packaging/*` and root `README.md` — phase 9 is the **sole** phase permitted
  to edit the spec;
- verify the binary on Linux or document a blocker (§2.3);
- decide the `examples/`-in-wheel question;
- **make the FROZEN list mechanical** — it is a packaging-adjacent CI change and
  this is the last chance before release.

Two items outlive phase 9 and need an operator, not an agent: **Jules's
independent verification pass**, and **a review of the three remaining Jules
commits**.

## Exact starting point for next agent

Branch `claude/handoff-master-verification-37e5d2` @ head, which is
`claude/phase-7-desktop` and `feature/human-cooperative-workflow-runtime` after
the merge described in `handoffs/reviews/branch-inventory.md`.

Read `handoffs/handoff-master.md` §18 and §2.3 first, then
`handoffs/implementation/release-verification-report.md` for what is verified
and what is not, then this note.

Run the suite **both ways**. Current: **682 passed, 1 skipped** (xvfb) /
**642 passed, 41 skipped** (no display).

A worktree needs its own venv — the repo-root one is an editable install
pointing at the main checkout, so imports resolve there and you will test the
wrong tree without noticing.

`src/runtime/state_machine.py` was edited in phase 7b on explicit operator
delegation. Every other FROZEN file in directive §3 is untouched and stays that
way.
