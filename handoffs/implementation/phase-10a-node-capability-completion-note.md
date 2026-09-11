# Agent Completion Note — Phase 10a: node and capability management

**Phase:** 10a. The follow-on, 10b (matching steps to computers), is not
started.
**Branch:** `claude/handoff-master-verification-37e5d2`, merged to `main`
task by task (PRs #19–#24; Task 9's is the last).
**Implemented by:** `claude-opus-5`. Tasks 1–7 subagent-driven with a review
per task; M8, I5, M5, Task 8 and Task 9 written directly.
**Written:** 2026-09-11.

## Scope completed

The runtime can now learn which computers a person has, from them, asking
permission before anything is contacted — and use them.

| Task | What | Review state |
|---|---|---|
| 1 | contracts: `InferenceNode`, `ScanConsent`, provenance | reviewed clean |
| 2 | the human layer: figures in words, the §3.6 panel | reviewed clean |
| 3 | backend probes, Ollama and llama.cpp | reviewed clean |
| 4 | consent-gated, streaming discovery | reviewed clean |
| 5 | the store, and endpoint merging | reviewed clean |
| 6 | the `node` CLI | reviewed, fixed — **fix round never reviewed** |
| 7 | the GUI service layer | reviewed, fixed — **fix round never reviewed** |
| M8, I5, M5 | typing a computer in; `node add` renaming; unchecked computers on the panel | **not reviewed** |
| 8 | the desktop's Environment tab | **not reviewed** |
| 9 | the wiring gap, doctrine tests, documentation, this note | **not reviewed** |

The operator has scheduled one Opus review over the whole branch, after this
note. The review debt above is real and deliberate; do not describe any of
it as reviewed clean until that review has happened.

## Files changed

42 files, about 10,600 lines, since the phase base `3d81d36`
(`git diff --stat 3d81d36`). No FROZEN path (`.github/workflows/frozen-paths.yml`).

- **New:** `src/schemas/node.py`; `src/nodes/{backends,discovery,store,registry,summary}.py`;
  `src/gui/services/nodes.py`; `src/gui/environment_views.py`;
  `docs/environment-guide.md`; `tests/copy_rules.py`; seven test modules.
- **Changed:** `src/cli.py` (the `node` sub-app, and `_model_endpoints`);
  `src/gui/app.py` (the fourth tab); `src/gui/services/__init__.py`;
  `pyproject.toml` (`pythonpath`); `tests/test_hardening.py`;
  `tests/test_packaging.py`; `tests/test_gui_workflow.py`; README, release
  notes, CLI and desktop guides, backlog; the design spec.

## Tests run and results

```
xvfb-run -a .venv/bin/pytest -q      # CI's own command
1045 passed, 2 skipped

.venv/bin/python -m pytest -q        # no display
984 passed, 63 skipped
```

From 712 passed, 1 skipped at the plan's start. The two skips under CI's
command: one pre-existing, and the operator-hostname check, which skips
because the names it checks cannot be committed (below).

**CI is green on `main`** — and was not, from PR #19 to #22, while every local
run was: see *New risks or defects*.

Beyond the suite: every safety property added since Task 7 was broken on
purpose and confirmed to fail (30 for M8/I5/M5 and Task 8, plus the
doctrine and documentation guards in Task 9), and the Environment tab was
looked at under Xvfb, which found four defects no test had.

## Decisions made

1. **A recorded computer is usable by name, now.** Task 9 found that nothing
   called `merged_endpoints`: the runtime read `model_endpoints.yaml` alone,
   so no recorded computer could run anything. Wired into `_model_endpoints`;
   an unreadable `nodes.yaml` is named in a warning and left out, so graph
   runs that use no recorded computer still run.
2. **Typing an address is not permission to contact it** (operator, M8). The
   check afterwards is the existing one-named-computer permission, not a new
   one, and defaults to no.
3. **A computer typed in and never checked counts on the panel, named as
   such** (operator, M5 option C). Looked at and silent, it does not.
4. **The exported-brief doctrine test records computers first.** Nothing on
   the export path reads them today, so without that the test could not fail.
   Shown to fail by injecting the leak it guards against.
5. **Private addresses are checked across every tracked file**, not only
   `src/` — the repository is public. Documentation examples are allowed by
   name, each with its reason.
6. **Operator hostnames are checked from an environment variable,**
   `FUKASAWA_FORBIDDEN_NAMES`, because listing them in a test would publish
   them.

## Assumptions

- One person's own network (operator, 2026-08-27): if they can reach a
  machine, so can this program. No per-computer grants, no service accounts.
- The desktop names itself `desktop-operator` when it records a permission,
  as the Workflow tab does. There is no sign-in.
- Windows and macOS: built by CI, not hand-verified. The Environment tab has
  been seen on Linux under Xvfb only.

## Known limitations

- **Nothing matches steps to computers** — phase 10b.
- **Sweeping a whole network is not built.** Offered, and answered as such.
- **Ollama and llama.cpp only.** LM Studio, vLLM and other OpenAI-format
  programs are planned, design §10.1.
- **No `node edit` in the terminal**, though design §7 lists it. Editing is in
  the desktop, or in `nodes.yaml`.
- **The store has no lock.** The tab refuses writes during a look; two
  processes writing at once can still lose an edit, and a crash mid-write can
  truncate the file.
- **The ✓ marks did not render** in the headless display's fonts. Expected to
  render on a normal desktop; unconfirmed.

## New risks or defects

- **CI was red on `main` from PR #19 to #22 and nobody saw it.** `pytest` and
  `python -m pytest` resolved imports differently, so the suite never ran in
  CI while every local run passed. Fixed (`pythonpath = ["."]`). Rule since:
  read CI, not the terminal.
- **The operator's LAN addresses are in the public history.** Commit `93e4d64`
  (Phase 5B) put them in the default endpoint config; `9d49d56` removed them.
  The tree is clean — the new doctrine test says so — but the history is not.
  Rewriting published history is the operator's decision.
- **"Oldowan"** is both an example workflow's name and one of the operator's
  hostnames. Found by running the hostname check locally with the operator's
  names. Whether that matters is the operator's call.
- **Open question for the operator:** "Check again" on one recorded computer
  goes through `scan()`, so it replaces the standing look permission with
  "one named computer" (Task 7's I6 rule). Consistent, and possibly not what
  anybody wants; the operator's "directed use needs no second permission"
  ruling suggests a check on a recorded computer should not write it at all.

## Recommended next action

1. **The Opus review over the whole branch**, `3d81d36..main`, as the operator
   scheduled. It settles the unreviewed rows in the table above.
2. The operator's call on "Check again" and the permission.
3. Phase 10b — matching steps to computers — needs its own design: does a step
   no recorded computer can run block promotion, lower `AutomationReadiness`,
   or only warn?

## Exact starting point for next agent

`main`, after Task 9's PR merges. Read, in order:
`handoffs/phase-10a-node-and-capability-handoff.md`, then this note, then
`handoffs/reviews/node-and-capability/` (the ledger, and the Task 8 and Task 9
briefs, each listing what the plan got wrong).

Run `xvfb-run -a .venv/bin/pytest -q` — CI's command — and read CI after
pushing. A worktree needs its own venv, and plain `python script.py` still
imports the main checkout's `src`; use `PYTHONPATH=$PWD`.
