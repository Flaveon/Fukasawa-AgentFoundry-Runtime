# Agent Completion Note — Phase 7b: closing §16

**Phase:** 7b of 9 — completes Gate F, which phase 7 knowingly left partial.
**Branch:** `claude/handoff-master-verification-37e5d2`, based on
`claude/phase-7-desktop` @ `6b33657`.
**Implemented by:** `claude-opus-5` in the Codex implementation role.

## Scope completed

Three things the operator asked for, in the order phase 7's note recommended:

1. **A review of phases 1–7 against the master handoff** —
   `handoffs/reviews/phases-1-7-master-handoff-review.md`. §5, §7, §8, §15 and
   §19 read directly against what was built.
2. **§16 finished** — items 3 and 14 from nothing, UI for 6 and 9 over the
   existing services, and 4 and 8 from text lines to grouped tables.
3. **A verdict on the Jules `state_machine.py` refactor** —
   `handoffs/reviews/jules-state-machine-refactor-verdict.md`.

Plus a branch inventory (`handoffs/reviews/branch-inventory.md`), asked for
mid-session.

## §16 compliance — now complete

| # | Required capability | Before | Now |
|---|---|---|---|
| 1 | Workflow project list | met | met |
| 2 | Create/import observed workflow | met | met |
| 3 | **Guided step editor** | not built | **met** |
| 4 | Findings grouped by severity and location | partial | **met** |
| 5 | Finding detail and remediation | met | met |
| 6 | **Accept non-blocking risk with rationale** | service only | **met** |
| 7 | Promote to Accountable Workflow | met | met |
| 8 | **Cooperation assessment table** | partial | **met** |
| 9 | **Executor override with required rationale** | service only | **met** |
| 10 | Cooperative workflow preview | met | met |
| 11 | Export to Workflow Design Brief / Agent Foundry | met | met |
| 12 | Save, reload, and resume | met | met |
| 13 | Visible maturity state | met | met, now in a persistent bar |
| 14 | **Visible validation/rule version** | not built | **met** |
| 15 | No UI-thread blocking during long operations | met | met |

**15 of 15.** Gate F's three criteria — CLI lifecycle, CustomTkinter lifecycle,
same authoritative services — are all met, the third still asserted by
`TestParity`.

## Files changed

**Created**
`src/gui/services/step_editor.py` — guidance and per-field read/write.
`src/gui/step_editor_view.py` — the guided form (§16.3).
`src/gui/tables.py` — the grouped table both §16.4 and §16.8 needed.
`src/gui/dialogs.py` — the shared reason dialog (§16.6, §16.9).
`tests/test_packaging.py` — §15.7, and the defect below.
`handoffs/reviews/phases-1-7-master-handoff-review.md`
`handoffs/reviews/jules-state-machine-refactor-verdict.md`
`handoffs/reviews/branch-inventory.md`

**Modified**
`src/gui/services/workflow.py` — severity and location on `FindingView`;
severity-then-location ordering; `rule_set_version`/`schema_version` on results;
recorded `maturity` on `LifecycleResult`; `EXECUTOR_CLASSES`.
`src/gui/services/__init__.py` — re-exports, import surface unchanged in shape.
`src/gui/workflow_views.py` — swappable detail pane, version bar, the two
dialogs, table rendering.
`src/runtime/state_machine.py` — **FROZEN, see below**.
`pyproject.toml` — package discovery.
`tests/test_gui_workflow.py`, `tests/test_state_machine.py` — new coverage.
`docs/desktop-guide.md` — the new capabilities.

## A FROZEN file was edited, deliberately and on delegation

`src/runtime/state_machine.py` is FROZEN under directive §3, and §7 makes
touching it a stop-and-escalate condition. The operator delegated this decision
explicitly ("your call on Jules's state_machine.py refactor — re-verify"), which
*is* the escalation resolving. The change is five lines of control flow and no
behaviour; the reasoning and the verification are in the verdict document.

Recording it here rather than only there, because the next reader of the freeze
list needs to find both edits, not one.

## Tests run and results

```
xvfb-run -a .venv/bin/python -m pytest -q     # as CI runs it
622 passed

.venv/bin/python -m pytest -q                 # no display
582 passed, 40 skipped
```

Baseline was 559 / 544+15. **63 new tests, zero regressions, zero tests
weakened.**

One existing test changed rather than being added to:
`TestView::test_findings_are_rendered_with_remediation` asserted against the
text log that §16.4 replaced. Its assertion moved to the table and got *wider* —
it now checks every rule id and every remediation rather than one of each.

**Stress check:** 12 consecutive clean runs of the GUI files under xvfb. Phase 7
fixed an intermittent segfault there and this branch adds three view modules, so
"it passed once" was not enough.

### Mutation checks

Every safety property added here was verified by breaking it and watching the
test fail, then restoring it:

| Property | Mutation | Result |
|---|---|---|
| An invalid transition raises `NonConformanceError` | helper returns instead of raising | `TypeError` at the `raise`, immediately — and `TestRefusalIsLocal` fails |
| Every source package reaches the wheel | revert `pyproject.toml` to the hand-written list | both packaging guards fail, naming `src.gui.services` |
| A view cannot import the runtime | (existing) three new view modules are now covered automatically | guard discovers files by glob |

The packaging guard needed **two corrections found this way**. It passed against
the broken config twice before it was right: once because pip served a cached
wheel, and once because a gitignored `*.egg-info/SOURCES.txt` from an earlier
in-place build was feeding setuptools the package the config omitted. A guard
nobody has watched fail is not a guard.

## The defect that ships today

