# Schema Reference — Human & Cooperative Workflow contracts

Covers the contracts added for the Human Workflow Validator/Builder and
Cooperative Workflow Builder. Written for people who edit these files by hand,
not only for developers.

## Which documents are authoritative

| Source | Status |
|---|---|
| **Pydantic models in `src/schemas/`** | **CANONICAL.** The runtime validates against these; they are the contract (ADR-001). |
| Exported JSON Schema (`fukasawa schema dump`) | Generated from the models. The only permitted basis for a non-Python consumer. |
| This document | Human-readable reference, derived from the models. |
| `specs/*.md` | **Superseded** July-18 drafts. Historical input, not a contract. |
| `docs/architecture.md` | **Aspirational.** Lists objects and adapters that do not all exist. |

If any two disagree, the Pydantic models win.

## Versioning and unknown fields

- Every artifact contract carries **`schema_version`** (currently `"1"`).
  Evolution is additive-only within a major version; removals, renames, or
  semantic changes bump it (ADR-002).
- **Unknown fields are rejected** (`extra="forbid"`) across all new contracts.
  These are hand-written YAML files; a mistyped field name that gets silently
  ignored is precisely the invisible drift this product exists to catch. If
  you get an "extra inputs are not permitted" error, check your spelling
  against the tables below.
- All identifiers (`workflow_id`, `step_id`, `gate_id`) are lowercase,
  hyphen-separated slugs: `substack-publication`, `publish-post`.

## Lifecycle at a glance

```
HumanWorkflowDraft ──validate──> ValidationReport (WorkflowFinding[])
      │                                  │
      │ promote  (no unresolved blocking findings)
      ▼
AccountableWorkflow ──assess──> CooperationAssessment (one per step)
      │                                  │  human review / override
      ▼                                  ▼
CooperativeWorkflow ──export──> WorkflowBrief  ──> existing runtime
```

## `HumanWorkflowDraft` — the observed process

A workflow as it **actually happens**, gaps included. Deliberately permissive:
findings never prevent a draft from being written, saved, or reloaded.

| Field | Meaning |
|---|---|
| `workflow_id`, `name`, `version` | Identity and revision. |
| `maturity` | Where it sits on the ladder. Drafts start `OBSERVED`. |
| `purpose` | Why the workflow exists. |
| `trigger` | What starts it. Empty → **HW-001 (blocking)**. |
| `claimed_outcome` | What it is supposed to achieve. Empty → **HW-002 (blocking)**. |
| `actors`, `systems`, `artifacts` | Who and what is involved. |
| `steps` | The work. **First step is the entry point.** |
| `gates` | Observed approval/review points. |
| `observed_exceptions` | Failure modes seen in practice. One with no matching exception path → **HW-011**. |
| `unwritten_rules` | What people know but nobody wrote down. Flagged **HW-013 (non-blocking)** — recording these is honesty, not failure. |
| `known_pain_points` | Where it hurts today, in the operators' words. |
| `source_evidence` | Where the observations came from. |

## `WorkflowStep` — one unit of work

Shared by drafts and accountable workflows: promotion resolves accountability
without reshaping the work.

| Field | Meaning |
|---|---|
| `step_id` | Stable slug, unique in the workflow. |
| `name`, `description`, `action` | What happens. |
| `actor` | Who performs it. Empty → **HW-003 (blocking)**. |
| `trigger`, `preconditions` | What must happen/be true first. |
| `inputs` | `name`, `source`, `required`. Required input with no source → **HW-009**. |
| `outputs` | `name`, `artifact_type`, `evidence_requirement`. Missing either → **HW-010**. |
| `entry_condition`, `exit_condition` | How you know it started/finished. Vague exit → **HW-014**. |
| `decision_authority` | Who decides here. Empty or vague → **HW-004 (blocking)**. |
| `next_steps` | Step ids that may follow. Empty = terminal (intended for the last step, **HW-007** anywhere else). Unknown id → **HW-005**. |
| `exception_paths` | `failure_mode`, `owner`, `handling`, `next_step`. Missing owner → **HW-012**. |
| `characteristics` | See below — drives cooperation assessment. |

