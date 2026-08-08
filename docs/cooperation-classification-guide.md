<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Copyright (C) 2026 ConcordiaPax LLC -->

# Cooperation Classification Guide

How the runtime decides who should perform each step and how closely they
are watched. **Generated from `src/governance/cooperation.py`**, so the
published table cannot drift from the one that actually runs.

No model is involved. The same step always yields the same recommendation,
the same floor, and the same rationale — which is what lets you predict the
output before running it. A rule nobody can predict is a rule people learn
to ignore.

## The two mechanisms

1. **A base recommendation** from judgment load, determinism and
   repeatability — how much thinking the step needs, how reliably it
   repeats, and how often it recurs.
2. **Safety floors** then cap that recommendation. Risk, reversibility and
   data sensitivity are deliberately *not* consulted in step 1: they are
   floors applied afterwards, so raising one can only ever restrict a
   recommendation and never widen it.

## Executor classes, ordered by delegated judgment

| Rank | Class | Human authorizes each execution? | AI involved? |
|---|---|---|---|
| 0 | `NOT_READY_FOR_AUTOMATION` | no | no |
| 1 | `HUMAN_ONLY` | yes | no |
| 2 | `HUMAN_LED_AI_ASSISTED` | yes | yes |
| 3 | `AGENT_PREPARED_HUMAN_APPROVED` | yes | yes |
| 4 | `DETERMINISTIC_AUTOMATION` | no | no |
| 5 | `AGENT_EXECUTED_HUMAN_SUPERVISED` | no | yes |
| 6 | `BOUNDED_AUTONOMOUS_AGENT` | no | yes |

Two orderings are deliberate and worth understanding. `NOT_READY_FOR_AUTOMATION` ranks lowest because nothing is assigned at all.
And `DETERMINISTIC_AUTOMATION` ranks *below* `AGENT_EXECUTED_HUMAN_SUPERVISED`:
a script that always does the same thing has no latitude to misjudge, so it is
safer than an agent acting under observation. The ranking follows **how much
judgment is delegated**, not how absent humans are.

## Base recommendation table

Every combination of the three factors consulted in step 1. Risk,
reversibility and sensitivity do not appear here by design.

