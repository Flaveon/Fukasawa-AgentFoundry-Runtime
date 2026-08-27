# Pilot — ConcordiaPax Substack article production

This is the worked example: one real workflow carried the whole way from
"here is what actually happens" to a brief the runtime can execute.

It is a **real** workflow with **real** problems, not a demonstration built to
succeed. The observed capture reports **24 findings, 14 of them blocking**. That
is the point. A pilot that validated cleanly on the first pass would teach
nothing about what this product is for.

## The files, in the order they were produced

| File | What it is |
|---|---|
| `observed-workflow.yaml` | The process as actually observed, gaps included. **Start here.** |
| `validation-report.json` | Every finding, machine-readable. 24 findings. |
| `validation-report.md` | The same report for a person to read. |
| `repaired-workflow.yaml` | The same workflow after the blocking findings were fixed. 6 findings, 0 blocking. |
| `accountable-workflow.yaml` | Promoted to `ACCOUNTABLE`. Owners, gates and completion contract explicit. |
| `cooperation-assessment.yaml` | One assessment per step: who should do it, under what supervision. |
| `cooperative-workflow.yaml` | The approved assignments — executor, human owner, escalation, bounded tools. |
| `workflow-design-brief.yaml` | The export. A `WorkflowBrief` the existing runtime executes. |

`docs/pilot-walkthrough.md` runs the whole sequence as commands you can type.

## The seven real problems, and where each one is

Master handoff §10 requires this pilot to contain seven specific troubles. Each
is seeded in `observed-workflow.yaml` and each is caught by a rule — the mapping
matters, because it is the evidence that the rules detect things that actually
go wrong rather than things that are easy to detect.

| # | The problem | Where it lives | Caught by |
|---|---|---|---|
| 1 | **An idea expands beyond article scope** | `observed_exceptions`: "An idea turns out to be three articles"; `scope-check` produces nothing verifiable | HW-010, HW-011 |
| 2 | **Research becomes a hidden dependency** | `deep-research` takes an input with no stated source, and its exception has no owner | HW-009, HW-012 |
| 3 | **Publication ownership is implicit** | `publish-post` has **no actor at all** and no decision authority | HW-003, HW-004 |
| 4 | **"Ready to publish" lacks criteria** | `draft-article` and the `publication-approval` gate describe done by feel | HW-014 |
| 5 | **Artwork and distribution are separate dropped handoffs** | `request-artwork` outputs nothing verifiable; `publish-post` routes to `promote-post`, **a step that does not exist** | HW-005, HW-010 |
| 6 | **Scope control needs a human gate** | the `publication-approval` gate can reject but nothing says what happens then | HW-015 |
| 7 | **AI can prepare but not authorize** | `deep-research` is the only non-human actor, and it hands to a human before anything is published | *(not a defect — it is the property cooperation assessment must preserve, see below)* |

Two more the capture surfaced without being asked to:

- `archive-notes` is **unreachable** — nothing routes to it (HW-006).
- The workflow's claimed outcome is not supported by any step that produces
  evidence for it (HW-002).

## What the findings look like

```
24 findings — 14 blocking, 10 advisory
```

| Rule | Policy | n | Where |
|---|---|---|---|
| HW-002 unsupported outcome | blocking | 1 | (workflow) |
| HW-003 missing step owner | blocking | 1 | `publish-post` |
| HW-004 missing decision authority | blocking | 1 | `publish-post` |
| HW-005 dangling next step | blocking | 1 | `publish-post` |
| HW-006 unreachable step | blocking | 1 | `archive-notes` |
| HW-008 implicit handoff | blocking | 1 | `scope-check` |
| HW-009 missing input source | blocking | 1 | `deep-research` |
| HW-010 unverifiable output | blocking | 4 | `scope-check`, `request-artwork` |
| HW-011 unhandled failure mode | blocking | 1 | (workflow) |
| HW-012 unowned exception | blocking | 1 | `deep-research` |
| HW-015 gate with no rejection path | blocking | 1 | `publication-approval` |
| HW-013 memory dependency | advisory | 6 | (workflow), `scope-check`, `request-artwork` |
| HW-014 ambiguous criteria | advisory | 4 | (workflow), `draft-article`, `scope-check`, `publication-approval` |