### `StepCharacteristics` — what makes cooperation safe

Six observable properties, each defaulting to `UNKNOWN`. **`UNKNOWN` always
resolves toward human control**: an uncharacterized step is never treated as
safe to automate.

| Field | Values |
|---|---|
| `judgment_load` | `UNKNOWN`, `NONE`, `LOW`, `MODERATE`, `HIGH` |
| `repeatability` | `UNKNOWN`, `ONE_OFF`, `OCCASIONAL`, `ROUTINE` |
| `determinism` | `UNKNOWN`, `DETERMINISTIC`, `MOSTLY_DETERMINISTIC`, `JUDGMENT_BASED` |
| `risk` | `UNKNOWN`, `LOW`, `MODERATE`, `HIGH` |
| `reversibility` | `UNKNOWN`, `REVERSIBLE`, `PARTIALLY_REVERSIBLE`, `IRREVERSIBLE` |
| `data_sensitivity` | `UNKNOWN`, `PUBLIC`, `INTERNAL`, `SENSITIVE` |

## `WorkflowFinding` / `ValidationReport`

A finding is **one defect, in one place, with one remediation**.

| Field | Meaning |
|---|---|
| `finding_id` | Unique within its report. |
| `rule` | `rule_id` (`HW-004`) + `rule_version`. Rule ids are **never renumbered** — they are persisted on findings and acceptances permanently. |
| `finding_type` | `STRUCTURE`, `ACCOUNTABILITY`, `INFORMATION`, `REASONING_LOAD`, `RESILIENCE`. |
| `severity` | `ERROR`, `WARNING`, `INFO` — a description. |
| `blocking` | A policy, separate from severity. See below. |
| `message` | Deterministic: the same workflow always yields the same text. |
| `location` | `workflow_id`, `step_id`, `gate_id`, `field`, `detail`. |
| `remediation` | What to do, concretely. |
| `acceptance` | Set when a human accepted it as residual risk. |

### What "blocking" means

**Blocking means blocking promotion to `ACCOUNTABLE`. It never means blocking
capture, save, or reload.** An observed workflow is allowed to be a mess —
recording it honestly is the first stage of the lifecycle. Anything that
refuses to save an incomplete draft is a defect, not strictness.

`ValidationReport.promotion_ready` is true when no blocking finding remains
unresolved. Non-blocking findings never gate promotion, accepted or not —
accepting one records a decision, it does not unlock anything.

### `RiskAcceptance`

Requires `accepted_by`, `accepted_at`, and a non-empty `rationale`. An
acceptance without a reason is not a decision.

> **Attribution is self-attested.** This runtime has no authentication, so
> `accepted_by` is a name someone typed. Adequate for a single trusted local
> operator; **insufficient as multi-party non-repudiation.** The upgrade path
> is to sign acceptances with the operator's existing Ed25519 identity
> (`src/security/signing.py`); it is backlogged, not shipped.

## `AccountableWorkflow` — the promoted artifact

Produced by promotion, never by editing; the source draft stays intact for
audit. `trigger`, `owners` (≥1), `steps` (≥1), and `completion_contract` are
all mandatory here — the blocking rules must be resolved first.

It deliberately declares **no `states` or `transitions`**. What §5.4 calls
"states" is the step graph itself: each step is a state the work can be in.
Flattening into the runtime's `WorkflowBrief` happens only at export, because
flattening earlier would destroy the per-step attributes that cooperation
assessment reads next.

`lineage` (`PromotionLineage`) records source workflow and version, from/to
maturity, who promoted it and when, and the **rule set and schema versions**
the decision was made under.

## `WorkflowMaturity` — the ladder