| Judgment load | Repeatability | Determinism | Recommendation |
|---|---|---|---|
| NONE | ONE_OFF | DETERMINISTIC | `AGENT_PREPARED_HUMAN_APPROVED` |
| NONE | ONE_OFF | MOSTLY_DETERMINISTIC | `AGENT_PREPARED_HUMAN_APPROVED` |
| NONE | ONE_OFF | JUDGMENT_BASED | `AGENT_PREPARED_HUMAN_APPROVED` |
| NONE | OCCASIONAL | DETERMINISTIC | `AGENT_EXECUTED_HUMAN_SUPERVISED` |
| NONE | OCCASIONAL | MOSTLY_DETERMINISTIC | `AGENT_EXECUTED_HUMAN_SUPERVISED` |
| NONE | OCCASIONAL | JUDGMENT_BASED | `HUMAN_LED_AI_ASSISTED` |
| NONE | ROUTINE | DETERMINISTIC | `DETERMINISTIC_AUTOMATION` |
| NONE | ROUTINE | MOSTLY_DETERMINISTIC | `BOUNDED_AUTONOMOUS_AGENT` |
| NONE | ROUTINE | JUDGMENT_BASED | `HUMAN_LED_AI_ASSISTED` |
| LOW | ONE_OFF | DETERMINISTIC | `AGENT_PREPARED_HUMAN_APPROVED` |
| LOW | ONE_OFF | MOSTLY_DETERMINISTIC | `AGENT_PREPARED_HUMAN_APPROVED` |
| LOW | ONE_OFF | JUDGMENT_BASED | `AGENT_PREPARED_HUMAN_APPROVED` |
| LOW | OCCASIONAL | DETERMINISTIC | `AGENT_EXECUTED_HUMAN_SUPERVISED` |
| LOW | OCCASIONAL | MOSTLY_DETERMINISTIC | `AGENT_EXECUTED_HUMAN_SUPERVISED` |
| LOW | OCCASIONAL | JUDGMENT_BASED | `HUMAN_LED_AI_ASSISTED` |
| LOW | ROUTINE | DETERMINISTIC | `DETERMINISTIC_AUTOMATION` |
| LOW | ROUTINE | MOSTLY_DETERMINISTIC | `AGENT_EXECUTED_HUMAN_SUPERVISED` |
| LOW | ROUTINE | JUDGMENT_BASED | `HUMAN_LED_AI_ASSISTED` |
| MODERATE | ONE_OFF | DETERMINISTIC | `HUMAN_LED_AI_ASSISTED` |
| MODERATE | ONE_OFF | MOSTLY_DETERMINISTIC | `HUMAN_LED_AI_ASSISTED` |
| MODERATE | ONE_OFF | JUDGMENT_BASED | `HUMAN_LED_AI_ASSISTED` |
| MODERATE | OCCASIONAL | DETERMINISTIC | `HUMAN_LED_AI_ASSISTED` |
| MODERATE | OCCASIONAL | MOSTLY_DETERMINISTIC | `HUMAN_LED_AI_ASSISTED` |
| MODERATE | OCCASIONAL | JUDGMENT_BASED | `HUMAN_LED_AI_ASSISTED` |
| MODERATE | ROUTINE | DETERMINISTIC | `HUMAN_LED_AI_ASSISTED` |
| MODERATE | ROUTINE | MOSTLY_DETERMINISTIC | `HUMAN_LED_AI_ASSISTED` |
| MODERATE | ROUTINE | JUDGMENT_BASED | `HUMAN_LED_AI_ASSISTED` |
| HIGH | ONE_OFF | DETERMINISTIC | `HUMAN_ONLY` |
| HIGH | ONE_OFF | MOSTLY_DETERMINISTIC | `HUMAN_ONLY` |
| HIGH | ONE_OFF | JUDGMENT_BASED | `HUMAN_ONLY` |
| HIGH | OCCASIONAL | DETERMINISTIC | `HUMAN_ONLY` |
| HIGH | OCCASIONAL | MOSTLY_DETERMINISTIC | `HUMAN_ONLY` |
| HIGH | OCCASIONAL | JUDGMENT_BASED | `HUMAN_ONLY` |
| HIGH | ROUTINE | DETERMINISTIC | `HUMAN_ONLY` |
| HIGH | ROUTINE | MOSTLY_DETERMINISTIC | `HUMAN_ONLY` |
| HIGH | ROUTINE | JUDGMENT_BASED | `HUMAN_ONLY` |

> Any characteristic left `UNKNOWN` triggers the
> `UNKNOWN_CHARACTERISTICS` floor before this table is consulted, so an
> uncharacterized step is never treated as safe to automate.

## Safety floors

A floor is a **ceiling on autonomy** imposed by a fact about the work. When
several apply, the most restrictive wins; ties resolve in the order below, so
the outcome is deterministic.

| Floor | Triggered when | Caps autonomy at |
|---|---|---|
| `UNDEFINED_AUTHORITY` | the step names no decision authority | `NOT_READY_FOR_AUTOMATION` |
| `UNKNOWN_CHARACTERISTICS` | any characteristic is `UNKNOWN` | `NOT_READY_FOR_AUTOMATION` |
| `IRREVERSIBLE` | `reversibility` is `IRREVERSIBLE` | `AGENT_PREPARED_HUMAN_APPROVED` |
| `HIGH_RISK` | `risk` is `HIGH` | `AGENT_PREPARED_HUMAN_APPROVED` |
| `SENSITIVE_DATA` | `data_sensitivity` is `SENSITIVE` | `AGENT_PREPARED_HUMAN_APPROVED` |

A floor is recorded on the assessment **even when the base recommendation was
already at least as cautious**, because the floor governs what an override may
later do.

## The one-directional override rule

**A human may always move a step toward human control. A human may never move
a floored step toward greater autonomy.**

This is enforced in code by comparing `autonomy_rank`, not left to convention.
The floor exists because of a fact about the work — it cannot be undone, it
handles sensitive data, nobody owns the decision — and that fact does not
change because someone would prefer it did. If the underlying fact is wrong,
correct the step's characteristics; do not override around it.

On an **unfloored** step any override is permitted with a rationale: there the
table is guidance, not doctrine.

Every override requires an actor and a non-empty rationale. Without a reason
an override is indistinguishable from a mis-click, and this decision governs
who may act unsupervised.

## Supervision mode

Derived from the executor class rather than assessed separately: how closely
work is watched follows from who is doing it and how much latitude they have.

