# Phase 10a — Node and Capability Management

**Written 2026-08-27, at the operator's request, on stepping away from the
project for an indefinite period.** Everything needed to resume is in this
file or in the files it names. Nothing needed to resume is in anybody's
recollection.

---

## Read this first, in this order

1. This file, all of it.
2. `handoffs/reviews/node-and-capability/ledger.md` — the running record of
   every task, review verdict, fix round, and operator decision, in
   chronological order. **When this file and the ledger disagree, the ledger
   is older and this file is newer.** Both are snapshots; `git log` is truth.
3. `docs/superpowers/specs/2026-08-23-node-and-capability-design.md` — the
   design, and §3.1.1/§3.1.2 in particular. Those are copy rules the operator
   set personally and they are enforced by tests.
4. `docs/superpowers/plans/2026-08-23-node-and-capability.md` — the 9-task
   plan. **Treat it as dated 2026-08-23 and partly stale.** See "The plan
   lies" below; this is not a criticism of the plan, it is a property of any
   plan written before the code it describes.

---

## Where things stand

Branch: `claude/handoff-master-verification-37e5d2`
Worktree: `.claude/worktrees/handoff-master-verification-37e5d2`
HEAD at time of writing: `4999df2`
Suite: **907 passed, 41 skipped**, about 53 seconds. No FROZEN path touched
anywhere in this branch.

| Task | State |
|---|---|
| 1 contracts | complete, reviewed clean |
| 2 summary / human layer | complete, reviewed clean |
| 3 backend probes | complete, reviewed clean |
| 4 streaming discovery | complete, reviewed clean |
| 5 storage + registry | complete, reviewed clean |
| 6 CLI `node` sub-app | complete, reviewed, fixed — **fix commits never reviewed** |
| 7 GUI service layer | complete, reviewed, fixed — **fix commits never reviewed** |
| 8 Environment tab | not started |
| 9 doctrine tests, docs, phase note | not started |

Then a final whole-branch review, which the plan already calls for.

### The review debt, stated plainly

Tasks 1–5 each went implement → review → one fix round → review clean. Tasks 6
and 7 did **not** complete that cycle. Both were reviewed, both were fixed, and
**neither fix round was ever reviewed.** That is the honest state. It was a
deliberate choice — the operator judged the cost per round was climbing while
severity held, and chose to batch rather than keep spending. Do not paper over
it, and do not pretend those tasks are "reviewed clean".

The plan's final whole-branch review is the natural place to settle it. When
you get there, review `3d81d36..HEAD` with the knowledge that Tasks 6 and 7's
fix commits have had no independent pass.

---

## Pick up here

Three things are ready to go, in the order I would do them.

### 1. M8 — the Task 6 question the operator has now answered

`fukasawa node scan` with no flags shows a four-rung menu. Option 4 is
*"Don't look — I'll type it in"*. Choosing it currently prints
`Refused: no permission to look` and exits **3**. That describes the person
wrongly: they picked a route this program offered, and it did what they asked.

The code is at `src/cli.py`, in `node_scan`'s `if chosen is ScanScope.NONE:`
branch. There is a comment at that site explaining the open question. **Replace
that comment when you implement this.**

**Operator's rulings, all four:**

- **Exit 0** on option 4. Choosing "don't look" and having nothing looked at is
  success. `--scope none` **keeps exit 3** — that is a genuine refusal of an
  explicit request, and a test holds it. Split the two paths; do not change the
  flag path.
- **Prompt for a name and address and record it.** The operator asked for
  "capture boxes"; in a terminal that is an inline prompt. The boxes themselves
  are Task 8's Environment tab — decide the flow once so both front ends match,
  per §3.7.
- **Ask permission before listening.** Typing an address is **not** permission
  to contact it. Reaching a named address is a scan at `NAMED_HOST` scope and
  needs its own yes. So a typed-in computer is recorded **unchecked** unless the
  person separately permits a probe. This follows the four-rung doctrine rather
  than carving an exception into it.
- **Branch the copy on whether the store is empty.** See the next section for
  why.

**Two assumptions that were checked and found false. Do not reintroduce them.**

1. *"This only happens when no nodes are recorded."* **False.** `node_scan`
   loads the store but reads only the **consent** from it. The menu appears
   whenever `node scan` runs without `--scope` and without `--yes`, however many
   computers are already recorded. Somebody with three machines looking for a
   fourth sees this same menu. "Enter desired node name and location" is wrong
   copy for them.
