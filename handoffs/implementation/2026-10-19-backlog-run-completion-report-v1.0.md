# Backlog run — completion report

**Status: READY_FOR_HUMAN_GATE**, not DONE. The engineering work the owner's
handoff asked for is finished, reviewed, and merged, and `main` is green. The
outcomes that remain need the owner's decision. They are listed at the end,
each with the reason it waits on the owner and the shortest next action.

Run window: 2026-10-17 to 2026-10-19. Plan and authority:
`2026-10-17-backlog-run-plan-v1.0.md`. Owner decisions:
`2026-10-17-owner-decision-packet-v1.0.md`.

## Where `main` stands

| | SHA | CI |
|---|---|---|
| At the start | `95d8867` | red since 2026-10-14 (one GUI test) |
| Now | `82cc3d0` | green, and green at every merge in between (`9f74923`, `34b40bc`, `21a5453`, `f7ffa83`, `82cc3d0`) |

The merged head is the SHA this report describes. This report is committed on
top of it, in PR #31, so it cannot contain its own commit's hash.

## Pull requests

Every PR was written in its own worktree, with its own virtual environment,
and checked independently by a separate Opus context before it was marked
ready. The owner did every merge: this session's permission policy refused
merging ("merge without review"), and nothing tried to get around that.

| PR | What | Independent review | Disposition |
|---|---|---|---|
| #28 | Red `main`: the Workflow tab's worker thread read Tk entry boxes. PR CI then exposed a second hazard: Tk objects garbage-collected on a worker. | 0da943e APPROVE_WITH_NITS; c26a501 APPROVE_WITH_NITS (it corrected my description of the mechanism) | merged `9f74923` |
| #29 | Tests were broken by forced colour, TTY switches and a narrow terminal: 65, 65 and 15 failures, now 0 | APPROVE_WITH_NITS; nits fixed | merged `34b40bc` |
| #30 | #27 M0: the May 31 plan archived byte-for-byte, plus a 63-row trace from the plan to current contracts | CHANGES_REQUIRED → APPROVE | merged `21a5453` |
| #32 | Gate G findings, plus the High issue F1: a paused run could resume under a changed brief | four rounds → APPROVE_WITH_NITS | merged `f7ffa83` |
| #33 | Second review of PR #26's ten fixes, plus keeping passwords out of computer addresses | six rounds → APPROVE; then **the owner found two more problems**; four more rounds → APPROVE_WITH_NITS | merged `82cc3d0` |
| #31 | This run's plan, the decision packet, the reconciled backlog, and this report | — (documents only) | open, for the owner |
| #34 | #27's first reasoning-to-rule case, measured in shadow, nothing promoted | three rounds → APPROVE_WITH_NITS | open draft, **needs owner review** |

### Mistakes in this run, recorded so they are not repeated

- **#33's credential fix opened two new holes before it was right.** The
  owner's review found that credentials in schemes other than http/https were
  never detected. My first fix found them only after a *valid* scheme. My
  second fix let a later `://` hide them. My third fix folded backslashes into
  slashes, which let `http://al\ice:pw@host` through. I also removed a check
  as "equivalent" when it was the one catching that case. Four review rounds
  found four ways to mislead a parser of where an address's authority ends.
  The final design does not parse at all: **any `@` in an address counts as a
  credential**. Lesson: when each fix opens the next hole, change the design
  instead of patching again.
- **#27's first rule failed open**, and its first report claimed the rule
  came from the model's diagnosis. It did not: the rule was drafted before the
  model answered. Both were caught by independent review. v1's results are
  kept, and each revision was recorded as a dated amendment before its code
  changed.
- **I overstated two results before they were checked.** One was #33's "no
  password on any surface", which was true only for the http shapes tested.
  The other was #27's headline, before review showed the local model had not
  missed any real blocker. Both were corrected in the PR descriptions.

## Required end state, checked

