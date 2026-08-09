<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Copyright (C) 2026 ConcordiaPax LLC -->

# CLI Guide — the workflow lifecycle

How to take a process that currently lives in someone's head and turn it into
something a runtime can execute, without pretending the messy parts are not
there.

Everything here runs locally against a SQLite file. No network calls happen
anywhere in this program.

## The shape of it

```
workflow init          write down what actually happens
      ↓
workflow validate      find the gaps (16 deterministic rules)
      ↓
workflow promote        ×2   OBSERVED → MAPPED → ACCOUNTABLE
      ↓
workflow assess-cooperation   who should do each step
      ↓
workflow build-cooperative    assign it, then approve it
      ↓
workflow export-agent-brief   flatten into a runnable brief
      ↓
fukasawa run                  execute it on the existing runtime
```

`workflow status <id>` answers "where am I?" at any point and never fails.

## Exit codes

Stable. A script may branch on these.

| Code | Meaning | What to do |
|---|---|---|
| `0` | Success. | — |
| `1` | **Your input was wrong.** Missing file, malformed YAML, absent prerequisite, contradictory flags. | Fix the command or the file. |
| `2` | **Understood, and blocked for now.** Unresolved blocking findings; promotion not ready. | Fix the workflow. The same command then succeeds. |
| `3` | **Understood, and refused as doctrine.** An override across a safety floor, an unapproved export, a gateless autonomous agent. | Reconsider the request. Retrying will not help. |

The distinction between 1 and 2/3 is the one that matters. A `1` means you made
a mistake. A `2` or `3` means the runtime understood you perfectly and declined
— which is the product working, not failing.

Every command also takes `--json`, which emits one object on stdout instead of
tables. The JSON is emitted on failure paths too, always with `ok: false` and an
`error` key, so a caller never has to parse prose.

## The commands

### `workflow init <workflow-id>`

Writes a draft skeleton to fill in by hand.

```bash
fukasawa workflow init weekly-report --out weekly-report.yaml
```

The skeleton is deliberately incomplete. It loads, it saves, and `validate` will
tell you exactly what is missing. That order is the point: **record what happens
first, discover the gaps second.** A tool that refused to save an incomplete
process would make honest capture impossible, and honest capture is the whole
first stage.

Its comments name the rule ids, so the template teaches the rules rather than
merely satisfying them.

### `workflow validate <draft.yaml>`

Checks a draft against the 16 rules. No model is involved — the same draft
always produces the same findings, in the same order, with the same text.

```bash
fukasawa workflow validate weekly-report.yaml --save
```

Exits `2` while an unresolved blocking finding remains. **"Blocking" means
blocking promotion to `ACCOUNTABLE`, and nothing else.** `--save` stores the
draft and its report either way; a workflow is allowed to be a mess while you
are still writing down what it is.

### `workflow findings <draft.yaml>`

The same rules, without the gate. Always exits `0` when the draft loads.

```bash
fukasawa workflow findings weekly-report.yaml --rule HW-004
fukasawa workflow findings weekly-report.yaml --blocking-only
```

`validate` is the gate; `findings` is the lens. Separating them means a script
can read findings without having to treat their existence as a failure.

### `workflow promote <draft.yaml> --by <name>`

Advances one step up the maturity ladder. Run it twice to reach `ACCOUNTABLE`:

```bash
fukasawa workflow promote weekly-report.yaml --by drew   # OBSERVED → MAPPED
fukasawa workflow promote weekly-report.yaml --by drew   # MAPPED → ACCOUNTABLE
```

**Content comes from the file; progress comes from the ledger.** Promotion never
rewrites your YAML, so a file that has already been promoted still says
`OBSERVED` on disk. The command lifts it to the recorded maturity and says so.
Edits you make to the file are always picked up — only the maturity is taken
from the ledger.

`--by` is self-attested. This runtime has no authentication; the name is a name
someone typed. Adequate for one trusted local operator, insufficient as
multi-party non-repudiation.

### `workflow assess-cooperation <workflow-id>`

Recommends an executor for every step, from a published decision table. No
model, no randomness: you can predict the output before running it.

```bash
fukasawa workflow assess-cooperation weekly-report
```

To disagree with a recommendation, override it — with your name and a reason:

```bash
fukasawa workflow assess-cooperation weekly-report \
  --override draft-summary=HUMAN_LED_AI_ASSISTED \
  --by drew --why "The summary sets the tone; I write it and let AI suggest edits."
```

Both `--by` and `--why` are required. An override without a reason is
indistinguishable from a mis-click, and this decision governs who may act
unsupervised.

**Overrides are one-directional.** You may always move a step *toward* human
control. You may not move a step that hit a safety floor toward greater
autonomy — that exits `3`. The floor exists because of a fact about the work
(it cannot be undone, it handles sensitive data, nobody owns the decision), and
that fact does not change because someone would prefer it did. If the underlying
fact is wrong, correct the step's characteristics rather than overriding around
it.