`src/gui/services/` was **absent from every wheel built from this repository**
since phase 7 split it into a package. `pip install .` produced a working CLI
and a GUI that cannot import its own service layer.

Invisible to 559 passing tests, which run from the source tree, and to CI, which
builds through a PyInstaller spec rather than setuptools. §15.7 asked for
exactly this check and it had never been written.

Fixed, and guarded twice.

## Decisions made

1. **Guidance is read from the rule registry, not typed into the view.** A
   field's advice is `RULES[...].remediation`. Change a rule's remediation and
   the editor's advice changes with it. The field→rule map is presentation, and
   a test asserts every citation resolves.
2. **`step_id` is not editable from the form.** Other steps, exception paths and
   gates reference it by name; renaming it from a form would break them
   silently. Change it in the YAML, where the consequences are visible.
3. **Lists and objects cross the boundary as text**, one entry per line, `|`
   between columns. No dynamic widget arrays, every field round-trips through a
   string, and a partially-filled line is accepted rather than refused — the
   operator recorded something true, and the validator will name what is still
   missing.
4. **Saving rewrites YAML and loses comments.** `ruamel` would round-trip them
   and a new dependency is forbidden. Rather than discarding an operator's
   annotations silently, `write_step` backs the file up first and says so in its
   summary.
5. **Confirm stays disabled until the reason has content.** The service refuses
   an empty rationale regardless — the button state is a courtesy, and
   `test_confirming_while_incomplete_does_nothing` proves the guarantee is not
   the button.
6. **The override picker offers all seven executor classes**, ordered by
   autonomy rank, least first. §6 says the UI *may* emphasise a subset; it does
   not say the view may filter the schema, and a picker without
   `NOT_READY_FOR_AUTOMATION` would hide the honest answer.
7. **The import-law guard discovers its subjects.** It listed two view files by
   hand; this branch adds three more. A hardcoded list is a guard with a hole
   in it.
8. **Maturity in the version bar comes from stored artifacts, not the file**, so
   a maturity typed into YAML by hand cannot make the status bar lie.

## Two customtkinter facts that cost real time

Recording them because neither is in the documentation and both are the kind of
thing only running the widget finds — the same lesson phase 7 recorded about
`after()`.

* **`CTkScrollableFrame.winfo_children()` returns the internal canvas and
  scrollbar** alongside your widgets. The idiomatic
  `for child in self.winfo_children(): child.destroy()` destroys the canvas
  first, which takes your labels' Tk objects with it, and then raises from
  inside customtkinter when it reaches them. `Table` tracks what it created.
* **`fg_color` rejects `"transparent"` inside a light/dark tuple.** It must be
  the bare string.

## Assumptions

- Desktop actions are still attributed to `desktop-operator` unless the operator
  types a name into a reason dialog, which both now ask for. Self-attested
  either way — this runtime has no authentication.

## Known limitations

- **The step editor cannot add or delete steps**, only edit existing ones. §16.3
  asks for a step *editor*; adding a step is a structural change that reorders
  `next_steps` references, and doing it from a form without showing what else
  moves would be the same mistake as editing `step_id`. The YAML is the place.
- **Comments do not survive a save.** Documented in the guide and in the
  summary, and backed up. It stays a limitation until a round-tripping loader is
  worth a dependency.
- **`--paths-file` still has no desktop equivalent**, so the Workflow tab's
  export does not generate agent packages. Unchanged from phase 7, not a §16
  item.
- **The version bar shows the rule set version from the constant**, not from a
  stored report. If a workflow's findings were produced under an older rule set,
  the bar shows today's. `PromotionLineage` records the version a promotion was
  made under; surfacing *that* is a phase 8 improvement.
- **Old-version load behaviour is still untested** (§15.4). Phase 9, before
  there is a second schema version.

## New risks or defects

- **Three of the four unsanctioned Jules commits remain unreviewed.**
  `src/runtime/ledger.py` (241 lines, `301ca83`) is the largest and phase 3 owns
  it. The `state_machine.py` review found a real latent hazard behind a
  behaviour-preserving change; there is no reason to assume the others are
  cleaner. **Before Gate G.**
- **The FROZEN list is still unenforced prose.** Branch protection or a CI check
  on those paths is the fix. Phase 9 packaging item.
- **Gate C's false-positive review is still not written down.** HW-013 and
  HW-014 are the heuristics carrying the risk. Phase 8.

## Recommended next action

**Phase 8**, as originally planned, now that Gate F is met:
`docs/pilot-walkthrough.md`, `docs/lifecycle-overview.md`, the pilot README
(§10's one missing artifact), the Gate C false-positive review, and Jules
verification.

The walkthrough should show both surfaces reaching the same result — `TestParity`
already asserts it, and a reader seeing it once is worth more than the assertion.

Before or alongside it, the two items above that outlive this phase: review the
remaining Jules commits, and make the freeze mechanical.

## Exact starting point for next agent

Branch `claude/handoff-master-verification-37e5d2` @ head. Merge it into
`claude/phase-7-desktop`, then that into
`feature/human-cooperative-workflow-runtime` — phase 7 is no longer knowingly
partial, so the hold its note placed on that merge is lifted.

Read `handoffs/handoff-master.md` first; it is the authority and every derived
document is a lossy summary. Then this note's two review documents, then
`docs/desktop-guide.md`.

Run the suite **both ways** — `pytest -q` and `xvfb-run -a pytest -q` — because
the second runs 40 tests the first skips.
Current suite: **622 passed** (xvfb) / **582 passed, 40 skipped** (no display).

`src/runtime/state_machine.py` was edited this phase on explicit operator
delegation. Every other FROZEN file in directive §3 is untouched and stays that
way.