2. *"Obviously we can't do evals."* **False**, and putting it on screen would
   have been a false statement about this tool. `run_eval_case` runs against a
   `RunLedger` and recorded run artifacts; `src/governance/` contains **zero**
   references to nodes, inference, Ollama, or llama.cpp. Evals evaluate what
   already happened. The true and narrower consequence is the one the summary
   panel already states: steps whose actor is an agent cannot run. **Say nothing
   about evals.**

### 2. I5 in `src/cli.py`'s `node_add` — left open, patch already written

Task 7's fix round closed I5 in the GUI service but **not** in the CLI, because
that round's scope allowed `src/cli.py` only for a different finding, so a fix
there could not have carried a test. The exact patch is in
`handoffs/reviews/node-and-capability/task-7-fix-report.md`.

The defect: `upsert` matches on URL and preserves the existing `DECLARED` label
and kind — right for a rescan, wrong for a hand-add. Adding a computer at an
address already stored returns success and reports a name it did not store. The
measured behaviour was worse than the review described: with seeded provenance
the old code applied the typed label and kind to the **existing** row, so
`node add "Kitchen Box"` at Home PC's address said *"Added Kitchen Box."* while
silently **renaming Home PC**.

`upsert` already returns the merged node. Compare it and say what actually
happened.

This is the natural companion to M8 — same file, and both are §3.7 parity.

### 3. Task 8, the Environment tab

**Before dispatching anybody, check the plan's Task 8 section against the
current source.** This is not optional diligence, it is the highest-value hour
available. See below.

Fold in two things while you are there:

- The M8 flow above, as actual fields in the tab.
- Move the copy-rule helpers to `tests/copy_rules.py`. They currently live in
  `tests/test_node_cli.py` and are imported by `tests/test_gui_nodes.py`, so
  that module is loaded under two names. **Task 8 would be the third importer.**

Task 8 must also honour a constraint written into
`src/gui/services/nodes.py`'s module docstring: **do not offer editing while a
scan is running.** `scan()` upserts per event on the worker thread and
`update_field` does a whole-file read-modify-write on the UI thread. No lock, no
mtime check, and `src/nodes/store.py`'s write is a plain `write_text`, so a
crash mid-write truncates the store.

---

## The plan lies, and here is how

The plan was written 2026-08-23. Code landed after it. Two of the three
corrections that had to be made to Task 7's brief existed **only** because later
tasks moved the ground under the plan. Expect the same for Tasks 8 and 9.

Checking the plan against current source before dispatching Task 7 cost one
tool call and caught three real defects, one of which would have shipped a test
making **real outbound network calls**. Post-hoc review found comparable
defects at roughly fifty times the cost. **Front-load this.**

Known stale patterns already found in the plan text, all inside the Task 6
range (lines 1886–2307), all already handled:

- `row.source` — `SummaryRow.source` was deleted by Task 2's review.
- `console.print(jsonlib.dumps(...))` — `_emit_json` at `src/cli.py` is correct;
  Rich wraps to terminal width and corrupts JSON.

Tasks 7, 8 and 9 are clean of **those two**. They will have others.

---

## What this codebase has actually been caught doing

Six defects reached review in this phase. Five share one shape. Put this in
every brief you write.

**Fixtures that hide the bug by avoiding it.** Four variations so far, every one
of them a test that passed honestly and proved nothing:

1. A discovery fake blind to POST, guarding traffic that is mostly POST.
   Ollama's `/api/show` is a **POST**, not a GET.
2. A `CliRunner` at its default 80 columns, testing a bug about wrapping on
   narrow terminals.
3. The *fix* for that: a discovery stand-in yielding events with **no node
   attached**, so `found` stayed empty and the guarded path never ran.
4. Assertions positioned where they cannot fail — `events[-1].finished` stays
   true when *every* event is forced `finished=True`.

**When writing a test, name the line it would catch if that line were deleted.
Where cheap, delete the line and confirm red.**

**Mutation checks that mutate the wrong line.** This has now bitten three
agents in `src/gui/services/nodes.py` and `src/cli.py` specifically, because
these files repeat literals:

- `if chosen is ScanScope.LOCAL_NETWORK:` is not unique in `cli.py`.
- `"            finished=True,\n"` appears in two refusal blocks at the same
  indent.
- `target.set_consent(ScanConsent.granted(scope, actor))` now appears in both
  `save_consent` and `scan`.

