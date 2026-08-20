# Agent Completion Note — Phase 7: Desktop

**Phase:** 7 of 9 — targets Gate F.
**Branch:** `claude/phase-7-desktop`, based on
`feature/human-cooperative-workflow-runtime` @ `7d9a9c4`.
**Implemented by:** `claude-opus-5` in the Codex implementation role.

## Scope completed

- **`src/gui/services/`** — the twelve §16 service functions, split into a
  package (`brief.py` unchanged, `workflow.py` new) per ADR-007's consequence
  note. Import surface unchanged.
- **`src/gui/workflow_views.py`** — the Workflow tab: stage column, detail
  pane, worker threads.
- **`src/gui/app.py`** — mounts the new tab. The two existing tabs are
  untouched.
- **`src/schemas/templates.py`** — the draft skeleton, shared by CLI and desktop.
- **`tests/test_gui_workflow.py`** — 53 tests across four layers.
- **`docs/desktop-guide.md`** — the operator reference.

## Files changed

Created: `src/gui/services/__init__.py`, `src/gui/services/workflow.py`,
`src/gui/workflow_views.py`, `src/schemas/templates.py`,
`tests/test_gui_workflow.py`, `docs/desktop-guide.md`, this note.
Renamed: `src/gui/services.py` → `src/gui/services/brief.py` (content
unchanged but for the module docstring).
Modified: `src/gui/app.py`, `src/cli.py` (one import), `tests/test_gui.py`
(one patch target).

**No FROZEN file was touched.** Verified against directive §3 by path filter.

## Tests run and results

```
xvfb-run -a .venv/bin/python -m pytest -q     # as CI runs it
559 passed

.venv/bin/python -m pytest -q                 # no display
544 passed, 15 skipped
```

Baseline was 506 tests (502 passed + 4 skipped). 53 new, zero regressions.

Two mutation checks:

| Mutation | Caught by |
|---|---|
| A view imports `src.governance` directly (the R3 failure) | `TestImportLaw` (2 tests) |
| Results marshalled with `after()` from the worker thread | `TestView` (2 worker tests) |

Plus a **stress check**, because the defect below was intermittent: 14
consecutive clean runs of the GUI files and 4 clean full runs, against roughly
50% crashing before the fix.

## Two defects found by building it

Neither was visible from reading; both took running the thing.

**1. `after()` from a worker thread does nothing.** ADR-007 §3 says results
"marshal back via `widget.after()`", and the obvious reading — call `after()`
at the end of the worker — is wrong. Tkinter is not thread-safe, and here the
call failed *silently*: no exception, no callback, the result simply lost. The
worker now puts results on a `queue.Queue` and a main-thread poller drains it,
so every Tk call happens on the thread that owns the widgets. The ADR's intent
is satisfied; its literal instruction was not implementable as written.

**2. The suite segfaulted intermittently under xvfb.** Roughly half the runs of
the GUI files alone. The faulthandler stack put it inside Tk's event dispatch
(`tkinter/__init__.py:_substitute`) beneath a test that spun `window.update()`
in a tight loop while a worker ran.

Diagnosis: real code runs `mainloop()`; spinning `update()` is a test-only
pathology, and it processed queued events against action buttons that
`_render_actions` had already destroyed and rebuilt. Fixed on both sides —
tests drain the queue directly (`drain()` is public for exactly this), and
`select_stage` no longer rebuilds the action row when the stage has not
changed.

Worth recording that **two plausible hypotheses were wrong** before this one
was right: that `FukasawaApp.destroy()` skipped the tab's `destroy()` override
(it does not — checked), and that multiple Tk roots were to blame (a
module-scoped shared window did not stop the crash). The fixture is still
module-scoped, because one root per process is how Tk is meant to be used, but
it was not the cause.

## Decisions made

1. **Stage column, not a wizard.** The lifecycle is sequential but re-entrant —
   an operator usually wants to jump to one stage of an existing workflow, not
   walk from the start. The column doubles as the answer to "where am I?", which
   is the same job `workflow status` does.
2. **Services became a package now rather than later.** ADR-007 sanctions the
   split past ~500 lines; doing it upfront avoided a large mechanical move
   mid-phase. `__init__.py` re-exports everything, so the import law and every
   existing import are unaffected.
3. **The R3 guard is static.** `TestImportLaw` parses the source with `ast`
   rather than importing it, so it runs with or without a display. A guard on
   the phase's highest risk that only runs under xvfb is a guard that a
   developer never sees fail.
4. **The draft skeleton moved to `src/schemas/templates.py`.** Both surfaces
   create drafts, and its comments carry rule ids — two copies would teach two
   different things about the rules within a release or two.
5. **Handlers split into `run_*` (synchronous) and `on_*` (threaded).** The
   synchronous half is public, which is what lets the whole tab be tested
   without a display and without pretending the thread is absent.
6. **`steps_kept_human` is rendered on every result that carries it**, zero
   included — carried forward from phases 5 and 6.

## Two edits outside this phase's ownership

Both deliberate, both minimal, both flagged rather than buried.

