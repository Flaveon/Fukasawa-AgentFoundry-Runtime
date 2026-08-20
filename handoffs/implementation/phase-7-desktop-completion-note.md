# Agent Completion Note — Phase 7: Desktop

**Phase:** 7 of 9 — targets Gate F.
**Branch:** `claude/phase-7-desktop`, based on
`feature/human-cooperative-workflow-runtime` @ `7d9a9c4`.
**Implemented by:** `claude-opus-5` in the Codex implementation role.

## Scope completed

> **Phase 7 is partial.** It delivers 8 of §16's 15 items with 5 partial and 2
> not started — see "§16 compliance" below. Gate F is not met. The phase was
> built against a reconstruction of §16 because the master handoff was untracked
> and therefore invisible from a worktree; it is now committed.

- **`src/gui/services/`** — twelve service functions, split into a package
  (`brief.py` unchanged, `workflow.py` new) per ADR-007's consequence note.
  Import surface unchanged. These cover the §16 capabilities that are met, and
  the services behind items 6 and 9 exist but have no UI.
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

- Desktop actions are attributed to `desktop-operator`. Self-attested, like every
  actor name here.

> **Superseded, 2026-08-20.** This section previously assumed §16's fifteen items
> were unknowable and recorded a reconstruction built from `file-change-map` and
> ADR-007. The master handoff was then located — untracked in the main checkout,
> now committed as `handoffs/handoff-master.md` — and §16 read directly. The
> reconstruction was wrong in ways the section below records. It is replaced
> rather than deleted because *how confident it read while being wrong* is the
> lesson.

## §16 compliance — measured against the real specification

**Phase 7 does not complete §16.** Scored against `handoffs/handoff-master.md`
§16 after the document was recovered:

| # | Required capability | Status |
|---|---|---|
| 1 | Workflow project list | met |
| 2 | Create/import observed workflow | met |
| 3 | **Guided step editor** | **not built** |
| 4 | Findings view grouped by severity and workflow location | partial — flat log, sorted not grouped |
| 5 | Finding detail and remediation | met |
| 6 | Accept non-blocking risk with rationale | partial — service only, no UI |
| 7 | Promote to Accountable Workflow | met |
| 8 | Cooperation assessment table | partial — text lines, not a table |
| 9 | Executor override with required rationale | partial — service only, no UI |
| 10 | Cooperative workflow preview | met |
| 11 | Export to Workflow Design Brief / Agent Foundry | met |
| 12 | Save, reload, and resume | met |
| 13 | Visible maturity state | met |
| 14 | **Visible validation/rule version** | **not built** |
| 15 | No UI-thread blocking during long operations | met |

**8 met, 5 partial, 2 never started.**

Two corrections worth carrying forward:

* The reconstruction guessed items 13 and 14 were "no second validator" and
  "CLI/desktop parity". Both are wrong — they are the **constraint sentence
  following the list** ("The desktop app is a client of the runtime services. It
  must not implement a second validator."), not numbered capabilities. The real
  13 and 14 are visible maturity state and visible rule version.
* Items 6 and 9 were recorded below as *deliberate* omissions, on the reasoning
  that a half-built override without a mandatory reason field is worse than
  none. That reasoning still holds; the premise that they were optional does
  not. They are required capabilities, and the services behind both already
  exist and are tested — the remaining work is UI only.

Gate F ("CustomTkinter lifecycle works") is therefore **not met by this phase**.
Its third criterion, "same authoritative services used", is met and asserted by
`TestParity`.

## Known limitations

*Items 3, 4, 6, 8, 9 and 14 are §16 requirements, not discretionary scope — see
the table above. They are listed here with the reasoning that produced them.*

- **No override UI** (§16.9). `override_executor` exists as a service and is
  tested, but the tab offers no widget — an override needs a step picker, a class
  picker, and a mandatory reason field, and a half-built version that let someone
  skip the reason would be worse than none. The CLI has it.
- **No accept-risk UI** (§16.6), for the same reason: `accept_finding` is a
  tested service with no widget. Findings render with their remediation;
  accepting one is currently a CLI action.
- **No guided step editor** (§16.3). Not started, and not previously identified
  as required. The largest single gap: it needs per-field editing of
  `WorkflowStep` with the rule guidance that makes it *guided* rather than a form.
- **No visible rule-set version** (§16.14). `ValidationResult` does not carry
  `rule_set_version` and nothing renders it. The CLI shows it ("rule set v1").
  Small: one field through the service and one label.
- **The results pane is a text log**, not a table (§16.4, §16.8). Findings are
  sorted blocking-first then by rule id, not grouped by severity and location;
  assessments render as lines rather than a table.
- **`--paths-file` has no desktop equivalent**, so the Workflow tab's export
  does not generate agent packages. The existing Build Workflow tab does that
  from an exported brief. Not a §16 item.
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

- **Phases 1–6 were built against derived documents too, and have not been
  re-checked.** The master handoff was untracked for all of them. Phase 7's
  reconstruction of §16 scored 8 of 15; phase 6's of §17 fared better only
  because `file-change-map.md` happened to list the commands verbatim. §5
  (domain objects), §7 (the 16 validator rules), §8 (promotion state machine),
  §15 (test strategy) and §19 (gates A–E) governed the earlier phases and none
  has been read against what was built. A drift in §7 or §8 would reach further
  back than the desktop.

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

**Not phase 8.** Two things come first, in this order:

1. **A review of phases 1–7 against `handoffs/handoff-master.md`**, now that it
   is readable. Operator-directed, pending. §16 was wrong by a third; §5, §7,
   §8, §15 and §19 are unverified.
2. **Finish §16** — items 3 and 14 from nothing, UI for 6 and 9 over existing
   services, and 4 and 8 from text to grouped/tabular. Gate F depends on it.

Phase 8 (hardening + pilot README/walkthrough) follows: `docs/pilot-walkthrough.md`,
`docs/lifecycle-overview.md`, the pilot README, Jules verification, and closing
the Gate C false-positive review.

## Exact starting point for next agent

Branch `claude/phase-7-desktop` @ head. **Do not merge to
`feature/human-cooperative-workflow-runtime` yet** — the review above comes
first, and phase 7 is knowingly partial against §16.

Read **`handoffs/handoff-master.md` §16 first** — it is the authority, it is now
tracked, and every derived document (`file-change-map.md`, ADR-007, the
directive) is a lossy summary of it. Then `docs/desktop-guide.md` → this note.

Run the suite **both ways** — `pytest -q` and `xvfb-run -a pytest -q` — because
the second runs 15 tests the first skips, and one of this phase's two defects
only ever appeared under xvfb.
Current suite: **559 passed** (xvfb) / **544 passed, 15 skipped** (no display).
Do not touch any file listed FROZEN in directive §3.
