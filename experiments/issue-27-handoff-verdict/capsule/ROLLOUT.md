# Issue #27 — Rollout Plan for `package-consistency-checker`

**Not promoted. Requires owner review and approval (issue #27 checklist item
6).** Nothing in this directory, `src/governance/package_consistency.py`, or
`experiments/issue-27-handoff-verdict/shadow.py` is wired into the real Q2C
pipeline. `~/pipeline` and `~/substack` were never modified by this work.
The capsule at `process_capsule.yaml` is a promotion-review artifact,
`maturity: draft`, `depth_level: 0` — it documents what the capability
*would* do if promoted, not a thing that currently runs against production.

## Stages (each requires explicit owner approval before moving to the next)

1. **Shadow (current stage).** The rule runs only inside this experiment,
   over the frozen dataset in `dataset/`. It reads nothing from
   `~/substack` at run time — all real-case data was extracted once, by
   hand, into sanitized fixtures (`extract.py`, already run; see
   `dataset/manifest.json`'s `sha256` provenance). It writes only
   `results/treatment.json` and `results/comparison.md`. No pipeline run,
   no handoff, no quality report is touched. **Reversible by construction:
   there is nothing to roll back at this stage** — delete this directory
   and nothing else in the system changes.

2. **Advisory (not started).** Would require: (a) owner approval of this
   capsule's scope and the label definitions in `PROTOCOL.md`; (b) wiring
   the pipeline (or a sidecar script reading its output tree) to call
   `check_package_consistency()` after `build_duath_operator_handoff()` and
   `build_package_quality_report()` both run for a real run_id, and write
   its verdict to a new, clearly-labelled advisory field (e.g. a
   `consistency-check.json` next to `quality-report.json`) that a human can
   read alongside the existing documents. The rule's output would have NO
   effect on what ships, what gets deleted, or what the handoff says. Owner
   approval gate: review real advisory output over at least one full
   production week before considering stage 3.

3. **Blocking (not started).** Would require: (a) owner approval of stage
   2's advisory track record; (b) a decision about what BLOCK/ABSTAIN
   should actually prevent (e.g. withhold the handoff from an operator's
   "ready to ship" queue, or add a loud banner to it — NOT auto-delete
   anything, NOT auto-publish anything); (c) a second, independent review
   of the implementation (per `AGENTS.md`: "No autonomous coding agent may
   approve its own PR, change governance policies, or deploy unattended to
   production").

No stage after Shadow exists yet. This document records the plan for
discussion, not a schedule.

## Rollback

**v2 note (post-review — see PROTOCOL.md Amendment 3, M3):** an earlier
version of this section said rollback was "delete
`experiments/issue-27-handoff-verdict/` and
`src/governance/package_consistency.py`, and revert
`tests/test_package_consistency.py`" — that list was actually tried
(delete `package_consistency.py` in a scratch copy) and it broke the
suite, because it omitted `tests/test_package_consistency_rollback.py`
(which imports the rule directly) and `shadow.py` (which is unusable
without it). The list below was verified by actually deleting every file
on it, in a scratch copy of this worktree, and confirming the full suite
(`.venv/bin/pytest -q`) still passes: **1159 passed, 64 skipped, 0
failed** — nothing outside this list depends on the rule.

### From Shadow (current state)

Nothing is wired in. Rollback is: delete every one of these files —

* `src/governance/package_consistency.py` (the rule itself)
* `tests/test_package_consistency.py`
* `tests/test_package_consistency_rollback.py`
* `experiments/issue-27-handoff-verdict/shadow.py` (its only purpose is
  running this rule; it has no function without it)
* `experiments/issue-27-handoff-verdict/capsule/` (this file and
  `process_capsule.yaml` — a promotion-review artifact for a rule that no
  longer exists)

— and nothing else. `experiments/issue-27-handoff-verdict/PROTOCOL.md`,
`CANDIDATES.md`, `extract.py`, `baseline.py`, `rerun_timeouts*.py`, and
everything under `results/` are NOT part of this rollback: they record
history (the dataset, the baselines, the review, the decision to build
and then retire this rule) and do not import or depend on the rule module.
`tests/test_package_consistency_rollback.py::test_rest_of_src_does_not_import_the_rule`
is the automated version of this claim for everything under `src/`; the
full-suite run above is the automated version of it for the whole repo.

### From a future Advisory or Blocking stage (what it would need; none exists yet)

No Advisory or Blocking integration point has ever been built — this
capsule has never been wired into anything live, so there is nothing
concrete to describe rolling back FROM yet. What a real integration point
WOULD need, so that a future rollback from it is actually testable (unlike
the impossible "re-run the rollback test against a live integration
point" step this section used to have — there was never a live
integration point to run it against):

1. **A named, single call site** — e.g. a sidecar script invoked after a
   real pipeline run, or a wrapper that reads the pipeline's output tree —
   that is the ONLY place `check_package_consistency()` is called outside
   of this experiment and its tests. Not scattered call sites.
2. **A disable switch that does not require a code change** — e.g. an
   environment variable or config flag the integration checks before
   calling the rule at all, so "rollback" at that stage can be "flip the
   switch" before it is ever "delete files and redeploy".
3. **A test, scoped to that integration's own test suite, that imports the
   call site module with the rule's import blocked** (the same
   `sys.modules[...] = None` technique
   `test_baseline_a_runs_with_the_rule_module_unimportable` uses here) and
   asserts the integration's normal operation — whatever that turns out to
   mean at that stage — is unaffected. That test would be the real,
   stage-appropriate successor to this file's rollback tests; it cannot be
   written now because the call site it would test does not exist yet.

## Automated rollback tests

`tests/test_package_consistency_rollback.py` proves two narrower, verified
claims rather than modelling "disabled" as a stub that always answers
CONSISTENT (the exact fail-open behavior the H1 rewrite exists to
eliminate — see CANDIDATES.md):

* Baseline A's computation does not import or call the rule — checked
  statically (its source never names the rule) AND at runtime (it still
  produces correct output with the rule module blocked from being
  imported at all).
* Nothing else under `src/` references the rule module, so deleting
  `src/governance/package_consistency.py` cannot silently break anything
  outside the file list above.

A third test pins that `shadow.py`'s only dependency on the rule is one
removable import line, supporting this file's claim that deleting
`shadow.py` alongside the rule is a complete, clean removal.

## Known failures and escalation (summary; full detail in `process_capsule.yaml`)

Every failure mode this capsule can hit resolves to `ABSTAIN` with
`escalation_target: "human operator"` — never to a silent pass. See
`process_capsule.yaml`'s `known_failures` and `escalation_rules`, and
`src/governance/package_consistency.py`'s docstring for the full boundary
list (what this capsule does NOT check).
