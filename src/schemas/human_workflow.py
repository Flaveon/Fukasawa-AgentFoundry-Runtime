# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Human workflow contracts — observed truth first, accountability second.

This module holds the first two stages of the release lifecycle:

    Observed Human Workflow  ->  Validated Accountable Workflow

A ``HumanWorkflowDraft`` captures a process **as it actually happens**,
including the parts nobody wrote down: unwritten rules, remembered steps,
pain points, observed exceptions. It is deliberately permissive. A draft full
of gaps is not a failure — it is an honest recording, and honesty is the
point. Validation findings never prevent a draft from being written, saved,
or reloaded; they only prevent *promotion*.

An ``AccountableWorkflow`` is what a draft becomes once every gap that
matters has been closed or consciously accepted: every step owned, every
decision authority named, every exception handled, completion defined. It is
produced by promotion, not by editing — the draft it came from stays intact
for audit.

Two design rulings are load-bearing here (architecture review D3):

* ``AccountableWorkflow`` **reuses ``WorkflowStep``** rather than re-modeling
  the work. Promotion resolves accountability; it does not reshape structure.
* It introduces **no** ``states``/``transitions`` vocabulary. That flattening
  belongs to export (``src/foundry/workflow_export.py``), which turns an
  approved cooperative workflow into the runtime's existing ``WorkflowBrief``.
  Flattening early would destroy the per-step attributes — decision
  authority, reversibility, data sensitivity — that cooperation assessment
  reads next. The "states" required of an accountable workflow are its steps:
  each step is a state the work can be in.

Unknown fields are rejected across this module (``extra="forbid"``). These
files are hand-written YAML; a mistyped field name that is silently ignored
is exactly the invisible drift this product exists to catch.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

# RiskAcceptance is defined once, in the findings module that owns the concept,
# and reused here — an accepted risk on a promoted workflow is the same object
# that was attached to the finding, not a copy of it.
from src.schemas.findings import RiskAcceptance

#: Shared model config: reject unknown fields so typos surface loudly.
STRICT = ConfigDict(extra="forbid")

#: Slug pattern for every identifier in this module (lowercase, hyphenated).
SLUG = r"^[a-z0-9]+(-[a-z0-9]+)*$"

#: Current schema version for every contract in this module. Additive-only
#: within a major version; removals or semantic changes bump it (ADR-002).
SCHEMA_VERSION = "1"


class WorkflowMaturity(str, Enum):
    """How far a workflow has progressed from observation toward execution.

    All eight values exist from the first release so that adding gates later
    never requires a breaking schema change. **This release enforces
    promotion gates only through RUNTIME_READY** (architecture review D4);
    DEPLOYED and VALIDATED are recorded states whose entry criteria delegate
    to the existing run ledger and evaluation machinery plus a named human
    reviewer. No new deployment automation is built here.

    OBSERVED                    — captured from life; gaps expected.
    MAPPED                      — steps and references are structurally sound.
    ACCOUNTABLE                 — every step owned, every exception handled.
    COOPERATION_READY           — every executable step has an assessment.
    COOPERATIVE_DESIGN_APPROVED — a human approved the executor assignments.
    RUNTIME_READY               — exported to a workflow brief the runtime can run.
    DEPLOYED                    — agent packages generated and in use (evidence-based).
    VALIDATED                   — evaluation evidence shows it works (evidence-based).
    """

    OBSERVED = "OBSERVED"
    MAPPED = "MAPPED"
    ACCOUNTABLE = "ACCOUNTABLE"
    COOPERATION_READY = "COOPERATION_READY"
    COOPERATIVE_DESIGN_APPROVED = "COOPERATIVE_DESIGN_APPROVED"
    RUNTIME_READY = "RUNTIME_READY"
    DEPLOYED = "DEPLOYED"
    VALIDATED = "VALIDATED"


# --------------------------------------------------------------------- factors
#
# The enums below describe observable facts about a step. Cooperation
# assessment (phase 4) reads them through a published decision table, so they
# live on the step where they can be observed and reviewed — not inside the
# engine. Every one defaults to UNKNOWN, and UNKNOWN always resolves toward
# human control rather than automation.