| Item | State | Evidence |
|---|---|---|
| GitHub inventory reconciled; required PRs merged | **Met** for the engineering PRs. #31 and #34 are open for the owner. | PR table above |
| #27's original source preserved, and all its acceptance requirements satisfied | **Partly.** Source preserved (M0). The rest needs the owner. #27 stays open. | #30; #34 |
| `main`'s CI, test and build matrix green at the reported SHA | **Met** | `82cc3d0`: test, Linux/macOS/Windows build, frozen-paths |
| PR #26 follow-up review and the three historical reviews have evidence and resolved findings | **Met** | #33; #32; reports in each PR |
| Formal release, product and promotion decisions have owner dispositions | **Not met: needs the owner** | decision packet |
| Backlog and release notes distinguish shipped, remaining and proposed work | **Backlog met** (#31). **Release notes not updated**: their test counts are stale. | `tasks/backlog.md` |
| Primary checkout clean and matching `origin/main`; other checkouts verified | **Met** | below |
| Task worktrees and branches removed only when safe; user files kept | **Met** | below |
| Completion report committed and pushed | this file, PR #31 | — |

## Model roles actually used

| Role | Requested | Used |
|---|---|---|
| Orchestrator, integration, small direct fixes | Opus 5.5 | Opus 5.5 |
| Implementation | Sonnet 5.5 | **Sonnet 5**: 5.5 is not available in this environment |
| Scouting and evidence | Haiku 5.5 | **Haiku 4.5** for the backlog inventory, which cited two paths that do not exist, so every tick was checked again by hand. **Sonnet 5** for the Q2C defect search. |
| Independent review | Opus 5.5 | Opus 5.5, each review in a separate context |

Fixes written directly by the orchestrator:
- the colour conftest;
- the M0 archive;
- #28's GC fixture;
- R5b in #32;
- all of #33's fixes after the owner's findings.

Each one was then reviewed by a separate context before it merged.

## Findings that were fixed, by severity

- **High:**
  - a paused run silently resumed under a changed brief (#32);
  - credentials in addresses were stored in plain text, shown on every
    surface, and copied into ledger notes (#33);
  - #27's first rule failed open (#34).
- **Medium:**
  - `INSERT OR REPLACE` got past the append-only ledger triggers;
  - promotion was not atomic;
  - `fukasawa review` got around the resume gate;
  - an ambiguous address aborted a whole scan;
  - unknown top-level keys wiped a hand-written store;
  - a non-UTF-8 endpoint file crashed `node add`.
- **Low:** recorded in each PR.

## Checkouts and branches at the end

| Checkout | Branch | SHA | vs `origin/main` | Dirty |
|---|---|---|---|---|
| primary (`OpenAI_GPT_Builds/…`) | `main` | `82cc3d0` | 0 / 0 | untracked `.claude/` and the owner's handoff file (kept local on purpose) |
| `q2c-substack/…` | `main` | `82cc3d0` | 0 / 0 | untracked `baby-step.yaml`, the owner's own file, untouched |
| worktree `run-plan` | `docs/backlog-run-plan` | PR #31 head | ahead by this PR | clean |
| worktree `issue-27-shadow` | `feat/issue-27-handoff-verdict-shadow` | `126816e` | ahead by PR #34 | clean |

Removed after proving each was clean and contained in `main`:
- 11 worktrees;
- 10 local branches;
- 8 remote branches.

No stash was used or dropped. No forced removal or deletion was done, and no
history was rewritten. Scratch files are in the session scratchpad, outside the
repository.

## Waiting on the owner (shortest next action first)

1. **Merge #31** (these documents), or say what to change.
2. **#34 / issue #27.** Review the rule and the policy it encodes. Decide
   whether to approve the move from shadow to advisory (`capsule/ROLLOUT.md`).
   Answer the nine reconciliation decisions (packet item 8). #27 then still
   needs:
   - a case where the rule really is derived from the model's reasoning
     (checklist item 4 is not demonstrated);
   - measured human time;
   - a gated promotion.

   So #27 stays open.
3. **Gate G.** Decide whether this run's independent technical evidence
   (reviews of the three Jules commits; a re-run of the release checklist)
   satisfies it, or whether Jules's own pass is still required (packet
   item 10).
4. **Product decisions**, packet items 1–7, 9 and 12:
   - "Check again" overwrites the standing look permission;
   - Phase 10b;
   - LAN history and the example hostname;
   - HW-013/014;
   - the pilot asks for approval after publishing;
   - host-name folding;
   - an override for old paused runs.
5. **Private Q2C pipeline** (packet item 9). Its deterministic gate has
   produced nothing since 2026-07-03, and its handoff ignores that gate. Both
   are in a separate, private repository and were not changed.
6. **Your local files.** If you ever typed a user name or password into a
   computer's address, it may still be in plain text in your own
   `~/.fukasawa/nodes.yaml` or ledger. The program now hides such records and
   never uses them. They are local and were never published.