**Assert the anchor is unique, read the line back to confirm the mutation
landed where you meant, and verify the revert by checksum.** A red result from
a mutation that landed elsewhere proves nothing.

**Silent data outcomes.** Two so far: a node-id collision that silently deleted
a computer (fixed, ids now host-derived with numeric suffixes), and `add_node`
silently renaming an existing row while reporting success (fixed in the service,
**open in the CLI** — see item 2 above).

---

## Environment traps, both real, both cost time

**The worktree venv resolves `src` to the wrong tree.** The worktree has its own
`.venv` and `import src` **still** reaches the main checkout for any plain
`python script.py`, because the editable install points there. `python -c`
masks it (cwd joins `sys.path`) and pytest masks it (rootdir insertion). Any
script not run under pytest needs:

```
PYTHONPATH=$PWD .venv/bin/python script.py
```

Running the suite is safe: `.venv/bin/python -m pytest -q`. About 40 tests are
display-gated and skip in a plain run; that is expected, not a problem.

**`.superpowers/` is gitignored repo-wide** (`.gitignore:14`). Every plan
artifact — the ledger, all briefs, all reports, all review packages — lived on
one worktree's disk and nowhere else, until this handoff. That is why the ledger,
briefs and reports are now copied into
`handoffs/reviews/node-and-capability/`. The `review-*.diff` packages were
**deliberately not copied**: they are exactly `git diff A..B` and are
regenerable from history at any time.

---

## Conventions that are not negotiable

- **No `Co-Authored-By` trailers.** This branch has zero and the operator's
  conventions forbid them.
- Commit style: a specific subject line, then a body explaining **why**, in
  sentences. Read `git log` on this branch for the register.
- SPDX header on every new source file:
  `# SPDX-License-Identifier: AGPL-3.0-or-later` then
  `# Copyright (C) 2026 ConcordiaPax LLC`.
- Every function gets a docstring; non-developers read this code.
- No network calls at runtime or in tests. No hardcoded agent or model names.
- GUI services are Tk-free by rule (ADR-007 §1): dataclasses in, dataclasses
  out, no widget imports, no printing.
- **Sub-agents run on Opus.** The operator asked about pinning an older Opus for
  throughput; the model override accepts only `sonnet` / `opus` / `haiku` /
  `fable`, with no version pinning, and the operator chose to stay on Opus.
  **Do not downgrade reviewers** — every review in this phase found a genuine
  Critical, and one found a defect hidden inside the fix for the previous
  defect.
- **When in doubt, stop and write a comment explaining what the next step
  requires rather than guessing.** Guessing creates non-conformance. This has
  been used correctly twice in this phase and both times it was the right call.

---

## Deferred, not lost

**Workflow placeholders.** The operator wants a workflow to be creatable with no
computer recorded — placeholders and subscripts so the workflow asks for the
node at activation time. This touches `WorkflowStep.actor` and step assignment:
the **workflow schema**, not the node feature. It was deliberately kept out of
M8, because folding a feature into a one-line exit-code fix is how scope becomes
unreviewable. **It needs its own spec section and its own task.** Do not
implement it as a side effect of anything above.

**M5 — the recommended route lands on a dead end.** Both refusals point at
"type a computer in by hand", but `summarise` gates on `reachable`
(`src/nodes/summary.py:113`) and a hand-added node defaults to `reachable=False`.
So the route both refusals recommend lands on a panel saying "No step can be
assigned to an agent." This is Task 3's contract, confirmed and deliberately not
patched by Task 7's fix round. Decide it before Task 8 renders that panel — it
is the first thing a new user will see after following the advice.

**Minor deferred items from Tasks 1, 3 and 5** are listed at the top of
`handoffs/reviews/node-and-capability/ledger.md`. The final whole-branch review
was always meant to confirm them.

---

## What is NOT pushed

At the time of writing, `origin/claude/handoff-master-verification-37e5d2`
points at **`209df87`** — Task 6's unreviewed commit. **Seventeen commits are
local to this machine only**, including all of Task 6's fix round, the spec
correction, all of Task 7, and Task 7's fix round.

The operator was told and the push was left to them. **If you are resuming in a
cloud session or on another machine, check this first** — a stale remote will
show you Task 6 unreviewed and invite you to redo three days of work:

```
git log --oneline origin/claude/handoff-master-verification-37e5d2..HEAD
```

If that prints nothing, the push happened and this section is history.
