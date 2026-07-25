<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Copyright (C) 2026 ConcordiaPax LLC -->

# Validator Rule Catalog

The deterministic rules that validate an observed human workflow. Generated
from `src/governance/workflow_rules.py`, so this catalog cannot drift from the
code — regenerate it when the registry changes.

**16 rules — 14 blocking, 2 advisory.**

## What blocking means

A blocking finding blocks **promotion to `ACCOUNTABLE`**. It never blocks
capture, save, or reload. An observed workflow is allowed to be a mess —
recording it honestly is the first stage of the lifecycle. Anything that
refuses to save an incomplete draft is a defect, not strictness.

Blocking findings **cannot** be accepted as residual risk; they must be fixed.
Advisory findings never gate promotion, and may be consciously accepted with a
named actor and a rationale.

No LLM is involved in any rule. The same workflow always produces the same
findings, in the same order, with the same messages.

## Rules at a glance

| Rule | Policy | Dimension | Title |
|---|---|---|---|
| [`HW-001`](#hw-001) | **blocking** | STRUCTURE | Undefined workflow trigger |
| [`HW-002`](#hw-002) | **blocking** | STRUCTURE | Undefined claimed outcome or terminal completion |
| [`HW-003`](#hw-003) | **blocking** | ACCOUNTABILITY | Missing step owner |
| [`HW-004`](#hw-004) | **blocking** | ACCOUNTABILITY | Missing or ambiguous decision authority |
| [`HW-005`](#hw-005) | **blocking** | STRUCTURE | Referenced next step does not exist |
| [`HW-006`](#hw-006) | **blocking** | STRUCTURE | Unreachable step |
| [`HW-007`](#hw-007) | **blocking** | STRUCTURE | Accidental dead-end state |
| [`HW-008`](#hw-008) | **blocking** | INFORMATION | Implicit or incomplete handoff |
| [`HW-009`](#hw-009) | **blocking** | INFORMATION | Missing required input source |
| [`HW-010`](#hw-010) | **blocking** | INFORMATION | Output without artifact type or evidence requirement |
| [`HW-011`](#hw-011) | **blocking** | RESILIENCE | Missing exception path for a declared failure mode |
| [`HW-012`](#hw-012) | **blocking** | RESILIENCE | Unowned exception |
| [`HW-013`](#hw-013) | advisory | REASONING_LOAD | Human memory dependency or unwritten rule |
| [`HW-014`](#hw-014) | advisory | INFORMATION | Ambiguous terms without criteria |
| [`HW-015`](#hw-015) | **blocking** | RESILIENCE | Rejection or approval gate without a next action |
| [`HW-016`](#hw-016) | **blocking** | ACCOUNTABILITY | Unsupported completion claim |

## Rule detail

### HW-001

**Undefined workflow trigger** · **blocking** · severity `ERROR` · dimension `STRUCTURE` · version `1`

The workflow does not state what causes it to start.

**Remediation offered:** State what event or condition starts this workflow.

### HW-002

**Undefined claimed outcome or terminal completion** · **blocking** · severity `ERROR` · dimension `STRUCTURE` · version `1`

The workflow does not say what it achieves, or no reachable step ends it.

**Remediation offered:** State what the workflow achieves when it succeeds.

### HW-003

**Missing step owner** · **blocking** · severity `ERROR` · dimension `ACCOUNTABILITY` · version `1`

A step does not name who performs it.

**Remediation offered:** Name the person, role, or system that performs this step.

### HW-004

**Missing or ambiguous decision authority** · **blocking** · severity `ERROR` · dimension `ACCOUNTABILITY` · version `1`

A step that branches, is gated, or has irreversible or high-risk effect does not name who decides — or names no one in particular.

**Remediation offered:** Name the specific person or role with authority to decide here.

### HW-005

**Referenced next step does not exist** · **blocking** · severity `ERROR` · dimension `STRUCTURE` · version `1`

A route points to a step id that is not declared.

**Remediation offered:** Add the missing step, or correct the reference to an existing one.

### HW-006

**Unreachable step** · **blocking** · severity `ERROR` · dimension `STRUCTURE` · version `1`

A declared step cannot be reached from the entry step.

**Remediation offered:** Route to this step from where it really happens, or remove it.

### HW-007

**Accidental dead-end state** · **blocking** · severity `ERROR` · dimension `STRUCTURE` · version `1`

Work arrives somewhere that produces nothing and leads nowhere, or a failure has neither handling nor a next step.

**Remediation offered:** Say what this step produces, or route it onward to the step that follows.

### HW-008

**Implicit or incomplete handoff** · **blocking** · severity `ERROR` · dimension `INFORMATION` · version `1`

Work crosses from one actor to another with no verifiable artifact handed over.

**Remediation offered:** Give the upstream step an output with an artifact type and an evidence requirement, so the receiver knows what they are getting.

### HW-009

**Missing required input source** · **blocking** · severity `ERROR` · dimension `INFORMATION` · version `1`

A required input does not say where it comes from.

**Remediation offered:** Name the actor, system, or upstream step this input comes from.

### HW-010

**Output without artifact type or evidence requirement** · **blocking** · severity `ERROR` · dimension `INFORMATION` · version `1`

An output cannot be identified or verified.

**Remediation offered:** State what kind of artifact this is and what proves it exists.

### HW-011

**Missing exception path for a declared failure mode** · **blocking** · severity `ERROR` · dimension `RESILIENCE` · version `1`

A failure the workflow says happens in practice has no exception path.

**Remediation offered:** Add an exception path for this failure on the step where it occurs, with an owner and what is done.

### HW-012

**Unowned exception** · **blocking** · severity `ERROR` · dimension `RESILIENCE` · version `1`

An exception path does not name who handles it.

**Remediation offered:** Name the specific person or role who handles this failure.

### HW-013

**Human memory dependency or unwritten rule** · advisory · severity `WARNING` · dimension `REASONING_LOAD` · version `1`

The workflow depends on knowledge that exists only in someone's head.

**Remediation offered:** Write the rule into the step it governs, or accept it as a known residual risk with a rationale.

### HW-014

**Ambiguous terms without criteria** · advisory · severity `WARNING` · dimension `INFORMATION` · version `1`

A state is described by feel — 'ready', 'complete', 'approved' — with no criteria for judging it.

**Remediation offered:** Replace the term with a checkable condition, or state the criteria used to judge it.

### HW-015

**Rejection or approval gate without a next action** · **blocking** · severity `ERROR` · dimension `RESILIENCE` · version `1`

A gate can reject, but nothing says what happens then.

**Remediation offered:** State where work goes when this gate rejects — the step it returns to, or the action taken.

### HW-016

**Unsupported completion claim** · **blocking** · severity `ERROR` · dimension `ACCOUNTABILITY` · version `1`

The workflow claims an outcome that no reachable step produces evidence for.

**Remediation offered:** Give the completing step an output whose evidence requirement proves the claimed outcome.

## Shared vocabulary

Several rules ask whether a field is *undefined* or *ambiguous*. Those words
have exact meanings, listed here so an operator can predict what the validator
will say. A rule nobody can predict is a rule people learn to ignore.

**Treated as undefined** (in addition to empty): `-`, `--`, `?`, `??`, `???`, `n/a`, `na`, `none`, `tba`, `tbd`, `todo`, `unclear`, `unknown`.

**Treated as an ambiguous owner** (names no one in particular): `anyone`, `as needed`, `depends`, `everyone`, `it depends`, `shared`, `somebody`, `someone`, `tbd`, `team`, `the team`, `varies`, `whoever`, `whoever is available`.

### How HW-014 decides

Two classes of vague language, treated differently:

- **Perception words** — always reported, because no surrounding grammar makes
  them checkable. "Done when it looks fine" says no more than "done when it
  feels done": `acceptable`, `appropriate`, `as needed`, `clean`, `feels`, `fine`, `good`, `high quality`, `looks`, `ok`, `okay`, `polished`, `quality`, `reads as`, `seems`, `when appropriate`.
- **State words** — reported *only* when the text offers no criterion beside
  them: `approved`, `complete`, `completed`, `done`, `ready`, `sufficient`.

A criterion is considered stated when the text contains any digit or one of:
`%`, `<=`, `>=`, `all `, `approved by`, `at least`, `checklist`, `confirmed`, `contains`, `criteria`, `each`, `equals`, `every`, `exists`, `greater`, `if`, `less than`, `matches`, `no more than`, `passes`, `percent`, `reviewed by`, `signed`, `under`, `verified`, `when`, `within`.

So `approved when at least one reviewer has signed it` is accepted, while bare
`approved` and `approved when it looks right` are both reported.

### How HW-011 matches failures

An observed failure counts as handled when some step declares an exception path
whose description shares **at least half** of the observed failure's
meaning-carrying words. Exact text matching would be useless — nobody restates
a failure the same way twice — and anything cleverer would stop being
predictable. Half is the documented threshold.

### How HW-013 spots memory dependencies

Every entry in `unwritten_rules` produces one advisory finding. Step text is
additionally scanned for: `in the operator's head`, `in their head`, `in his head`, `in her head`, `from memory`, `remembers`, `remember to`, `just knows`, `tribal knowledge`, `nobody wrote`, `not written down`, `undocumented`, `everyone knows`.

### Why HW-004 does not ask every step who decides

A purely linear step that always does the same next thing decides nothing, and
demanding a decision authority for it would put noise on every well-formed
workflow. HW-004 fires only where a decision genuinely exists: the step
branches to more than one next step, a gate guards it, or its effect is
`IRREVERSIBLE` or `HIGH` risk — someone must own an act that cannot be undone.

## Adding a rule

1. Write a `detect(index) -> list[WorkflowFinding]` function in
   `src/governance/workflow_rules.py`. Use `WorkflowIndex` for reachability and
   gate lookups rather than walking the workflow again.
2. Every finding must carry a location (step or gate, plus the field at fault)
   and a remediation. One defect per finding — never bundle unrelated problems
   into one message.
3. Build the finding with `_make_finding`, which derives a deterministic id from
   the rule and the place it fired. Findings are persisted and referenced by
   risk acceptances, so a stable id is a correctness requirement.
4. Declare a `Rule` with the next free id. **Never renumber an existing id** —
   ids live permanently on stored findings and acceptances.
5. Severity follows policy: blocking rules are `ERROR`, advisory rules are
   `WARNING`. A test enforces this.
6. Add both halves of the required test pair in `tests/test_workflow_rules.py`:
   the rule stays silent on `clean-workflow.yaml`, and fires on a copy of it
   with exactly one defect introduced.
7. Regenerate this catalog.

If your rule makes `tests/fixtures/workflows/clean-workflow.yaml` report
anything, the rule is too aggressive. Fix the rule, not the fixture.
