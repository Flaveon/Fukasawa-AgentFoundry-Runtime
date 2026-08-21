# Branch inventory and recommendations

**Date:** 2026-08-21. Every remote branch, checked against `origin/main` and
against the release branch `feature/human-cooperative-workflow-runtime`.

> **Executed 2026-08-21.** Phase 7b merged into `claude/phase-7-desktop`,
> that fast-forwarded into `feature/human-cooperative-workflow-runtime`
> (`7d9a9c4` → `913aaef`) and pushed to origin, then the nine branches below
> were deleted. Eleven remote branches are now two: `main` and the feature
> branch. The verification that preceded each deletion is recorded under
> "What was checked before deleting".

## The live branches

| Branch | Head | Ahead of main | Recommendation |
|---|---|---|---|
| `origin/main` | `d9ed8db` | — | Keep. Does **not** contain the release work. |
| `feature/human-cooperative-workflow-runtime` | `913aaef` | 61 | Keep — the release integration branch. Phases 1–7b merged and pushed. |
| `claude/phase-6-cli` | `7d9a9c4` | 56 | **Deleted**, remote and local, with its worktree. Ancestor of the feature branch; phase 6 merged and closed. |
| `claude/phase-7-desktop` | `913aaef` | 61 | Local only, never pushed. Now an ancestor of the feature branch and deletable; kept as a live worktree. |
| `claude/handoff-master-verification-37e5d2` | `913aaef` | 61 | Merged. Same — deletable, kept as a live worktree. |

**Note on the local `main`:** it sits at `9273374`, **30 commits behind
`origin/main` (`d9ed8db`)**. An earlier draft of this table quoted that stale
SHA as origin's. It also makes `git branch -d` misjudge merged-ness, since `-d`
compares against the checked-out branch — check `merge-base --is-ancestor`
against the branch that actually carries the work instead of reaching for `-D`.

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

## What was checked before deleting

Not "0 ahead of main" — that test is wrong for a branch whose content was
rebased, and it would have kept `feature/smevals-integration` forever. What was
actually verified, per branch:

```
git rev-list --count origin/<branch> --not origin/main origin/feature/...
```

Seven branches returned **0** — every commit reachable from another surviving
ref. Two did not, and each was cleared by tree diff instead:

* **`feature/smevals-integration`** (4 unreachable commits). Its content is
  carried under different hashes. The tree diff against the feature branch is
  22,903 deletions and 52 insertions, and **every one of those insertions is a
  regression**: a backlog item marked incomplete that has since been done, an
  older docstring, and `@patch("src.gui.services.generate_packages")` — a patch
  target that has been broken since services became a package.
* **`jules-14199667656236827410-ac71b3dc`** (1 unreachable commit, a merge of
  `main` into itself). Its only unique content is `pr_description.md`, a stray
  file **deliberately removed** in `344e4f0`, plus older copies of
  `ledger.py` and `state_machine.py`.

And one deletion had a real precondition rather than a formality:
`release/v1-human-runtime` is only safe to delete if the release it points at
survives. Verified: the `v0.1.0` tag exists on origin
(`refs/tags/v0.1.0` → `9d49d56`) and that commit is an ancestor of
`origin/main`.

## Recommendations

1. **Delete now:** *(done — see the note at the top)* `claude/phase-6-cli`, `claude/resume-from-handoff-gx3at8`,
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

## What remains open

Items 3 and 4 above are the ones that outlive this cleanup: **protect the
FROZEN paths mechanically**, and **review the remaining three Jules commits** —
`ledger.py` (241 lines) first. Deleting the branches removed the clutter, not
the review debt.

Local `main` is 30 behind `origin/main` and should be updated before anyone
works from it.
