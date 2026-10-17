# Backlog run plan — 2026-10-17

**Assignment:** the owner's *Fukasawa Claude Backlog Handoff v1.0*, prepared
2026-10-16 against `main` = `95d8867`. It is kept in the owner's local checkout
and **not committed**: it names the owner personally, and this repository is
public. Everything in it that governs this run — the delegated authority, the
execution order, the protected behaviour — is restated below or in the
completion report. This file is the run's
versioned plan and status board; the completion report will be a separate
file beside it.

## Authority recorded for this run

The owner's handoff (§1) delegates, for this run only: ordinary
implementation, bug fixes, independent review, integration of ready
implementation PRs, evidence-backed issue closure, and cleanup of
demonstrably merged task branches/worktrees. This is narrower than, and
supersedes for this run, the older blanket "no autonomous merges" wording in
the repository and in issue #27.

It does **not** authorise: production deployment, bypassing GitHub
protection, self-approval, changing governance policy, inventing product
decisions, approving a process capsule on the owner's behalf, or a FROZEN-path
waiver. An independent AI review is technical review, not human sign-off.

`main` has no branch protection or rulesets (checked 2026-10-17:
`GET /branches/main/protection` → 404, rulesets `[]`). So nothing on GitHub
forces review — the review requirement in this plan is self-imposed and
must be kept anyway.

## Verified starting state (2026-10-17, re-queried)

| Item | State |
|---|---|
| `origin` | `Flaveon/Fukasawa-AgentFoundry-Runtime`, `main` = `95d8867`, matches the handoff snapshot |
| Open PRs | 0 |
| Open issues | 1 — #27 |
| Latest `main` CI | red: `build` runs on 95d8867 failed on `tests/test_gui_workflow.py::TestView::test_the_ui_thread_is_not_blocked_while_working` |
| Primary checkout | was 131 behind `origin/main`, clean apart from untracked `.claude/`, the owner handoff, and `handoffs/handoff-master.md` (byte-identical to the tracked copy on `origin/main`; backed up, removed, then fast-forwarded) |
| Second checkout | `~/agentic-workspace/q2c-substack/Fukasawa-AgentFoundry-Runtime`, `main` = `80c42a8` = its `origin/main` snapshot (stale vs 95d8867), one untracked user file `baby-step.yaml` |
| Pre-existing worktrees | `handoff-master-verification-37e5d2`, `phase-10a-code-review-c80d0f`, `phase-7-desktop`, `review-package-dispatch-7fd69f` — all clean, all branches ancestors of `origin/main` (0 unique commits) |
| Stashes | none |

## Model roles

The handoff names `claude-sonnet-5-5` and `claude-haiku-5-5`. **Neither is
available in this environment**; the subagent tool offers Opus 5.5, Sonnet 5
(`claude-sonnet-5`) and Haiku 4.5. Substitution, stated rather than silent:

| Role | Requested | Used |
|---|---|---|
| Orchestrator, integration, closure decisions | Opus 5.5 | Opus 5.5 (`claude-opus-5-5`) — this session |
| Implementer | Sonnet 5.5 | Sonnet 5 |
| Scout / evidence | Haiku 5.5 | Haiku 4.5 for inventory; Sonnet 5 for the Q2C defect search, which needs more judgment than inventory |
| Independent reviewer | Opus 5.5 | Opus 5.5, separate context per review |

Two small changes were written directly by the orchestrator rather than
delegated (the colour-off `tests/conftest.py`, and the M0 archive, which is a
byte copy plus provenance). Both still receive independent review.

## Tasks

| ID | Task | Depends on | Owner | Branch / worktree | Status | Evidence | Decision needed |
|---|---|---|---|---|---|---|---|
| A | Inventory local + remote truth | — | Opus | — | done | this file, "Verified starting state" | — |
| B1 | Fix GUI worker reading Tk widgets (red `main`) | A | Sonnet 5 → Opus review | `fix/gui-worker-thread-tk` | in progress | — | — |
| C1 | Second review of PR #26's ten fixes (277f758) | A | Opus reviewer | read-only `review-95d8867` | in progress | — | — |
| C2 | Technical review of Gate G commits 301ca83, 693328b, 0f2d6b4 | A | Opus reviewer | read-only `review-95d8867` | in progress | — | Gate G acceptance stays with the owner |
| C3 | Forced-colour CLI test failures | A | Opus | `fix/tests-color-off` | committed, awaiting review | reproduced at 95d8867: **65** failures under `FORCE_COLOR=1` (note recorded 9); after fix 1159 passed / 64 skipped | — |
| C4 | Reconcile `tasks/backlog.md` against code/tests | A | Haiku 4.5 scout → Opus edit | `docs/backlog-run-plan` | done | 32 ticked with named carriers, 21 open with stated status. The scout's table was used as leads only: it cited two paths that do not exist (`config/cpax_profile.yaml`, `handoffs/adr/`) and test names by wildcard, so every ticked carrier was re-checked by hand | — |
| C5 | Independent lifecycle/CLI/desktop/offline/persistence/packaging verification | B1 | Opus reviewer | — | pending | — | Gate G acceptance stays with the owner |
| D0 | #27 M0: archive the May 31 plan verbatim | A | Opus | `docs/issue-27-m0-source-archive` | committed, awaiting review | SHA-256 `82ca7abf…10ad122f`, matches the original commit `c49a5cb` and five other local copies | — |
| D2 | #27: source → contract reconciliation, ADR options | D0 | Opus | — | pending | — | owner decisions on divergences (issue checklist item 2) |
| D3 | #27: find a real recurring Q2C defect, baseline metrics | D0 | Sonnet 5 scout | read-only | in progress | — | — |
| D4–D8 | #27: candidate rule, shadow evaluation, capsule packaging, rollback, measured benefit | D3 | Sonnet 5 / Opus | — | pending | — | human review + promotion approval (issue checklist item 6) |
| E | Explicit packets for Phase 10b, "check again" consent, LAN history, HW-013/014 | A | Opus | — | pending | — | owner |
| F | Integration, cleanup, completion report | all | Opus | — | pending | — | — |

## Validation commands (every writing worktree has its own `.venv`)

```bash
uv venv --python 3.12 .venv && uv pip install -e '.[dev,gui]'
GITHUB_ACTIONS=true xvfb-run -a .venv/bin/pytest -q
.venv/bin/python -m pytest -q
FORCE_COLOR=1 .venv/bin/python -m pytest -q      # after C3
```

## Notes

- CI installs CPython **3.12.15**; this host's uv offers 3.12.13 at most
  (`uv 0.11.29`). Local Tcl/Tk 9.0.3 tolerates a worker thread reading a
  widget, CI's does not — which is why B1's test passes locally and fails in
  CI. B1 is therefore verified by a thread-identity regression test that fails
  on any platform, plus CI on the PR head.
- The privacy tests (`test_no_private_address_is_published`,
  `test_no_forbidden_name_is_published`) run on every new document. The
  forbidden-name list is supplied at test time and never committed. The
  pre-existing example hostname used throughout the examples is the known
  limitation handled in task E; it is not renamed here.