Re-running the command recomputes every recommendation from the table, and
**carries your existing overrides forward** — you do not have to re-type them.
Passing `--override` for a step replaces the decision recorded for it. Every
earlier row stays in the ledger, so the history shows what the table
recommended before a person overruled it.

If a step's characteristics change so that a stored override would now cross a
safety floor, the command exits `3` and names the step rather than quietly
dropping the decision.

### `workflow build-cooperative <workflow-id>`

Assigns every step, reading each assessment's *effective* executor — so a
recorded override governs and the table's recommendation does not.

```bash
fukasawa workflow build-cooperative weekly-report --approve-by drew
```

Approval is a separate human act. Building without `--approve-by` is useful:
read the assignments, then approve them. Export refuses an unapproved workflow.

Every assignment names a **human owner** and an **escalation target**, including
the fully automated ones. Automation moves the work, never the accountability.

### `workflow export-agent-brief <workflow-id>`

Flattens the approved workflow into a `WorkflowBrief` the existing runtime
executes unchanged.

```bash
fukasawa workflow export-agent-brief weekly-report \
  --out weekly-report-brief.yaml \
  --packages ./packages --workspace ~/my-project
```

Each step becomes a state; each declared edge becomes a transition owned by that
step's executor, carrying its evidence requirement and task depth.

**A step needing a human to authorize each execution exports as two
transitions**, with a real waiting state between the agent's work and the
person's decision:

```
publish-post → publish-post-pending-approval    (agent,  GUIDED)
publish-post-pending-approval → archive-notes   (human,  CONSCIOUS)
```

That is not decoration. The runtime opens its review gate on CONSCIOUS
transitions, and a brief refuses a CONSCIOUS transition owned by an agent — so
the approval has to be a place the work waits, which also makes it an event the
ledger records.

`--packages` generates one agent package per declared agent. A non-C-Pax
workspace needs `--paths-file` (a YAML mapping of `context`, `tasks_ready`,
`tasks_blocked`, `outputs`, `logs`, `agent_config`, `archive`) or `--workspace`
pointing at a numbered layout. Agents with undefined paths are incomplete, so
the build refuses rather than guessing.

### `workflow status <workflow-id>`

Where a workflow sits, and what is missing. Never refuses — an absent stage is
reported as absent, because "nothing here yet" is the answer to the question
rather than an error.

```bash
fukasawa workflow status weekly-report
```

## What the CLI will always tell you

**How many steps stayed with a person.** `build-cooperative` and
`export-agent-brief` both report it, including when the answer is zero. An
operator who exports a workflow and reads only "2 packages generated" has
learned nothing about the six steps still on their desk, and that silence is the
failure mode this product exists to prevent.

## Worked example

The Substack pilot, end to end, from a clean database:

```bash
fukasawa workflow validate examples/workflows/substack-publication/repaired-workflow.yaml --db pilot.db --save
fukasawa workflow promote examples/workflows/substack-publication/repaired-workflow.yaml --by drew --db pilot.db
fukasawa workflow promote examples/workflows/substack-publication/repaired-workflow.yaml --by drew --db pilot.db
fukasawa workflow assess-cooperation substack-publication --db pilot.db
fukasawa workflow build-cooperative substack-publication --db pilot.db --approve-by drew
fukasawa workflow export-agent-brief substack-publication --db pilot.db --out brief.yaml
fukasawa workflow status substack-publication --db pilot.db
```

The assessment puts `publish-post` on `AGENT_PREPARED_HUMAN_APPROVED` with an
`IRREVERSIBLE` floor: an agent may **prepare** the publication, but a human
authorizes it, because an email to subscribers cannot be unsent. That result
comes from the table, not from anyone placing it by hand.

## Two conventions this sub-app does not share

The ten older sub-apps (`runs`, `package`, `bundle`, `trust`, …) predate this
one and were out of scope to change. They return `1` for every failure and have
no `--json`. Unifying them is worth doing and is not done.

## Where things are stored

| Thing | Where |
|---|---|
| Drafts | `workflow_drafts` — editable, keyed by workflow and version |
| Validation reports | `validation_reports` — append-only |
| Promotions | `workflow_promotions`, `accountable_workflows` — append-only |
| Assessments and overrides | `cooperation_assessments` — append-only |
| Executor assignments | `cooperative_workflows` — append-only |
| Exported briefs | `workflows` |
| Runs and transitions | `runs`, `ledger` — append-only |

Append-only is enforced by SQLite triggers, not by convention: code holding a
direct database handle still cannot update or delete those rows. Pass `--db` to
use a file other than `./fukasawa.db`.