class JudgmentLoad(str, Enum):
    """How much human judgment the step's decision genuinely requires."""

    UNKNOWN = "UNKNOWN"
    NONE = "NONE"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class Repeatability(str, Enum):
    """How often this step recurs in the same shape."""

    UNKNOWN = "UNKNOWN"
    ONE_OFF = "ONE_OFF"
    OCCASIONAL = "OCCASIONAL"
    ROUTINE = "ROUTINE"


class Determinism(str, Enum):
    """Whether the same inputs reliably produce the same output."""

    UNKNOWN = "UNKNOWN"
    DETERMINISTIC = "DETERMINISTIC"
    MOSTLY_DETERMINISTIC = "MOSTLY_DETERMINISTIC"
    JUDGMENT_BASED = "JUDGMENT_BASED"


class RiskLevel(str, Enum):
    """How much damage a wrong outcome at this step causes."""

    UNKNOWN = "UNKNOWN"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class Reversibility(str, Enum):
    """Whether the step's effect can be undone after the fact."""

    UNKNOWN = "UNKNOWN"
    REVERSIBLE = "REVERSIBLE"
    PARTIALLY_REVERSIBLE = "PARTIALLY_REVERSIBLE"
    IRREVERSIBLE = "IRREVERSIBLE"


class DataSensitivity(str, Enum):
    """How sensitive the data this step handles is."""

    UNKNOWN = "UNKNOWN"
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    SENSITIVE = "SENSITIVE"


class StepCharacteristics(BaseModel):
    """Observable properties of a step that determine safe cooperation.

    Grouped into one object so a step stays readable and so the cooperation
    decision table has a single, auditable input surface. Every field
    defaults to UNKNOWN: a step nobody has characterized is never treated as
    safe to automate.
    """

    model_config = STRICT

    judgment_load: JudgmentLoad = Field(
        default=JudgmentLoad.UNKNOWN,
        description="How much human judgment the decision at this step requires.",
    )
    repeatability: Repeatability = Field(
        default=Repeatability.UNKNOWN,
        description="How often this step recurs in the same shape.",
    )
    determinism: Determinism = Field(
        default=Determinism.UNKNOWN,
        description="Whether identical inputs reliably produce identical output.",
    )
    risk: RiskLevel = Field(
        default=RiskLevel.UNKNOWN,
        description="How much damage a wrong outcome at this step causes.",
    )
    reversibility: Reversibility = Field(
        default=Reversibility.UNKNOWN,
        description="Whether this step's effect can be undone afterward.",
    )
    data_sensitivity: DataSensitivity = Field(
        default=DataSensitivity.UNKNOWN,
        description="How sensitive the data handled at this step is.",
    )


# ----------------------------------------------------------------- step pieces


class StepInput(BaseModel):
    """Something a step needs before it can run."""

    model_config = STRICT

    name: str = Field(description="What the input is, in plain language.")
    source: str = Field(
        default="",
        description=(
            "Where the input comes from — an actor, a system, or an earlier "
            "step's output. Empty means the source was never identified, "
            "which rule HW-009 reports."
        ),
    )
    required: bool = Field(
        default=True,
        description="Whether the step cannot proceed without this input.",
    )


class StepOutput(BaseModel):
    """Something a step produces."""

    model_config = STRICT

    name: str = Field(description="What the output is, in plain language.")
    artifact_type: str = Field(
        default="",
        description=(
            "The kind of artifact produced (document, file, message, "
            "decision, ...). Empty is reported by rule HW-010."
        ),
    )
    evidence_requirement: str = Field(
        default="",
        description=(
            "What must exist to prove this output was really produced. Empty "
            "is reported by rule HW-010 — an unverifiable output is how "
            "unsupported completion claims start."
        ),
    )