```
OBSERVED → MAPPED → ACCOUNTABLE → COOPERATION_READY
        → COOPERATIVE_DESIGN_APPROVED → RUNTIME_READY → DEPLOYED → VALIDATED
```

All eight values exist so adding gates later is never a breaking change.
**This release enforces gates only through `RUNTIME_READY`.** `DEPLOYED` and
`VALIDATED` are recorded states whose entry criteria delegate to the existing
run ledger and evaluation machinery plus a named human reviewer — no new
deployment automation is built here.

## `ExecutorClass` — who does the work

| Value | Meaning |
|---|---|
| `HUMAN_ONLY` | A person does it; no AI involved. |
| `HUMAN_LED_AI_ASSISTED` | A person does it, AI helps. |
| `AGENT_PREPARED_HUMAN_APPROVED` | An agent prepares, a human authorizes. |
| `AGENT_EXECUTED_HUMAN_SUPERVISED` | An agent acts, a human watches. |
| `DETERMINISTIC_AUTOMATION` | A rule or script; no reasoning needed. |
| `BOUNDED_AUTONOMOUS_AGENT` | An agent acts within stated bounds. Requires an approval gate. |
| `NOT_READY_FOR_AUTOMATION` | Nothing assigned yet — the honest answer when facts are unknown. |

`autonomy_rank` orders these by **how much judgment is delegated**, not by how
absent humans are. Two orderings are deliberate and worth understanding:
`NOT_READY_FOR_AUTOMATION` ranks lowest (nothing is assigned at all), and
`DETERMINISTIC_AUTOMATION` ranks *below* `AGENT_EXECUTED_HUMAN_SUPERVISED` —
a script that always does the same thing has no latitude to misjudge, so it is
safer than an agent acting under observation.

### The one-directional override rule

A human may always move a step **toward** human control. A human may **not**
move a step that hit a safety floor toward greater autonomy. `safety_floor`
records which fact forced the recommendation (`IRREVERSIBLE`, `HIGH_RISK`,
`SENSITIVE_DATA`, `UNDEFINED_AUTHORITY`, `UNKNOWN_CHARACTERISTICS`), so an
operator can see *why*, not merely *that*. Comparing `autonomy_rank` is how
this is enforced in code rather than trusted to convention.

## `CooperativeWorkflow` / `StepAssignment`

Every assignment requires a **`human_owner`** and an **`escalation_target`** —
including fully automated steps. Automation moves the work, never the
accountability. `fallback_executor` defaults to `HUMAN_ONLY`, because falling
back toward a human is always safe. `allowed_tools` is a whitelist: anything
absent is forbidden. Approval (`approved_by`) is a human act recorded on the
artifact; nothing reaches the Agent Foundry path without it.

## Exporting for other languages

Available now (phase 1) as a Python API:

```python
from src.schemas.export_jsonschema import write_schemas, schema_json

write_schemas("schemas/")            # one <contract>.schema.json per contract
print(schema_json("workflow-step"))  # a single contract as canonical JSON
```

The `fukasawa schema dump` CLI wrapper lands with the CLI phase, which owns
`src/cli.py`; the export logic it will call is already in place and tested.

> **What JSON Schema does not carry.** The exported artifacts capture field
> names, types, defaults, and enum values. They do **not** capture rules
> enforced by Pydantic validators or by the runtime — for example the
> one-directional override rule, the mandatory-rationale constraints, or the
> existing doctrine that a CONSCIOUS-depth transition cannot be owned by an
> agent. **A consumer that validates only against these files will accept data
> this runtime rejects.** Those rules are the prose statements in this
> document; a future consumer must implement them deliberately.

This export is the substituted obligation for the cross-language requirement
that was ruled not applicable in a Python-only repository (architecture review
defect D1, ratified 2026-07-25). Hand-written parallel definitions of these
contracts in another language are prohibited; generate from these artifacts.
