# Product lifecycle overview

What this runtime is for, in one page, before any of the reference documents.

## The claim

A workflow that involves both people and AI agents fails in a specific way: not
because the model is bad, but because **nobody wrote down who is accountable for
what.** The gaps were there before any agent arrived. Automating on top of them
makes them faster and harder to see.

So this runtime does the unglamorous thing first. It makes you write the
workflow down, tells you deterministically where the accountability holes are,
refuses to let you promote it until they are closed, and only then asks which
steps an agent should touch.

## The order, and why it is that order

```
Observed Human Workflow
        ↓   validate, repair
Validated Accountable Workflow
        ↓   assess, approve
Cooperative Human–AI Workflow
        ↓   export
Executable Fukasawa Runtime
```

> **Human workflow truth comes first. Accountability comes second.
> Cooperation comes third. Execution comes last.**

Each arrow is a gate, and the order is not cosmetic:

- You cannot assess **who should do a step** before you know **who does it
  today** — that is the difference between designing a process and automating a
  guess.
- You cannot decide an agent may act unsupervised before anyone has said the
  step is reversible, low-risk and repeatable.
- You cannot export to a runtime a workflow whose completion nobody has defined,
  because the runtime would have no way to know it was finished.

## The five stages

### 1. Observe — record what actually happens

A `HumanWorkflowDraft` captures the process **including the parts nobody wrote
down**: unwritten rules, observed exceptions, known pain points, where the
knowledge really lives.

The load-bearing design decision: **a draft full of gaps is not a failure.** It
is an honest recording, and honesty is the point. Nothing here refuses to save
an incomplete workflow — a tool that did would guarantee it never learned the
truth.

### 2. Validate — find the holes, deterministically

Sixteen rules, each with a stable id, a location, a severity, a blocking policy
and a remediation. **No model is involved.** The same workflow always produces
the same findings, which is what makes a finding arguable instead of an opinion.

Findings are typed data, not sentences: rule, workflow, step, field, severity,
what to do. One defect per finding — a rule that bundles unrelated problems into
one message makes the report unactionable, and that is a defect in the rule.

The rules validate five dimensions: **structure, accountability, information
requirements, reasoning load, resilience.**

> **"Blocking" means blocking promotion.** It never means blocking capture,
> save, or reload. Findings gate the promotion, not the truth.

### 3. Repair or accept — close the gap, or decide to live with it

Two legitimate responses to a finding:

- **Fix it.** The remediation says how.
- **Accept it**, if it is advisory — with your name, the time, and a reason, all
  three mandatory. An acceptance without a reason is not a decision, it is a
  shrug.

A **blocking** finding cannot be accepted. Waiving one would turn the gate into
a formality, and then the whole apparatus is theatre.

This is where the heuristic rules earn their keep. HW-013 flags knowledge that
lives in someone's head; it is advisory precisely so that admitting "artwork is
optional in practice, whatever the process says" is rewarded with visibility
rather than punished with a blocked promotion.

### 4. Cooperate — decide who should do each step

Once a workflow is `ACCOUNTABLE`, every step gets a `CooperationAssessment`:
a recommended executor, with a rationale, from a **published decision table**
reading facts declared on the step — judgment load, repeatability, determinism,
risk, reversibility, data sensitivity.

Seven executor classes, ordered by how much unsupervised latitude they grant:

| | Class |
|---|---|
| 0 | `NOT_READY_FOR_AUTOMATION` — the honest answer when the facts are unknown |
| 1 | `HUMAN_ONLY` |
| 2 | `HUMAN_LED_AI_ASSISTED` |
| 3 | `AGENT_PREPARED_HUMAN_APPROVED` |
| 4 | `DETERMINISTIC_AUTOMATION` |
| 5 | `AGENT_EXECUTED_HUMAN_SUPERVISED` |
| 6 | `BOUNDED_AUTONOMOUS_AGENT` |

`DETERMINISTIC_AUTOMATION` deliberately ranks *below* a supervised agent: a
script that always does the same thing has no latitude to misjudge. The axis is
**how much judgment is delegated**, not how absent the human is.

Every characteristic defaults to `UNKNOWN`, and **`UNKNOWN` always resolves
toward human control.** A step nobody has characterized is never treated as safe
to automate.

#### Safety floors are one-directional

An irreversible effect, high risk, sensitive data, or an undefined decision
authority sets a **floor**. A human may always move work *toward* human control.
A human may **not** move a floored step toward greater autonomy — and the
refusal names the remedy: if the fact is wrong, change the characteristic, and
the recommendation follows. Preferring a different answer is not a reason.

Every override needs an actor and a rationale.

### 5. Export — hand it to the runtime that already works

An approved `CooperativeWorkflow` flattens into the existing `WorkflowBrief`,
which the proven state machine, ledger and package generator already execute.
This layer adds a front end to governance; it is not a second runtime.

The flattening preserves the human authority rather than dropping it. A step
classified `AGENT_PREPARED_HUMAN_APPROVED` becomes **three** states — the
agent's work, a waiting state, the person's decision — so the approval is
somewhere the work sits and something the ledger records.

## The maturity ladder

```
OBSERVED → MAPPED → ACCOUNTABLE → COOPERATION_READY
        → COOPERATIVE_DESIGN_APPROVED → RUNTIME_READY → DEPLOYED → VALIDATED
```

Promotion moves **exactly one step**. There is no path from `OBSERVED` to
`RUNTIME_READY`; a workflow that skipped mapping has not become accountable by
being declared so.

Promotion **produces a new artifact** and leaves the source alone, recording who
promoted it, when, and under which rule-set and schema versions. Refusals are
recorded too — keeping only the successes would make the record an advertisement
rather than an audit.

This release enforces gates through `RUNTIME_READY`. `DEPLOYED` and `VALIDATED`
are recorded states whose evidence comes from the run ledger and evaluation
machinery that already exist.

## Two properties that hold everywhere

**Nothing authoritative involves a model.** Validation, promotion eligibility,
classification, export and persistence are all deterministic. AI assistance is
optional, clearly separated, and may never silently alter authoritative state.
This is what makes the whole thing auditable.

**A refusal is not an error.** When the runtime declines — an unapproved export,
an override across a floor, a blocking finding someone tried to accept — it
understood the request and said no, with a reason and a remedy. Both the CLI and
the desktop render refusals distinctly from mistakes, because the operator needs
to read them rather than retry them.

## Two surfaces, one implementation

The CLI (`docs/cli-guide.md`) and the CustomTkinter desktop
(`docs/desktop-guide.md`) call **the same service functions**. Neither owns a
rule. If they ever disagreed about a workflow, one of them stopped calling them
— which is asserted mechanically, not trusted.

## Where to go next

| You want to | Read |
|---|---|
| See it done on a real workflow | `docs/pilot-walkthrough.md` |
| Know what the rules check | `docs/validator-rule-catalog.md` |
| Know what the contracts hold | `docs/schema-reference.md` |
| Know what each maturity state means | `docs/promotion-state-reference.md` |
| Know how executors are chosen | `docs/cooperation-classification-guide.md` |
| Drive it from a terminal | `docs/cli-guide.md` |
| Drive it from the desktop | `docs/desktop-guide.md` |

## What this deliberately is not

Not a multi-agent framework, not a swarm, not a node-canvas editor, not a
marketplace, not an orchestration engine. It does not model every organization,
replace every worker, or automate every decision.

It proves one sequence:

```
map → validate → repair → cooperate → export
```