class ExceptionPath(BaseModel):
    """What happens when a declared failure mode occurs."""

    model_config = STRICT

    failure_mode: str = Field(
        description="The thing that goes wrong, stated plainly."
    )
    owner: str = Field(
        default="",
        description=(
            "Who handles this failure. Empty means the exception is unowned, "
            "which rule HW-012 reports as blocking."
        ),
    )
    handling: str = Field(
        default="",
        description="What is actually done when the failure occurs.",
    )
    next_step: Optional[str] = Field(
        default=None,
        description=(
            "Step id work moves to when this failure is handled. None means "
            "the failure ends the workflow."
        ),
    )


class WorkflowStep(BaseModel):
    """One unit of observed work.

    Shared by ``HumanWorkflowDraft`` and ``AccountableWorkflow``: promotion
    resolves accountability without reshaping the work (architecture review
    D3). Dangling ``next_steps`` references are caught structurally by the
    containing model; reachability and dead ends are semantic questions
    answered by validator rules HW-005, HW-006, and HW-007.
    """

    model_config = STRICT

    step_id: str = Field(
        pattern=SLUG,
        description="Stable identifier for this step, unique within the workflow.",
    )
    name: str = Field(description="Short human-readable name for the step.")
    description: str = Field(
        default="", description="What happens at this step, in plain language."
    )
    actor: str = Field(
        default="",
        description=(
            "Who performs this step — a person, role, team, or system. Empty "
            "means the step is unowned, which rule HW-003 reports as blocking."
        ),
    )
    action: str = Field(
        default="", description="The work performed, stated as a verb phrase."
    )
    trigger: str = Field(
        default="", description="What causes this step to begin."
    )
    preconditions: list[str] = Field(
        default_factory=list,
        description="What must already be true before this step can start.",
    )
    inputs: list[StepInput] = Field(
        default_factory=list, description="What this step consumes."
    )
    outputs: list[StepOutput] = Field(
        default_factory=list, description="What this step produces."
    )
    entry_condition: str = Field(
        default="", description="How you know the step has properly begun."
    )
    exit_condition: str = Field(
        default="",
        description=(
            "How you know the step is finished. Vague exit conditions "
            "('when it looks ready') are reported by rule HW-014."
        ),
    )
    decision_authority: str = Field(
        default="",
        description=(
            "Who has authority to decide at this step, when a decision is "
            "made. Empty or vague is reported by rule HW-004 as blocking — "
            "an unclear decision owner is the most common cause of workflow "
            "stalls."
        ),
    )
    next_steps: list[str] = Field(
        default_factory=list,
        description=(
            "Step ids that may follow this one. Empty means this step is "
            "terminal — intentional for the final step, an accidental dead "
            "end anywhere else (rule HW-007)."
        ),
    )
    exception_paths: list[ExceptionPath] = Field(
        default_factory=list,
        description="What happens when this step's declared failure modes occur.",
    )
    characteristics: StepCharacteristics = Field(
        default_factory=StepCharacteristics,
        description=(
            "Observable properties that determine safe human/AI cooperation. "
            "Read by cooperation assessment; unknown values resolve toward "
            "human control."
        ),
    )
    notes: str = Field(
        default="", description="Anything else the observer recorded."
    )


class ApprovalGate(BaseModel):
    """A point where someone must approve before work continues.

    Gates are declared explicitly rather than inferred, because a gate whose
    rejection path nobody defined is a place where work silently dies —
    reported by rule HW-015.
    """

    model_config = STRICT

    gate_id: str = Field(pattern=SLUG, description="Stable identifier for this gate.")
    at_step: str = Field(description="Step id this gate guards.")
    approver: str = Field(
        default="",
        description="Who decides at this gate. Empty is reported by rule HW-004.",
    )
    criteria: str = Field(
        default="",
        description=(
            "What the approver checks. Empty or vague ('looks good') is "
            "reported by rule HW-014."
        ),
    )
    on_approve: Optional[str] = Field(
        default=None,
        description="Step id work moves to when approved. None means the workflow completes.",
    )
    on_reject: str = Field(
        default="",
        description=(
            "What happens on rejection — a step id or a stated action. Empty "
            "is reported by rule HW-015 as blocking: a gate with no rejection "
            "path is a dead end wearing a checkpoint's clothes."
        ),
    )


