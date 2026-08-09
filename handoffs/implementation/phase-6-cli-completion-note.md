# Agent Completion Note — Phase 6: CLI

**Phase:** 6 of 9 — targets Gate F (first half).
**Branch:** `claude/phase-6-cli`, based on
`feature/human-cooperative-workflow-runtime` @ `551ddd2`.
**Implemented by:** `claude-opus-5` in the Codex implementation role.

## Scope completed

- **`src/cli.py`** — additive `workflow` sub-app with all eight §17 commands:
  `init`, `validate`, `findings`, `promote`, `assess-cooperation`,
  `build-cooperative`, `export-agent-brief`, `status`. `--json` on every one.
  Stable exit codes. **No existing command edited.**
- **`src/runtime/ledger.py`** — two additive append-only tables closing the
  save/reload gap (see the ownership note below).
- **`tests/test_workflow_cli.py`** — 72 tests.
- **`docs/cli-guide.md`** — the operator reference.
- **`docs/migration-notes.md`** — the new tables recorded, as the phase-4 note
  asked.

## Files changed

Created: `tests/test_workflow_cli.py`, `docs/cli-guide.md`, this note.
Modified: `src/cli.py` (additive only), `src/runtime/ledger.py`,
`docs/migration-notes.md`.

**No FROZEN file was touched.** Verified against directive §3 by path filter.

## Tests run and results

```
.venv/bin/python -m pytest -q
490 passed, 4 skipped      # 418 before + 72 new; 0 regressions
```

Baseline reproduced before any change: 418 passed, 4 skipped.

Five mutation checks. Two of them **exposed weak tests before they exposed
anything about the code**, which is the argument for doing this at all:

| Mutation | Caught by | Note |
|---|---|---|
| Exit codes collapsed to 0/1 | `TestExitCodes` (6 tests) | First attempt caught only 1 test — the assertions imported `EXIT_BLOCKED`/`EXIT_REFUSED` from the module under test, so renumbering them kept the tests green. Rewritten to pin literal integers, since the numbers *are* the contract. |
| YAML error allowed to escape | `TestNoTracebacks` | First attempt caught **nothing**. CliRunner reports `exit_code == 1` for an unhandled exception as well as a deliberate `typer.Exit(1)`, so asserting the code alone cannot tell a clean refusal from a crash. Added `assert_clean_exit`, which also checks `result.exception`. |
| `NotFoundError` leak restored | 21 tests | |
| Recorded maturity ignored | 18 tests | |
| Override carry-forward removed | 2 tests | |

## The ownership decision this phase required

`release-plan.md` item 8 makes "save/reload/resume at every stage (ledger
tables)" a required release item, and item 6 requires `assess-cooperation` and
`build-cooperative`. But no ledger table existed for cooperation assessments or
cooperative workflows, and `src/runtime/ledger.py` belongs to phase 3 under
directive §3.

Phases 4 and 5 each recorded this gap in their limitations and each declined to
close it. That was individually correct and collectively how a release ships
without save/reload. **Phase 6 is the first phase that cannot defer it** — a
command whose output vanishes when the process exits is not a command.

Raised with the operator, who authorized reassigning the file for these two
tables. `ledger.py` is *owned*, not FROZEN, so this is an ownership decision the
operator can grant rather than a frozen-file breach. R5 still binds (additive
DDL, append-only, no destructive changes); R1/ADR-002 does not apply, since
ledger tables are neither signed nor hash-pinned.

Both tables use a **surrogate `record_id`** rather than a natural key.
`apply_override` returns a copy carrying the same `assessment_id`, so an
override is a later row on top of the original; approving a cooperative workflow
likewise lands beside the unapproved build. Keying naturally would have forced a
choice between refusing the override and erasing the recommendation it replaced,
and the value of an override is that you can still see what it overruled.

## Two bugs found by driving the real lifecycle

Neither was visible from unit tests; both surfaced on the first end-to-end run.

**1. Promotion repeated `OBSERVED → MAPPED` forever.** `promote()` stores an
advanced draft in the ledger but never rewrites the YAML, so a CLI reading
maturity from the file could never reach `ACCOUNTABLE`. Fixed by taking
**content from the file and progress from the ledger** — edits are never
ignored, recorded progress is never repeated, and the lift is announced.

**2. `ledger.load_workflow_draft(id, version)` leaked
`sqlite_utils.db.NotFoundError`** instead of the `KeyError` its own docstring
promises. The unversioned branch honoured the contract; the version-pinned one
did not, and it reached the CLI as a traceback — the exact thing directive §6.11
forbids. Fixed in `ledger.py`, which this phase now owns.

## Decisions made

1. **Exit codes 0 / 1 / 2 / 3.** The 1-versus-2/3 split is the point: a `1`
   means the operator made a mistake; a `2` or `3` means the runtime understood
   and declined. Collapsing them would make the CLI unscriptable in exactly the
   situations that matter. `2` is retryable after fixing the workflow; `3` is not.
2. **`--json` per command, not on the sub-app callback.** `... validate x.yaml
   --json` reads naturally; `workflow --json validate x.yaml` does not. Costs
   eight parameter declarations and a `_set_json` call each; worth it.
