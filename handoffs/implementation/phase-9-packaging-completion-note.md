# Agent Completion Note — Phase 9: packaging and release documentation

**Phase:** 9 of 9 — the last. Targets Gate G.
**Branch:** `claude/handoff-master-verification-37e5d2`.
**Implemented by:** `claude-opus-5` in the Codex implementation role.

## Scope completed

| Deliverable | Status |
|---|---|
| `packaging/fukasawa.spec` | **no change needed** — `collect_submodules("src")` already covers the phase 7b modules |
| `packaging/README.md` | updated — real size, and the bundled-examples behaviour |
| `README.md` | rewritten, top to bottom — see below |
| `docs/release-notes.md` | **done** |
| `docs/packaging-guide.md` | **done** |
| Binary verified or blocker documented (§2.3) | **verified on Linux**, not deferred |
| FROZEN list made mechanical | **done** — `.github/workflows/frozen-paths.yml` |
| `examples/`-in-wheel decision | **decided and documented** — it does not ship; reasoning in the packaging guide |

**§18 is complete at 13 of 13.** The two contributor guides live inside the
references they extend rather than as separate files, and the README says so.

## Tests run and results

```
xvfb-run -a .venv/bin/python -m pytest -q     # as CI runs it
707 passed, 1 skipped

.venv/bin/python -m pytest -q                 # no display
667 passed, 41 skipped
```

From 694 / 654+41 at phase 8. **13 new tests, zero regressions, zero weakened.**

## The binary is verified, not deferred

§2.3 permits either. Built on Linux (kernel 5.15, Python 3.12.13, PyInstaller
6.22.2) and driven from an empty directory containing no source:

| Check | Result |
|---|---|
| `fukasawa --help` | works |
| All 9 `workflow` subcommands | present |
| Bundled pilot validated by its documented path | 24 findings, exit 2 |
| `validate brief` on the bundled brief | works |
| Full lifecycle → written brief | works |
| `workflow status` after it | 5 of 6 stages |
| GUI mode under Xvfb | real window, `Fukasawa AgentFoundry Runtime` 820x640, clean startup, no output |

The GUI check matters more than it looks: `FukasawaApp()` constructs every tab
before `mainloop()`, so a window that is still alive after 14 seconds is proof
that the phase 7b step editor, tables and dialogs all built inside the frozen
bundle. `xwininfo` confirms the window exists rather than inferring it from a
live process.

Windows and macOS are built and smoke-tested by CI on their own runners —
PyInstaller does not cross-compile — but are **not** hand-verified. The
packaging guide says exactly that rather than implying three verified platforms.

## Two defects found by doing it

### 1. The binary carried the pilot and nobody could open it

All 39 files under `examples/` are bundled by the spec. PyInstaller unpacks data
into `sys._MEIPASS` and nothing resolved paths against it, so every documented
example command failed from the binary with "No such file" while the file sat
inside the executable the operator had just run.

`src/resources.py` fixes it. The design decision worth keeping: **the working
directory always wins.** A file the operator edited is the one they mean, so a
bundled copy of the same name never shadows it, and an absolute path is never
redirected into the bundle. Unfrozen, the whole module is the identity function
— a checkout behaves as it always did and the tests need no frozen interpreter.

### 2. The release README claimed infrastructure that does not exist

This one I nearly shipped. Phase 9 owns `README.md`, and I rewrote it from
"Directory Map" downward while **preserving the top four sections verbatim** —
Purpose, Product Frame, Source Inputs, Key Distinction. They read plausibly.

They dated from the 2026-07-19 planning package, had survived nine
implementation phases unread, and described this runtime as the layer that was
still *missing*. Two items they listed as delivered infrastructure do not exist:

- a **workflow node library** — nowhere in the repository;
- the **prompt/module registry** — `registry/prompt-module-registry.yaml`, a
  `schema_version: 0.1` draft that no source file reads.

Caught because the operator said mid-phase: *"a lot has changed since that
readme was generated — don't assume any instructions over 2 weeks old are
current truth."* Checking file dates rather than reading text found nine
planning-package documents untouched since 2026-07-19.