class SourceEvidence(BaseModel):
    """Where an observation came from, so a claim can be checked."""

    model_config = STRICT

    kind: str = Field(
        description="Type of evidence (interview, recording, document, observation, ...)."
    )
    reference: str = Field(
        description="Pointer to the evidence — a path, a date, a person, a link."
    )
    note: str = Field(default="", description="What this evidence established.")


# --------------------------------------------------------------------- drafts


class HumanWorkflowDraft(BaseModel):
    """A workflow captured as it actually happens, gaps included.

    This model is permissive on purpose. Validation produces findings; it
    never blocks capture. A draft that cannot be saved because it is
    incomplete would defeat the entire premise — human workflow truth comes
    first, and truth is usually incomplete when you first write it down.
    """

    model_config = STRICT

    schema_version: str = Field(
        default=SCHEMA_VERSION,
        description="Contract version this draft was written against (ADR-002).",
    )
    workflow_id: str = Field(
        pattern=SLUG, description="Unique slug identifying this workflow."
    )
    name: str = Field(description="Human-readable name of the workflow.")
    version: str = Field(
        default="1",
        description="Revision of this draft, bumped by whoever edits it.",
    )
    maturity: WorkflowMaturity = Field(
        default=WorkflowMaturity.OBSERVED,
        description="How far this workflow has progressed. Drafts start OBSERVED.",
    )
    purpose: str = Field(
        default="", description="Why this workflow exists, in plain language."
    )
    trigger: str = Field(
        default="",
        description=(
            "What starts the workflow. Empty is reported by rule HW-001 as "
            "blocking — a workflow nobody can say how it starts cannot be run."
        ),
    )
    claimed_outcome: str = Field(
        default="",
        description=(
            "What the workflow is supposed to achieve, as claimed by the "
            "people who run it. Empty is reported by rule HW-002."
        ),
    )
    actors: list[str] = Field(
        default_factory=list,
        description="People, roles, and teams involved.",
    )
    systems: list[str] = Field(
        default_factory=list, description="Tools and systems the work passes through."
    )
    artifacts: list[str] = Field(
        default_factory=list, description="Documents and files the work produces or uses."
    )
    steps: list[WorkflowStep] = Field(
        default_factory=list,
        description="The observed steps. The first step is the entry point.",
    )
    gates: list[ApprovalGate] = Field(
        default_factory=list, description="Observed approval or review gates."
    )
    observed_exceptions: list[str] = Field(
        default_factory=list,
        description=(
            "Failure modes seen in practice. A failure listed here with no "
            "matching exception path is reported by rule HW-011."
        ),
    )
    unwritten_rules: list[str] = Field(
        default_factory=list,
        description=(
            "Things people know but nobody documented. Recording these is "
            "success, not failure — rule HW-013 flags them non-blocking so "
            "they are visible without punishing honesty."
        ),
    )
    known_pain_points: list[str] = Field(
        default_factory=list,
        description="Where the workflow hurts today, in the operators' own words.",
    )
    source_evidence: list[SourceEvidence] = Field(
        default_factory=list,
        description="Where these observations came from.",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this draft was first captured (UTC).",
    )
    notes: str = Field(default="", description="Anything else worth recording.")

    def step(self, step_id: str) -> WorkflowStep:
        """Look up a step by id. Raises KeyError for unknown ids."""
        for s in self.steps:
            if s.step_id == step_id:
                return s
        raise KeyError(f"no step '{step_id}' in workflow '{self.workflow_id}'")

    def step_ids(self) -> set[str]:
        """Every declared step id, for reference checking."""
        return {s.step_id for s in self.steps}

    @property
    def entry_step(self) -> Optional[WorkflowStep]:
        """The first declared step, or None for an empty draft."""
        return self.steps[0] if self.steps else None