3. **`init` writes a `HumanWorkflowDraft` skeleton**, not a project scaffold.
   The skeleton is deliberately incomplete and its comments name the rule ids,
   so the template teaches the rules rather than merely satisfying them.
4. **`validate` gates; `findings` does not.** Same rules, two commands, because
   a script needs to read findings without their existence being a failure.
5. **Re-assessment carries recorded overrides forward.** Reads take the newest
   row per step, so a fresh un-overridden assessment would have become newest
   and the human's decision would have stopped governing while still visible in
   the history. A stored override that would now cross a safety floor exits `3`
   and names the step rather than being dropped.
6. **`steps_kept_human` is always reported**, including when it is zero, per the
   phase-5 handoff.
7. **The boundary test asserts ADR-007 §5, not the directive's literal wording.**
   See below.

## A directive requirement that needed interpretation

Directive §5 asks for a boundary test that "`src/cli.py` never imports from
`src/gui/`". Read literally that is unpassable, and always was: `fukasawa gui`
exists to launch the desktop app, so it necessarily imports it — and that
command predates this phase and is out of scope to edit.

ADR-007 §5's actual requirement is that **the desktop stays optional forever**,
the runtime fully operable from the CLI with no display. The existing launcher's
function-local import with an `ImportError` fallback is the mechanism
*implementing* that, not a violation of it.

`TestBoundary` therefore asserts the real property — importing `src.cli` in a
subprocess never imports `src.gui`, the single reference is function-local, and
no `workflow` command touches the GUI — plus that no classification logic was
copied into the CLI. Flagged rather than silently reinterpreted.

## Assumptions

- `--by` and `--approve-by` are self-attested; this runtime has no
  authentication. The same ceiling documented on `RiskAcceptance`.
- `assess-cooperation` reads `systems` from the stored draft when one exists, so
  `required_tools` is matched rather than inferred. With no stored draft it
  reports none — inheriting phase 4's decision 7.

## Known limitations

- **The two conventions do not extend backwards.** The ten older sub-apps
  return `1` for every failure and have no `--json`. Unifying them would mean
  editing existing commands, which the phase boundary forbids. Worth doing;
  not done.
- **No `accept-risk` command.** Non-blocking findings can be accepted through
  `src/governance/workflow_promotion.accept_risk`, but §17 does not list a CLI
  surface for it and I did not invent one. An operator cannot currently accept
  an advisory finding from the CLI.
- **`workflow promote` cannot pass `--owners`.** `promote()` accepts it;
  ownership falls back to the draft's actors. Adding a repeatable flag is easy
  and was out of the named command set.
- **`approved_at` is still never set**, carried over from phase 5. The
  timestamp belongs to the act of approving, and `--approve-by` on
  `build-cooperative` is arguably that act — worth revisiting.
- **`export-agent-brief --out` writes before package generation may refuse**, so
  a `3` from a failed build can leave a valid brief file on disk. The brief is
  correct; only the packages failed. Documented rather than reordered, because
  the brief is the primary artifact.
- **No `fukasawa workflow run`.** Exported briefs run through the existing
  `fukasawa run`, deliberately: phase 6 adds a front end to the proven runtime
  rather than a second way to execute.

## New risks or defects

- Nothing new for the register.
- **For phase 7:** the desktop must call these same governance functions, not
  re-derive anything. Directive §6.3 forbids classification logic under
  `src/gui/`, and `TestBoundary` in this phase's suite is the pattern to extend.
  Note also that `src/gui/services.py` will need the same
  content-from-file/progress-from-ledger rule the CLI now implements, or the
  GUI will reproduce bug 1.
- **For phase 8:** the pilot artifacts in
  `examples/workflows/substack-publication/` were generated with the operator's
  `request-artwork` override applied. A fresh `assess-cooperation` produces
  **three** agents rather than two, because the table recommends a supervised
  agent there. Both are correct; the walkthrough should say which it is showing.

## Recommended next action

Phase 7 (desktop): `src/gui/workflow_views.py` for §16 items 1–15, service
functions in `src/gui/services.py`, worker threads so the UI thread never
blocks, and no logic in views. New GUI tests go in `tests/test_gui_workflow.py`
— `tests/test_gui.py` is owned by nobody and must not be edited.

## Exact starting point for next agent

Branch `claude/phase-6-cli` @ head (merge to
`feature/human-cooperative-workflow-runtime` first).
Read: `docs/cli-guide.md` → this note → `adr-proposals/adr-007` → directive §16.
Import surface, all already used by the CLI and safe to call from services:
`validate_workflow`; `promote`, `assess`, `accept_risk`; `assess_workflow`,
`apply_override`, `steps_not_ready`; `build_cooperative_workflow`,
`export_workflow`, `steps_kept_human`; and on the ledger
`save_cooperation_assessments`, `load_cooperation_assessments`,
`cooperation_assessment_history`, `save_cooperative_workflow`,
`load_cooperative_workflow`.
Current suite: **490 passed, 4 skipped**. Do not touch any file listed FROZEN
in directive §3.
