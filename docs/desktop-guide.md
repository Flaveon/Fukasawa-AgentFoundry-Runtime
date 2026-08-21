<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Copyright (C) 2026 ConcordiaPax LLC -->

# Desktop Guide

The same workflow lifecycle as the CLI, for people who would rather see it than
type it. Nothing here can do anything the CLI cannot, and nothing here decides
anything differently — both surfaces call the same functions.

```bash
fukasawa gui
```

The desktop is optional forever. If `customtkinter` is not installed the
command says so and the rest of the runtime is unaffected.

## The three tabs

| Tab | For |
|---|---|
| **Workflow** | The lifecycle: capture → validate → promote → assess → assign → export |
| **Validate Brief** | Check a finished brief file on its own |
| **Build Workflow** | Generate agent packages from an approved brief |

Workflow comes first because a brief is what the lifecycle *produces*; the other
two tabs act on one you already have.

## The Workflow tab

Three fields across the top — the **workflow id**, the **draft file**, and the
**ledger database** (defaults to `fukasawa.db`) — then two panes.

**Left: the lifecycle.** Six stages, each with a marker showing whether the work
has reached it. A filled marker means that stage exists in the ledger.

```
● 1. Draft          What actually happens, gaps included.
● 2. Accountable    Promoted once the blocking gaps are closed.
● 3. Assessed       Who should perform each step.
· 4. Assigned       Executors chosen, and approved by a person.
· 5. Exported       A brief the runtime can execute.
· 6. Runs           What happened when it ran.
```

Clicking a stage shows its actions on the right. The markers refresh after every
action, so the column is always a current answer to "where am I?" — the same
question `fukasawa workflow status` answers.

**Right: actions and results.** What you can do at the selected stage, and a log
of what came back.

### Stage 1 — Draft

*New draft* writes a skeleton at the draft path. It is deliberately incomplete:
it loads and saves, and validation then names what is missing. Recording an
unfinished process is the first stage, not a failure of it.

*Save to ledger* stores the draft. **Saving never depends on the draft being
complete.** *Reload* reads it back, and *List all* shows every stored workflow.

*Edit steps* opens the **guided step editor**. Pick a step from the dropdown and
every field of it becomes a box, in the order an observer naturally answers
them: what is it, who does it, what does it need, what does it produce, where
does it go, what can go wrong, and what is it like.

What makes it *guided*: beside each box is the remediation sentence of the rule
that fires on that box, and the fields a **blocking** rule governs are tinted.
The advice is read from the rule set itself, so it cannot drift from the
findings you will get. The findings against **this step only** sit above the
form, so you see what you came to fix before you start typing.

Three things worth knowing:

* **`step_id` is not editable here.** Other steps, exception paths and gates
  point at it by name, and renaming it from a form would break those references
  silently. Change it in the YAML, where you can see what else moves.
* **Lists are one entry per line**, and objects use `|` between their columns —
  the column names are printed above the box. A line with only some columns
  filled in is accepted; the validator will tell you what is still missing.
* **Saving rewrites the YAML, and comments are not preserved.** The previous
  file is copied to `<name>.yaml.bak` first. If your draft's comments matter to
  you, edit that file directly instead.

The six *characteristics* at the bottom — judgment load, repeatability,
determinism, risk, reversibility, data sensitivity — are dropdowns rather than
free text because they decide who is allowed to execute the step. Recording that
a step is irreversible and high-risk is what pulls it back from automation at
stage 3.

### Stage 2 — Accountable

*Validate* checks the draft against the 16 rules and shows every finding in a
table **grouped by severity, then by where in the workflow it is**, with the
count of blocking findings on each group's heading. Blocking findings block
promotion and nothing else.

*Accept risk…* records a conscious decision to live with an **advisory**
finding. Click the finding first, then the button. The dialog asks for your name
and a reason and **will not enable Confirm until both are filled in** — an
acceptance without a reason is not a decision. Accepting unlocks nothing:
advisory findings never blocked promotion. What changes is that the reason is on
the record.

A blocking finding cannot be accepted, and the button says so rather than
opening a dialog that would refuse at the end.

*Promote* advances one maturity step — run it twice to reach `ACCOUNTABLE`.
Content comes from your file and progress from the ledger, so editing the file
between promotions is picked up, and a step already taken is not repeated.

### Stage 3 — Assessed

*Assess cooperation* recommends an executor for every step from the published
decision table, and shows them as a table: step, executor, supervision,
readiness, floor, and the reason. No model is involved — the same workflow
always yields the same recommendations, so you can disagree with one before you
run it.

The table is in two groups, and the division is the one that matters: steps with
**no safety floor**, which you may override in either direction, and steps
**with** one, which may only move toward human control.

*Override executor…* replaces one step's recommendation with your judgment.
Click the step first. The dialog lists all seven executor classes ordered by
autonomy, least first, and requires a name and a reason before Confirm enables.
For a floored step it says up front which floor applies and which direction is
refused.

Re-assessing **carries your recorded overrides forward**. A safety floor —
irreversible effect, sensitive data, no named decision authority — can only be
overridden toward human control, never away from it. Attempting the latter is
refused with the reason.

### Stage 4 — Assigned

*Build assignments* reads each assessment's *effective* executor, so an override
you recorded governs and the table's recommendation does not.

*Build + approve* signs them. Export refuses an unapproved workflow, so the
unapproved build exists precisely so you can read the assignments first.

Every assignment names a human owner and an escalation target, including the
fully automated ones. Automation moves the work, never the accountability.

### Stage 5 — Exported

*Export brief* flattens the approved workflow into a brief the runtime executes.
A step needing a human to authorize each execution becomes **two** transitions
with a waiting state between them, so the approval is somewhere the work sits
and something the ledger records.

### Stage 6 — Runs

*Refresh* re-reads the lifecycle. Running an exported brief is
`fukasawa run` — the desktop adds a front end to the proven runtime rather than
a second way to execute.

## What the desktop always tells you

**How many steps stayed with a person**, including when the answer is zero.
Reading "3 packages generated" and nothing else teaches you nothing about the
five steps still on your desk.

**Which maturity the ledger records, and under which versions.** The line under
the detail pane always reads:

```
maturity ACCOUNTABLE   ·   rule set v1   ·   schema v1
```

The maturity comes from the stored artifacts rather than from your file, so a
maturity typed into the YAML by hand cannot make it say something untrue. The
rule set version is what produced the findings you are looking at; two reports
that disagree may be disagreeing because the rules moved, and this is where you
find out.

## Refusals are not errors

When the runtime declines — an unapproved export, an override across a safety
floor, a blocking finding that cannot be accepted — the result reads
`Refused:` followed by the reason. That is the product working. The reasons are
written to be read by the person who hit them, so they are shown in full.

## Where the logic lives

Every action is a function in `src/gui/services/`, which imports no widgets and
can be called with no display. The views in `src/gui/app.py` and
`src/gui/workflow_views.py` may import only those services, the standard
library, and customtkinter — enforced by a test that parses the source, so it
holds whether or not anyone runs the GUI.

That boundary is why the desktop and the CLI cannot drift: a rule lives in one
place, and both surfaces call it. `tests/test_gui_workflow.py` includes parity
tests that run both and compare.

Long actions run on a worker thread; results return through a queue that the UI
thread drains. The window never freezes, and no Tk call is ever made from a
worker — Tkinter is not thread-safe, and a cross-thread `after()` fails silently
rather than loudly.

## Attribution

Actions taken in the desktop are recorded as `desktop-operator`. Like every
actor name in this runtime it is self-attested — there is no authentication.
Adequate for one trusted local operator; **not** multi-party non-repudiation.
