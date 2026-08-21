# Branch inventory and recommendations

**Date:** 2026-08-21. Every remote branch, checked against `origin/main` and
against the release branch `feature/human-cooperative-workflow-runtime`.

## The live branches

| Branch | Head | Ahead of main | Recommendation |
|---|---|---|---|
| `main` | `9273374` | — | Keep. Does **not** contain the release work. |
| `feature/human-cooperative-workflow-runtime` | `7d9a9c4` | 56 | Keep — the release integration branch. Phases 1–6 merged. |
| `claude/phase-6-cli` | `7d9a9c4` | 56 | **Delete.** Identical commit to the feature branch; phase 6 is merged and closed. |
| `claude/phase-7-desktop` | `6b33657` | 61 | Keep until this branch merges into it. Local only, never pushed. |
| `claude/handoff-master-verification-37e5d2` | this work | 61 + | Merge into `claude/phase-7-desktop`, then that into the feature branch. |

## Fully superseded — safe to delete

| Branch | Why |
|---|---|
| `claude/resume-from-handoff-gx3at8` | 0 ahead, 30 behind, merged into main. |
| `release/v1-human-runtime` | 0 ahead, 30 behind, merged into main. The v0.1.0 tag is the durable record. |
| `jules-10749710553318904718-2cfb5225` | 0 ahead, merged. |
| `fix/unused-import-app-7512446294262378718` | 0 ahead, merged. |
| `fix/test-app-entry-4805474542911117311` | 0 ahead, merged. |
| `refactor-ledger-schema-2696240816656306523` | 0 ahead, merged. **See the caveat below.** |
| `jules-14199667656236827410-ac71b3dc` | 1 ahead, but that commit is a merge of `main` into itself — zero unique content. Its actual contribution (`bb5feff`, Graph Spec validation tests) is already in main. |

## `feature/smevals-integration` — delete, verified redundant

4 commits ahead of `main`, 0 behind, not merged — which reads as unmerged work.
It is not. Three of the four commits are already on the release branch under
different hashes (`287baea`, `0f1ad37`, `ba8a3c1` — ADR-008, the integration
design, and the optional smevals backend). The fourth, `3af51d6` ("skip the GUI
dispatch test when the GUI stack is absent"), is also carried; the release
branch has the same change with slightly reworded prose.

Verified by tree diff: `claude/phase-7-desktop` contains everything
`feature/smevals-integration` has, plus ~13,000 lines it does not.

**Delete it.** Leaving it is worse than untidy — a branch that reads as
"4 ahead, unmerged" invites someone to merge it, which would revert the reworded
docstring and add nothing.

## The caveat on the Jules branches

`refactor-ledger-schema-2696240816656306523` and its siblings are merged and
deletable *as branches*. That is a separate question from whether their content
was ever reviewed. Four Jules commits touched files the directive lists as
FROZEN or as owned by a specific phase:

| Commit | File | Lines | Owner per directive §3 |
|---|---|---|---|
| `3d3bea4` | `src/runtime/state_machine.py` | 128 | **FROZEN** |
| `301ca83` | `src/runtime/ledger.py` | 241 | phase 3 |
| `693328b` | `src/foundry/validator.py` | — | — |
| `0f2d6b4` | `src/governance/maturity.py` | — | — |

`state_machine.py` has now been reviewed — see
`jules-state-machine-refactor-verdict.md`, which found a real latent hazard
behind a behaviour-preserving change. **The other three have not.** `ledger.py`
is the largest and the one most worth reading next.

Delete the branches; keep the review debt on the list.

## Recommendations

1. **Delete now:** `claude/phase-6-cli`, `claude/resume-from-handoff-gx3at8`,
   `release/v1-human-runtime`, `feature/smevals-integration`, and the four Jules
   branches. Nine branches down to three plus the working one.
2. **Do not delete `main`'s divergence from the feature branch by merging early.**
   The release branch is 56 commits ahead and phases 8–9 are unfinished; merging
   to `main` before Gate G is what the gate exists to prevent.
3. **Protect the FROZEN paths.** The branch cleanup above is cosmetic; this is
   not. Branch protection or a CI check on `src/runtime/state_machine.py`,
   `src/runtime/bundle.py`, `src/schemas/graph.py`, `src/schemas/bundle.py`,
   `src/kernel/*`, `src/security/*` and `src/foundry/generator.py` would have
   stopped all four unsanctioned edits. Prose did not.
4. **Review `ledger.py`'s Jules refactor** before Gate G, on the same standard:
   what guarantee did the old shape provide locally that the new shape moved
   somewhere else?

## Suggested commands

```bash
git push origin --delete claude/phase-6-cli claude/resume-from-handoff-gx3at8 release/v1-human-runtime feature/smevals-integration
```

```bash
git push origin --delete jules-14199667656236827410-ac71b3dc jules-10749710553318904718-2cfb5225 fix/unused-import-app-7512446294262378718 fix/test-app-entry-4805474542911117311 refactor-ledger-schema-2696240816656306523
```