| Executor class | Supervision |
|---|---|
| `NOT_READY_FOR_AUTOMATION` | `APPROVAL_REQUIRED` |
| `HUMAN_ONLY` | `NONE` |
| `HUMAN_LED_AI_ASSISTED` | `EVERY_OUTPUT_REVIEWED` |
| `AGENT_PREPARED_HUMAN_APPROVED` | `APPROVAL_REQUIRED` |
| `DETERMINISTIC_AUTOMATION` | `SPOT_CHECK` |
| `AGENT_EXECUTED_HUMAN_SUPERVISED` | `EVERY_OUTPUT_REVIEWED` |
| `BOUNDED_AUTONOMOUS_AGENT` | `SPOT_CHECK` |

A step guarded by an approval gate has its supervision tightened from
`SPOT_CHECK` to `APPROVAL_REQUIRED`: a gate is evidence a human already
decided this needs their eyes.

## Automation readiness

Separate from the executor class, because a step can be *suitable* for
automation in principle while lacking the repetition or clarity to do it
safely yet — the same evidence-before-capability discipline the agent maturity
model uses.

| Readiness | When |
|---|---|
| `NOT_READY` | the class is `HUMAN_ONLY` or `NOT_READY_FOR_AUTOMATION`, any characteristic is `UNKNOWN`, or the work is `ONE_OFF` |
| `PILOT` | a safety floor applies, or the work is not yet routine and deterministic |
| `READY` | routine, at least mostly deterministic, and unfloored |

## Export mapping

What each class becomes when the approved workflow is flattened onto the
runtime. Published here per ADR-006; the tables that run are in
`src/foundry/workflow_export.py`.

| Executor class | Task depth | Transition owner | Agent declared? | Agent depth level |
|---|---|---|---|---|
| `NOT_READY_FOR_AUTOMATION` | CONSCIOUS | the human owner | **no** | — |
| `HUMAN_ONLY` | CONSCIOUS | the human owner | no | — |
| `HUMAN_LED_AI_ASSISTED` | GUIDED | the human owner | no | — |
| `AGENT_PREPARED_HUMAN_APPROVED` | GUIDED, then CONSCIOUS | the agent, then the human | yes | 2 |
| `DETERMINISTIC_AUTOMATION` | ROUTINE | the script | yes | 0 |
| `AGENT_EXECUTED_HUMAN_SUPERVISED` | GUIDED | the agent | yes | 2 |
| `BOUNDED_AUTONOMOUS_AGENT` | GUIDED, then CONSCIOUS | the agent, then the human | yes | 3 |

Four things in that table are decisions rather than transcription:

**The export reads the *effective* executor.** A recorded override is the
human's decision about their own workflow, and it is what governs. The
recommendation is never consulted at export.

**`HUMAN_LED_AI_ASSISTED` declares no agent.** A person does the work and AI
helps, so the human owns the transition — and an agent that owns no transition
is one the package generator refuses to build. The assistance is recorded in
`allowed_tools`, which is what it is: a tool, not a governed executor.

**Gated classes export as two transitions, not one.** The runtime opens its
review gate on CONSCIOUS-depth transitions, and a `WorkflowBrief` refuses a
CONSCIOUS transition owned by an agent — so a gated agent step cannot be a
single transition. It becomes the agent's work, a state the work waits in
(`<step>-pending-approval`), and then the human's decision. The approval is
therefore a place and an event the ledger records, not a field that claims one.
`BOUNDED_AUTONOMOUS_AGENT` is refused outright if no gate is named.

**No exported agent is ever Level 4 or 5.** Level 4 coordinates a whole
workflow, which is this runtime's job rather than an exported agent's, and
Level 5 is redesign-only and refused by the generator.

## Adding or changing a classification policy

1. Change `_base_recommendation`, `_FLOOR_CEILINGS`, or `_SUPERVISION` in
   `src/governance/cooperation.py`. Keep each a pure function of the declared
   characteristics — no I/O, no model call, no clock.
2. A new floor is a **ceiling**. It must only ever restrict; a floor that
   raises autonomy is a contradiction and will fail
   `test_a_floor_only_ever_restricts`.
3. Add both halves of the test pair in `tests/test_cooperation.py`: the case
   that triggers your rule, and a neighbouring case that must not.
4. Regenerate this guide.

The recommendation is the beginning of a conversation, not the end of one. It
is deliberately conservative, it is always overridable toward a human, and
nothing it produces assigns work by itself — assignment, approval and export
are later steps, each of which keeps a person in the loop.