# ------------------------------------------------------------ promoted artifact


class PromotionLineage(BaseModel):
    """Where a promoted artifact came from, so promotion is traceable.

    Promotion produces a new artifact rather than mutating the draft
    invisibly, and this records the link plus the exact rule and schema
    versions the decision was made under.
    """

    model_config = STRICT

    source_workflow_id: str = Field(description="Workflow the promotion came from.")
    source_version: str = Field(
        default="", description="Version of the source draft at promotion time."
    )
    from_maturity: WorkflowMaturity = Field(description="Maturity before promotion.")
    to_maturity: WorkflowMaturity = Field(description="Maturity after promotion.")
    promoted_by: str = Field(
        description="Who performed the promotion (self-attested; see RiskAcceptanceRef)."
    )
    promoted_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the promotion happened (UTC).",
    )
    rule_set_version: str = Field(
        default="1",
        description="Version of the validator rule set evaluated for this promotion.",
    )
    schema_version: str = Field(
        default=SCHEMA_VERSION,
        description="Contract version the promoted artifact was written against.",
    )


class AccountableWorkflow(BaseModel):
    """A workflow whose accountability gaps are closed or consciously accepted.

    Deliberately **not** a second ``WorkflowBrief`` (architecture review D3):
    it reuses ``WorkflowStep`` and declares no states or transitions. The
    flattening into the runtime's brief format happens only at export, after
    cooperation assessment has read the per-step attributes it needs.

    What §5.4 calls "states" is the step graph itself — each step is a state
    the work can be in; "handoffs", "exceptions", and "evidence requirements"
    live on the steps that own them.
    """

    model_config = STRICT

    schema_version: str = Field(
        default=SCHEMA_VERSION,
        description="Contract version this artifact was written against (ADR-002).",
    )
    workflow_id: str = Field(
        pattern=SLUG, description="Unique slug identifying this workflow."
    )
    name: str = Field(description="Human-readable name of the workflow.")
    version: str = Field(default="1", description="Revision of this promoted artifact.")
    maturity: WorkflowMaturity = Field(
        default=WorkflowMaturity.ACCOUNTABLE,
        description="Maturity of this artifact. At minimum ACCOUNTABLE.",
    )
    purpose: str = Field(description="Why this workflow exists.")
    trigger: str = Field(
        min_length=1,
        description="What starts the workflow. Required here — HW-001 must be resolved to promote.",
    )
    owners: list[str] = Field(
        min_length=1,
        description=(
            "Everyone accountable for part of this workflow. At least one "
            "owner is required: an accountable workflow with no owner is a "
            "contradiction."
        ),
    )
    steps: list[WorkflowStep] = Field(
        min_length=1,
        description="The workflow's steps, carried forward from the draft unchanged in shape.",
    )
    gates: list[ApprovalGate] = Field(
        default_factory=list, description="Explicit approval and review gates."
    )
    completion_contract: str = Field(
        min_length=1,
        description=(
            "Plain-language definition of done, with criteria. Required — "
            "HW-002 and HW-016 must be resolved to promote."
        ),
    )
    exception_policy: str = Field(
        default="",
        description="What to do when something happens that no exception path covers.",
    )
    accepted_risks: list[RiskAcceptance] = Field(
        default_factory=list,
        description=(
            "Non-blocking findings a human consciously accepted, carried onto "
            "the promoted artifact so the residual risk travels with the "
            "workflow rather than living only in a report."
        ),
    )
    lineage: PromotionLineage = Field(
        description="Where this artifact came from and under which rule/schema versions."
    )
    notes: str = Field(default="", description="Anything else worth recording.")

    def step(self, step_id: str) -> WorkflowStep:
        """Look up a step by id. Raises KeyError for unknown ids."""
        for s in self.steps:
            if s.step_id == step_id:
                return s
        raise KeyError(f"no step '{step_id}' in workflow '{self.workflow_id}'")

    def step_ids(self) -> set[str]:
        """Every declared step id, for reference checking."""
        return {s.step_id for s in self.steps}