**Nothing here prevents saving the workflow.** Blocking means blocking
*promotion*; the messy capture is stored, reloadable and resumable exactly as
written. Refusing to record an unfinished process would defeat the first stage
of the lifecycle.

## What the repair changed

`repaired-workflow.yaml` is the same workflow after a person fixed the fourteen
blocking findings — naming `publish-post`'s actor and decision authority,
routing it to `archive-notes` instead of the non-existent `promote-post`, giving
the gate a rejection path, and making the outputs verifiable.

```
6 findings — 0 blocking. Promotion ready.
```

All six survivors are **HW-013**, and every one of them is the same kind of
thing: knowledge the capture honestly admitted lives in someone's head.

Four come from the `unwritten_rules` the observer wrote down:

- "Never publish two long articles in the same week."
- "If the operator is unsure about a claim, cut it rather than hedge it."
- "Artwork is optional in practice, even though the workflow implies it is required."
- "The operator always does the final read on a real screen, never on a phone."

Two more were caught in step descriptions, where the same admission was made in
passing rather than declared — `scope-check` says the criteria are "in the
operator's head", and `request-artwork` says "nobody wrote" the brief down.
Those two are the secondary net working: the honest capture path is the
`unwritten_rules` list, and the prose scan finds what the observer mentioned
without thinking to list it.

These are **not defects to fix**. They are real knowledge that lives in one
person's head, and writing them down is the honest thing the tool asked for.
HW-013 is non-blocking precisely so that recording them is rewarded with
visibility rather than punished with a blocked promotion. An operator either
writes each one into the step it governs, or accepts it as a residual risk with
a reason — both are recorded decisions.

## What cooperation assessment decided

Eight steps, assessed deterministically from their declared characteristics —
no model involved, so the same workflow always produces the same answer:

| Step | Executor | Safety floor |
|---|---|---|
| `capture-idea` | HUMAN_LED_AI_ASSISTED | — |
| `scope-check` | HUMAN_ONLY | — |
| `deep-research` | HUMAN_LED_AI_ASSISTED | — |
| `draft-article` | HUMAN_ONLY | — |
| `request-artwork` | AGENT_EXECUTED_HUMAN_SUPERVISED | — |
| `review-and-approve` | HUMAN_ONLY | **IRREVERSIBLE** |
| `publish-post` | AGENT_PREPARED_HUMAN_APPROVED | **IRREVERSIBLE** |
| `archive-notes` | DETERMINISTIC_AUTOMATION | — |

This is problem 7 from the table above, resolved rather than reported: **an
agent may prepare the publication, and only a person may authorize it.**
`publish-post` is irreversible, so a safety floor applies and the step cannot be
overridden toward greater autonomy — a human who wanted to hand publication to a
bounded autonomous agent would be refused, with the reason stated.

The tools report this as:

```
5 step(s) stay with a person: capture-idea, scope-check, deep-research,
draft-article, review-and-approve
```

Five is the count of steps a **person performs**. A sixth, `publish-post`, is
performed by an agent but cannot take effect until a person approves it, so
six of the eight require human involvement and only two — `request-artwork`
under supervision and `archive-notes` outright — run without it.

That count is stated on every result that carries it, **including when it is
zero**. Reading "3 agent packages generated" and nothing else teaches you
nothing about the five steps still on your desk.

Three agent packages are required: `request-artwork-agent`,
`publish-post-agent`, `archive-notes-agent`.

## Running it yourself

```bash
fukasawa workflow validate examples/workflows/substack-publication/observed-workflow.yaml
```

The full sequence, with commentary, is `docs/pilot-walkthrough.md`.