* **`src/cli.py`** — one import line, replacing its private `_DRAFT_SKELETON`
  with the shared constant. Phase 6 owns the file; phase 6 is merged and closed,
  and the alternative was shipping two copies of a teaching template.
* **`tests/test_gui.py`** — one patch target, `src.gui.services.generate_packages`
  → `src.gui.services.brief.generate_packages`. That file is owned by *nobody*,
  which forbids adding tests to it; leaving it broken is forbidden outright by
  §6.1. Re-exporting the symbol would not have helped — the patch would bind the
  package namespace while `build_workflow` resolves the name in its own module.

## Assumptions

- **§16's fifteen items are a reconstruction.** They are written down nowhere in
  this repository, and no master handoff exists on disk. Built from
  `file-change-map`'s twelve-function list plus ADR-007's threading,
  no-second-validator, and parity requirements — the same method used for §17 in
  phase 6, and it should be checked against the real spec if it ever surfaces.
- Desktop actions are attributed to `desktop-operator`. Self-attested, like every
  actor name here.

## Known limitations

- **No override UI.** `override_executor` exists as a service and is tested, but
  the tab offers no widget for it — an override needs a step picker, a class
  picker, and a mandatory reason field, and a half-built version that let
  someone skip the reason would be worse than none. The CLI has it.
- **No accept-risk UI**, for the same reason: `accept_finding` is a tested
  service with no widget. Findings render with their remediation; accepting one
  is currently a CLI action.
- **`--paths-file` has no desktop equivalent**, so the Workflow tab's export
  does not generate agent packages. The existing Build Workflow tab does that
  from an exported brief.
- **The results pane is a text log**, not a table. Adequate and honest; a real
  findings table with per-row actions is the natural next increment.
- **The stage column shows six stages**, matching `workflow status`. The maturity
  ladder has eight values; `DEPLOYED` and `VALIDATED` have no desktop surface,
  consistent with the release enforcing gates only through `RUNTIME_READY`.

## New risks or defects

- **A FROZEN file was modified, and nobody recorded it.** `src/runtime/state_machine.py`
  was refactored by `google-labs-jules[bot]` on 2026-08-05 (commit `3d3bea4`,
  128 lines changed), merged to `main` via PR, and inherited by this branch.
  Directive §3 lists that file as FROZEN and §7 makes touching it a
  stop-and-escalate condition. No handoff, note, or register entry mentions it.

  Nothing observably broke — 559 tests pass, including the golden
  `graph_fingerprint` tripwire — but "nothing broke" is the wrong measure for a
  freeze. The freeze existed so that nobody would have to re-derive whether the
  proven runtime's behavior had changed; that guarantee has been spent and does
  not come back. **A human should decide** whether to accept the refactor
  explicitly, revert it, or re-verify the runtime against it.

  Same agent also rewrote `src/runtime/ledger.py` (241 lines, `301ca83` —
  phase 3's file), `src/foundry/validator.py` (`693328b`), and
  `src/governance/maturity.py` (`0f2d6b4`).

- **The ownership rules are unenforced.** Directive §3 and `file-change-map.md`
  are instructions, and the one non-Claude agent working this repo does not
  follow them. Branch protection on the FROZEN paths would bind where prose does
  not — cheap, and a natural phase 9 packaging item.

- **Jules commits are a code/doc drift source.** It changes code without
  changing the contracts that describe the code, which is the exact drift
  `docs/source-to-contract-map.md` exists to detect. When code and a doc
  disagree in this repo, check `git log --author=jules -- <file>` before
  concluding the doc is stale.
- **For phase 8:** the pilot walkthrough should show both surfaces reaching the
  same result — `TestParity` already asserts it, and a reader seeing it once is
  worth more than the assertion. Phase 8 also runs Jules verification: it will
  meet a `tests/test_gui.py` whose patch target this phase changed, and a
  `src/gui/services.py` that is now a package. Both are anticipated, neither is
  a regression.
- **For phase 9:** `customtkinter` stays an optional dependency and the desktop
  must remain optional forever (ADR-007 §5). `TestImportLaw` and the plain-pytest
  run (544 passed with no display) are the evidence that still holds.
- **Carried from phase 6, still true:** the ten older CLI sub-apps have no
  `--json` and return `1` for every failure. The desktop does not touch them.

## Recommended next action

Phase 8 (hardening + pilot README/walkthrough): `docs/pilot-walkthrough.md`,
`docs/lifecycle-overview.md`, the pilot README, Jules verification, and closing
the Gate C false-positive review. No new capability.

## Exact starting point for next agent

Branch `claude/phase-7-desktop` @ head (merge to
`feature/human-cooperative-workflow-runtime` first).
Read: `docs/desktop-guide.md` → `docs/cli-guide.md` → this note → directive §8.
Run the suite **both ways** — `pytest -q` and `xvfb-run -a pytest -q` — because
the second runs 15 tests the first skips, and one of this phase's two defects
only ever appeared under xvfb.
Current suite: **559 passed** (xvfb) / **544 passed, 15 skipped** (no display).
Do not touch any file listed FROZEN in directive §3.
