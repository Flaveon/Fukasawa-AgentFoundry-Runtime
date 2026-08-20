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

### Stage 2 — Accountable

*Validate* checks the draft against the 16 rules and lists every finding with
its remediation. Blocking findings block promotion and nothing else.

*Promote* advances one maturity step — run it twice to reach `ACCOUNTABLE`.
Content comes from your file and progress from the ledger, so editing the file
between promotions is picked up, and a step already taken is not repeated.

### Stage 3 — Assessed

*Assess cooperation* recommends an executor for every step from the published
decision table. No model is involved: the same workflow always yields the same
recommendations, so you can disagree with one before you run it.

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
