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

### From Shadow (current state)

Nothing is wired in. "Rollback" is: delete
`experiments/issue-27-handoff-verdict/` and
`src/governance/package_consistency.py`, and revert
`tests/test_package_consistency.py`. No other file in the repository, the
pipeline, or `~/substack` changes as a result, because nothing outside this
experiment ever reads this rule's output.

### From a future Advisory or Blocking stage (described for when it exists)

1. Remove (or comment out, with a dated note) the call site that invokes
   `check_package_consistency()` from wherever stage 2/3 wired it in.
2. Delete any sidecar output file the integration started writing (e.g. the
   hypothetical `consistency-check.json`).
3. Confirm the pipeline's own behavior (`build_duath_operator_handoff`,
   `build_package_quality_report`) is unchanged — this capsule never
   modifies either function; rollback should never need to touch
   `q2c_pipeline.py` at all, only the integration point that called into
   this capsule.
4. Re-run the automated rollback test below against a live integration
   point and confirm it reports "capsule disabled" behavior.

## Automated rollback test

`tests/test_package_consistency_rollback.py` proves the shadow runner's
disabled-capsule behavior: with the capsule treated as disabled (its rule
function simply not called), the shadow runner emits no rule findings at
all, and Baseline A's real-world numbers (what the pipeline's own handoff
documents actually say, independent of this capsule entirely) are
unchanged whether or not the capsule exists. This is the strongest
rollback guarantee available at the Shadow stage, since there is no live
integration point yet to disable.

## Known failures and escalation (summary; full detail in `process_capsule.yaml`)

Every failure mode this capsule can hit resolves to `ABSTAIN` with
`escalation_target: "human operator"` — never to a silent pass. See
`process_capsule.yaml`'s `known_failures` and `escalation_rules`, and
`src/governance/package_consistency.py`'s docstring for the full boundary
list (what this capsule does NOT check).
