# Promotion State Reference

How a workflow earns its way from "we wrote down what actually happens" to
"the runtime can execute this" — and what the runtime refuses to let you skip.

## The ladder

```
OBSERVED → MAPPED → ACCOUNTABLE → COOPERATION_READY
        → COOPERATIVE_DESIGN_APPROVED → RUNTIME_READY → DEPLOYED → VALIDATED
```

**One step at a time.** There is no path from `OBSERVED` to `RUNTIME_READY`.
A workflow that skipped mapping and accountability has not become accountable
by being declared so, and the transition table refuses every jump, every
sideways move, and every step backwards.

| State | Means | Gate to reach it |
|---|---|---|
| `OBSERVED` | captured from life, gaps included | none — capture is never blocked |
| `MAPPED` | structurally sound | no unresolved **structural** blocking findings (HW-001, 002, 005, 006, 007) and at least one step |
| `ACCOUNTABLE` | every gap closed or consciously accepted | **no unresolved blocking findings at all**, plus a stated trigger, a defined completion, and every step owned |
| `COOPERATION_READY` | every executable step assessed | a cooperation assessment per step *(phase 4)* |
| `COOPERATIVE_DESIGN_APPROVED` | a human approved the executor assignments | approved cooperative workflow *(phase 4/5)* |
| `RUNTIME_READY` | exported to something the runtime can run | export to a workflow brief *(phase 5)* |
| `DEPLOYED` | agent packages generated and in use | **delegated** — evidence from real runs, plus a named reviewer |
| `VALIDATED` | evaluation evidence shows it works | **delegated** — evaluation results, plus a named reviewer |

### What this release enforces

Gates are enforced with their own logic **through `RUNTIME_READY`**. Attempting
a promotion past it is refused with a stated reason rather than silently
allowed.

`DEPLOYED` and `VALIDATED` exist in the enum so that adding their gates later is
never a breaking schema change, but this release builds **no new deployment
machinery** — their criteria delegate to evidence the runtime already produces
(the run ledger, evaluation results) plus a named human. Automatic deployment
without explicit approval is a stated non-goal.

## What blocks, and what may be accepted

**Blocking findings must be fixed. They cannot be accepted away.** Permitting a
waiver would turn the gate into a formality — `accept_risk()` refuses outright,
and names the remediation instead.

**Non-blocking findings may be consciously accepted**, and only with all three
of: an actor, a timestamp, and a non-empty rationale. An acceptance without a
reason is not a decision. Accepted risks travel onto the promoted artifact, so
the residual risk stays attached to the workflow rather than living in a report
nobody re-reads.

> **Blocking never means "blocks capture."** An observed workflow is allowed to
> be a mess; recording it honestly is the first stage of the lifecycle. Blocking
> means *blocks promotion to `ACCOUNTABLE`*.

## Promotion produces artifacts, not mutations

| Transition | What it produces |
|---|---|
| `OBSERVED → MAPPED` | the draft advances in place; the move is recorded in the append-only promotion trail with the report it was based on |
| `MAPPED → ACCOUNTABLE` | a separate, immutable `AccountableWorkflow`; **the source draft is untouched** |

An `AccountableWorkflow` deliberately declares **no states or transitions**. The
steps *are* the states. Flattening into a runnable `WorkflowBrief` happens at
export, after cooperation assessment has read the per-step attributes —
decision authority, reversibility, data sensitivity — that flattening would
destroy.

**Artifacts are never overwritten.** Promoting a version that already has an
artifact is refused with instructions to bump the draft version, because an
audit may already cite what is stored. Earlier versions stay readable.

## The audit trail

Every transition attempt lands in `workflow_promotions` — **including refusals**.
A history showing only the promotions that succeeded would be an advertisement,
not an audit. Each row records:

- from and to maturity, and whether it was granted
- who promoted it and when
- the **rule set version and schema version** the decision was made under
- the id of the validation report cited as evidence
- the refusal reason, or what was produced

Four tables are append-only and enforced by SQLite triggers, so even code with a
direct database handle cannot rewrite them: `validation_reports`,
`risk_acceptances`, `workflow_promotions`, `accountable_workflows`.
`workflow_drafts` is deliberately **not** — a draft is a working document people
edit, and forbidding that would make capture impossible.

## Attribution is self-attested

`promoted_by` and `accepted_by` are names someone typed. This runtime has no
authentication, and organization-wide identity management is a stated non-goal.

**That is adequate for a single trusted local operator and insufficient as
multi-party non-repudiation.** Stated plainly rather than implied, because an
audit trail that looks stronger than it is, is worse than one whose limits are
known. The upgrade path — signing promotions and acceptances with the operator's
existing Ed25519 identity (`src/security/signing.py`) — is backlogged, not
shipped.

## Three state machines, deliberately separate

| Machine | Tracks | Where |
|---|---|---|
| run states | where one execution of a workflow stands | `src/runtime/state_machine.py` |
| agent maturity | `draft → tested → validated` for an agent package | `src/governance/maturity.py` |
| **workflow maturity** | this ladder | `src/governance/workflow_promotion.py` |

They are different axes and are not merged: a `VALIDATED` workflow may contain
draft agent packages, and a completed run says nothing about whether the
workflow it ran is accountable. Conflating them would corrupt all three
evidence models.

## Usage

```python
from src.governance.workflow_rules import validate_workflow
from src.governance.workflow_promotion import assess, accept_risk, promote

report = validate_workflow(draft)

# See the picture before trying: what is met, what is missing.
picture = assess(draft, report)
print(picture.target, picture.allowed, [c.detail for c in picture.unmet])

# Consciously accept an advisory finding.
accept_risk(ledger, draft.workflow_id, report, finding_id,
            accepted_by="flaveon", rationale="Known and tolerated; revisit if it bites.")

# Promote one step. Raises PromotionRefusedError, having recorded the refusal.
outcome = promote(ledger, draft, report, promoted_by="flaveon")
outcome.draft      # set when the draft advanced (→ MAPPED)
outcome.artifact   # set when an artifact was produced (→ ACCOUNTABLE)
```

`assess()` never raises and never promotes — it answers "could this move up, and
if not, what is missing," so an operator sees the whole picture before trying.