The README now has a **"Documents that are historical, not current"** section
naming all nine and stating plainly that where they disagree with the code, the
code is right. `roadmap.md` is called out separately because it uses a
*different phase numbering* from the one this release followed, which has
confused readers before.

## The FROZEN list now binds

`.github/workflows/frozen-paths.yml` fails a pull request touching any path in
directive §3's FROZEN list. It was prose from the start, and prose did not bind:
four files were edited across four merged PRs by a contributor that never read
it, with no note or escalation.

Verified against history rather than asserted: it flags the real `3d3bea4`
(`state_machine.py`), passes the three commits that touched phase-owned but not
frozen files, catches any path under `src/kernel/`, and does not false-positive
on a name like `state_machine_helpers.py`.

The escape hatch is a tracked `.github/FROZEN_WAIVER.md` naming which files, why,
who authorised it and what was re-verified — reviewable in the diff instead of
argued in a comment thread. **The job does not forbid the change; it forbids the
change happening quietly.**

## Decisions made

1. **The wheel does not ship `examples/`.** Shipping them means restructuring
   the directory under `src/` — changing every documented path in every document
   for the install mode least likely to want it — or `data-files`, which lands
   in `sys.prefix` where nothing finds it again. The wheel's audience has the
   repository. Documented rather than left to be discovered.
2. **The spec was not touched.** `collect_submodules("src")` already discovers
   the phase 7b modules; editing it to name them would have added a list to
   forget to update. Phase 9 is the only phase permitted to edit the spec and
   the right use of that permission was not to.
3. **The two §18 contributor guides stay as sections.** They exist, they are
   where a contributor would look, and splitting them into stub files to satisfy
   a count would make the documentation worse.
4. **A test now guards the documented commands.** I shipped
   `workflow findings <workflow-id>` when it takes a path.
   `TestDocumentedCommandsAreReal` checks all nine in both directions.

## Assumptions

- The binary was verified on this machine's Linux only. CI's three-OS matrix is
  treated as build evidence, not verification.

## Known limitations

- **Windows and macOS binaries are not hand-verified.**
- **A bare wheel install cannot run the documented example commands.**
- **`.github/FROZEN_WAIVER.md` has never been exercised** — the escape hatch is
  written but untested, because nothing has needed a waiver since it landed.
- **Nine planning-package documents remain stale.** They are now *labelled*
  rather than fixed. Rewriting `specs/`, `roadmap.md` and `docs/architecture.md`
  to match the code is real work and none of it is phase 9's; labelling them
  stops them misleading a reader today.

## New risks or defects

Unchanged, and both still need a human rather than an agent:

- **Jules's independent verification pass has not happened.** §11.7 assigns it
  for the *independence*; the agent that wrote phases 7–9 cannot supply that.
- **Three commits on phase-owned files remain unreviewed** —
  `src/runtime/ledger.py` (241 lines, `301ca83`) first. The one that *was*
  reviewed had moved a real safety property while preserving behaviour and
  passing 559 tests.

## Recommended next action

**The nine implementation phases are done.** What is left before tagging:

1. **Jules's independent verification pass** — operator action.
2. **Review the three remaining Jules commits**, `ledger.py` first.
3. Tag the release candidate. CI builds the three binaries and attaches them on
   a `v*` tag.

Optional and worth considering after the tag: rewrite or retire the nine stale
planning documents, and spend §11.4's unspent Grok Build budget on adversarial
validator fixtures.

## Exact starting point for next agent

Branch `claude/handoff-master-verification-37e5d2` @ head, identical to
`claude/phase-7-desktop` and `feature/human-cooperative-workflow-runtime`.

Read `docs/release-notes.md` first — it is the summary of what shipped and what
did not. Then `handoffs/implementation/release-verification-report.md` for what
is verified and by whom.

Run the suite **both ways**: **707 passed, 1 skipped** (xvfb) / **667 passed,
41 skipped** (no display). A worktree needs its own venv.

`src/runtime/state_machine.py` was edited in phase 7b on explicit operator
delegation, and `.github/workflows/frozen-paths.yml` will now stop that
happening without one.
