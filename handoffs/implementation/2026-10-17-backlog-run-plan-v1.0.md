# Backlog run plan — 2026-10-17

> **Closed 2026-10-19.** Final status, dispositions and what waits on the owner:
> `2026-10-19-backlog-run-completion-report-v1.0.md`. The task table below is
> the plan as it stood during the run.

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
| B1 | Fix GUI worker reading Tk widgets (red `main`) | A | Sonnet 5 → Opus review | `fix/gui-worker-thread-tk`, PR #28 | **CI green, two independent reviews, awaiting owner merge** | 0da943e, c26a501 (GC-on-worker test hazard found on PR CI, fixed), 177877b; local repro on CI's CPython 3.12.15 / Tcl 9.0.4 | merge (refused to this session by permission policy) |
| C1 | Second review of PR #26's ten fixes (277f758) | A | Opus reviewer → Sonnet 5 fix → Opus re-review | `fix/pr26-second-review` | fixes committed (afc81b0), re-review APPROVE_WITH_NITS; one Minor regression (ambiguous address aborts whole scan) being fixed | 3 Important + 7 Minor found; 25/27 mutants killed originally | m3 host-name folding (packet §7) |
| C2 | Technical review of Gate G commits 301ca83, 693328b, 0f2d6b4 | A | Opus reviewer → Sonnet 5 fix | `fix/gate-g-review-findings` | review done (all three behaviour-preserving); pre-existing gaps being fixed | 4 Medium, 5 Low pre-existing (incl. INSERT OR REPLACE past append-only triggers; non-atomic promotion) | Gate G acceptance (packet §10) |
| C3 | Forced-colour CLI test failures | A | Opus | `fix/tests-color-off`, PR #29 | reviewed (APPROVE_WITH_NITS, nits fixed in 9f9bb35); CI red only on B1's test until #28 merges | 65 failures at 95d8867 under FORCE_COLOR, 65 under TTY_COMPATIBLE, 15 under COLUMNS=30; all 0 after | merge |
| C4 | Reconcile `tasks/backlog.md` against code/tests | A | Haiku 4.5 scout → Opus edit | `docs/backlog-run-plan` | done | 32 ticked with named carriers, 21 open with stated status. The scout's table was used as leads only: it cited two paths that do not exist (`config/cpax_profile.yaml`, `handoffs/adr/`) and test names by wildcard, so every ticked carrier was re-checked by hand | — |
| C5 | Independent lifecycle/CLI/desktop/offline/persistence/packaging verification | A | Opus reviewer | scratch, removed | done | lifecycle, phase-0 criteria, offline (strace: 0 network syscalls), desktop, wheel, PyInstaller all PASS; F1 High (paused run resumes under a changed brief) folded into C2's branch; F3 → packet §6 | Gate G acceptance |
| D0 | #27 M0: archive the May 31 plan verbatim | A | Opus | `docs/issue-27-m0-source-archive`, PR #30 | done, CI red only on B1's test | SHA-256 `82ca7abf…10ad122f` = original commit `c49a5cb` | merge |
| D2 | #27: source → contract reconciliation, ADR options | D0 | Opus | PR #30 | done | 63 trace rows; 9 owner decisions | packet §8 |
| D3 | #27: find a real recurring Q2C defect, baseline metrics | D0 | Sonnet 5 scout | read-only | done, verified by Opus | 24/35 gated runs: handoff says PASS/ship while the same run's deterministic gate says HOLD | — |
| D4–D8 | #27: candidate rule, shadow evaluation, capsule packaging, rollback, measured benefit | D3 | Sonnet 5 / Opus | `feat/issue-27-handoff-verdict-shadow` | baseline running (44 cases × 1 local-model call) | — | human review + promotion approval |
| E | Explicit packets for Phase 10b, "check again" consent, LAN history, HW-013/014 | A | Opus | `docs/backlog-run-plan` | done | `2026-10-17-owner-decision-packet-v1.0.md` | owner |
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
