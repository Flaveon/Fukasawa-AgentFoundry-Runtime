# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Cooperation contracts — who does each step, and under what supervision.

The third lifecycle stage:

    Validated Accountable Workflow  ->  Cooperative Human-AI Workflow

A ``CooperationAssessment`` answers one question about one step: what is the
most appropriate executor, given how much judgment the step needs, how
repeatable and deterministic it is, how risky and reversible its effect is,
and how sensitive its data is. The answer is produced by a **published
decision table** in ``src/governance/cooperation.py`` — never by a model.
A human can therefore predict the recommendation before running it, which is
what makes a classification explainable rather than merely automatic.

A ``CooperativeWorkflow`` is the approved result: every step assigned, with a
human owner, an escalation target, bounded tools, and a fallback.

The safety rule this module exists to make enforceable:

    **Overrides are one-directional.** A human may always move work toward
    human control. A human may not move a step that hit a safety floor toward
    greater autonomy.

``ExecutorClass.autonomy_rank`` exists to make that rule checkable in code
rather than trusted to convention: comparing ranks is how the engine and its
tests prove an override did not quietly increase autonomy on a floored step.
This mirrors doctrine the runtime already enforces elsewhere — a
CONSCIOUS-depth transition cannot be owned by an agent
(``WorkflowBrief._check_agents_are_consistent``).
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.schemas.human_workflow import SCHEMA_VERSION, SLUG, StepCharacteristics

#: Shared model config: reject unknown fields so typos surface loudly.
STRICT = ConfigDict(extra="forbid")


class ExecutorClass(str, Enum):
    """Who executes a step, and how much human control surrounds it.

    All seven values ship in the first release even though the desktop UI
    emphasizes a subset, because these strings are persisted in the ledger and
    exported into YAML — adding a value later must never be a breaking change.

    HUMAN_ONLY                      — a person does it; no AI in the loop.
    HUMAN_LED_AI_ASSISTED           — a person does it, AI helps.
    AGENT_PREPARED_HUMAN_APPROVED   — an agent prepares, a human authorizes.
    AGENT_EXECUTED_HUMAN_SUPERVISED — an agent acts, a human watches.
    DETERMINISTIC_AUTOMATION        — a rule or script; no reasoning needed.
    BOUNDED_AUTONOMOUS_AGENT        — an agent acts within stated bounds.
    NOT_READY_FOR_AUTOMATION        — nothing is assigned until the step is
                                      better understood. The honest answer
                                      when the facts are unknown.
    """

    HUMAN_ONLY = "HUMAN_ONLY"
    HUMAN_LED_AI_ASSISTED = "HUMAN_LED_AI_ASSISTED"
    AGENT_PREPARED_HUMAN_APPROVED = "AGENT_PREPARED_HUMAN_APPROVED"
    AGENT_EXECUTED_HUMAN_SUPERVISED = "AGENT_EXECUTED_HUMAN_SUPERVISED"
    DETERMINISTIC_AUTOMATION = "DETERMINISTIC_AUTOMATION"
    BOUNDED_AUTONOMOUS_AGENT = "BOUNDED_AUTONOMOUS_AGENT"
    NOT_READY_FOR_AUTOMATION = "NOT_READY_FOR_AUTOMATION"

    @property
    def autonomy_rank(self) -> int:
        """How much unsupervised latitude this class grants, low to high.

        Used to enforce that an override never increases autonomy on a step
        that hit a safety floor. Two values sit deliberately outside the
        obvious ordering:

        * ``NOT_READY_FOR_AUTOMATION`` ranks 0 — less autonomy than
          HUMAN_ONLY, because nothing is assigned at all.
        * ``DETERMINISTIC_AUTOMATION`` ranks below the supervised-agent class:
          a script that always does the same thing has no latitude to misjudge,
          so it is *safer* than an agent acting under observation, even though
          no human touches it. Ranking it by "how little a human is involved"
          rather than "how much judgment is delegated" would be the wrong axis.
        """
        return {
            ExecutorClass.NOT_READY_FOR_AUTOMATION: 0,
            ExecutorClass.HUMAN_ONLY: 1,
            ExecutorClass.HUMAN_LED_AI_ASSISTED: 2,
            ExecutorClass.AGENT_PREPARED_HUMAN_APPROVED: 3,
            ExecutorClass.DETERMINISTIC_AUTOMATION: 4,
            ExecutorClass.AGENT_EXECUTED_HUMAN_SUPERVISED: 5,
            ExecutorClass.BOUNDED_AUTONOMOUS_AGENT: 6,
        }[self]

    @property
    def requires_human_authorization(self) -> bool:
        """Whether a human must authorize each execution before it takes effect."""
        return self in (
            ExecutorClass.HUMAN_ONLY,
            ExecutorClass.HUMAN_LED_AI_ASSISTED,
            ExecutorClass.AGENT_PREPARED_HUMAN_APPROVED,
        )

    @property
    def involves_agent(self) -> bool:
        """Whether an AI agent participates at all, in any capacity."""
        return self in (
            ExecutorClass.HUMAN_LED_AI_ASSISTED,
            ExecutorClass.AGENT_PREPARED_HUMAN_APPROVED,
            ExecutorClass.AGENT_EXECUTED_HUMAN_SUPERVISED,
            ExecutorClass.BOUNDED_AUTONOMOUS_AGENT,
        )


class SupervisionMode(str, Enum):
    """How closely a human watches the work.

    NONE                    — no routine human observation (scripts only).
    SPOT_CHECK              — sampled review after the fact.
    EVERY_OUTPUT_REVIEWED   — a human reads every result.
    APPROVAL_REQUIRED       — nothing takes effect until a human approves.
    """

    NONE = "NONE"
    SPOT_CHECK = "SPOT_CHECK"
    EVERY_OUTPUT_REVIEWED = "EVERY_OUTPUT_REVIEWED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"


class AutomationReadiness(str, Enum):
    """Whether this step is ready to be automated at all, today.

    Separate from the executor class because a step can be *suitable* for
    automation in principle while lacking the evidence, tooling, or examples
    to do it safely yet — the same evidence-before-capability doctrine the
    agent maturity model already uses.
    """

    NOT_READY = "NOT_READY"
    PILOT = "PILOT"
    READY = "READY"


class SafetyFloor(str, Enum):
    """Why a recommendation was forced toward human control.

    Recorded on the assessment so an operator can see *which* fact caused the
    floor, not merely that one applied. A floored step cannot be overridden
    toward greater autonomy.

    NONE                  — no floor applied; the decision table decided freely.
    IRREVERSIBLE          — the effect cannot be undone.
    HIGH_RISK             — a wrong outcome causes serious damage.
    SENSITIVE_DATA        — the step handles sensitive data.
    UNDEFINED_AUTHORITY   — nobody has said who decides here.
    UNKNOWN_CHARACTERISTICS — the step has not been characterized enough to judge.
    """

    NONE = "NONE"
    IRREVERSIBLE = "IRREVERSIBLE"
    HIGH_RISK = "HIGH_RISK"
    SENSITIVE_DATA = "SENSITIVE_DATA"
    UNDEFINED_AUTHORITY = "UNDEFINED_AUTHORITY"
    UNKNOWN_CHARACTERISTICS = "UNKNOWN_CHARACTERISTICS"


class ExecutorOverride(BaseModel):
    """A human changing the recommended executor class, on the record.

    Rationale is mandatory: an override without a reason is indistinguishable
    from a mis-click, and this decision governs who is allowed to act
    unsupervised. Attribution is self-attested (no authentication exists in
    this runtime) — the same ceiling documented on ``RiskAcceptance``.
    """

    model_config = STRICT

    overridden_to: ExecutorClass = Field(
        description="The executor class the human chose instead."
    )
    rationale: str = Field(
        min_length=1,
        description="Why the recommendation was wrong for this step. Required.",
    )
    actor: str = Field(
        min_length=1, description="Who made the override (self-attested)."
    )
    at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the override was made (UTC).",
    )


class CooperationAssessment(BaseModel):
    """Per-step analysis of appropriate human/AI cooperation.

    The assessed factors are echoed from the step's declared characteristics
    rather than referenced by pointer, so a stored assessment remains
    auditable even if the workflow is later edited — you can always see what
    the recommendation was actually based on.
    """

    model_config = STRICT

    schema_version: str = Field(
        default=SCHEMA_VERSION,
        description="Contract version this assessment was written against (ADR-002).",
    )
    assessment_id: str = Field(description="Unique id for this assessment.")
    workflow_id: str = Field(description="Workflow the assessed step belongs to.")
    step_id: str = Field(description="Step being assessed.")
    recommended_executor: ExecutorClass = Field(
        description="What the decision table recommends for this step."
    )
    rationale: str = Field(
        min_length=1,
        description=(
            "Why this class was recommended, stated deterministically in terms "
            "of the assessed factors. Same facts must always yield the same text."
        ),
    )
    assessed_factors: StepCharacteristics = Field(
        description="The step characteristics this recommendation was computed from."
    )
    safety_floor: SafetyFloor = Field(
        default=SafetyFloor.NONE,
        description=(
            "Which safety floor forced the recommendation toward human "
            "control, if any. Anything other than NONE means overrides toward "
            "greater autonomy are refused."
        ),
    )
    required_tools: list[str] = Field(
        default_factory=list,
        description="Tools an executor would need to perform this step.",
    )
    supervision_mode: SupervisionMode = Field(
        description="How closely a human must watch this step's execution."
    )
    automation_readiness: AutomationReadiness = Field(
        description="Whether this step is ready to be automated today."
    )
    override: Optional[ExecutorOverride] = Field(
        default=None,
        description="Set when a human replaced the recommendation with their own judgment.",
    )
    assessed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the assessment was computed (UTC).",
    )

    @property
    def effective_executor(self) -> ExecutorClass:
        """The class that actually governs this step — override wins if present."""
        return self.override.overridden_to if self.override else self.recommended_executor

    @property
    def is_floored(self) -> bool:
        """Whether a safety floor constrains what this step may be overridden to."""
        return self.safety_floor is not SafetyFloor.NONE


class StepAssignment(BaseModel):
    """The approved assignment of one step to one executor.

    Everything an executor is permitted and forbidden to do is stated here
    explicitly rather than inherited implicitly, because these fields become
    the generated agent package's contract and permissions.
    """

    model_config = STRICT

    step_id: str = Field(description="Step being assigned.")
    executor_class: ExecutorClass = Field(
        description="Approved executor class for this step."
    )
    executor_identity: str = Field(
        default="",
        description=(
            "Who or what performs it — a person, a named agent, or a script. "
            "Empty for NOT_READY_FOR_AUTOMATION steps."
        ),
    )
    human_owner: str = Field(
        min_length=1,
        description=(
            "The human accountable for this step's outcome. Required for every "
            "assignment, including fully automated ones — automation moves the "
            "work, never the accountability."
        ),
    )
    approval_gate: str = Field(
        default="",
        description=(
            "Gate id that must approve before this step takes effect. Required "
            "for BOUNDED_AUTONOMOUS_AGENT; the builder enforces that."
        ),
    )
    escalation_target: str = Field(
        min_length=1,
        description="Who the executor escalates to when blocked or uncertain.",
    )
    allowed_tools: list[str] = Field(
        default_factory=list,
        description="Tools this executor may use. Anything absent is forbidden.",
    )
    prohibited_actions: list[str] = Field(
        default_factory=list,
        description="Actions this executor must never take, stated explicitly.",
    )
    evidence_output: str = Field(
        default="",
        description=(
            "What this step must produce to prove it happened. Carried into "
            "the exported brief as the transition's evidence requirement."
        ),
    )
    fallback_executor: ExecutorClass = Field(
        default=ExecutorClass.HUMAN_ONLY,
        description=(
            "Who takes over when the assigned executor cannot proceed. "
            "Defaults to HUMAN_ONLY — falling back toward a human is always safe."
        ),
    )
    runtime_requirements: list[str] = Field(
        default_factory=list,
        description="What must be available at runtime for this step to execute.",
    )


class CooperativeWorkflow(BaseModel):
    """An approved human-AI assignment of a whole workflow.

    This is the last artifact before export. Approval is a human act and is
    recorded on the artifact: nothing reaches the Agent Foundry path without a
    named person having approved the executor assignments.
    """

    model_config = STRICT

    schema_version: str = Field(
        default=SCHEMA_VERSION,
        description="Contract version this artifact was written against (ADR-002).",
    )
    workflow_id: str = Field(
        pattern=SLUG, description="Workflow these assignments belong to."
    )
    name: str = Field(description="Human-readable name of the workflow.")
    version: str = Field(default="1", description="Revision of this artifact.")
    source_workflow_version: str = Field(
        default="",
        description="Version of the accountable workflow these assignments were built from.",
    )
    assignments: list[StepAssignment] = Field(
        min_length=1,
        description="One assignment per executable step. Every step must be assigned.",
    )
    assessment_ids: list[str] = Field(
        default_factory=list,
        description="The assessments these assignments were derived from, for traceability.",
    )
    required_agent_packages: list[str] = Field(
        default_factory=list,
        description="Agent packages that must be generated for this workflow to run.",
    )
    deployment_constraints: list[str] = Field(
        default_factory=list,
        description="Conditions that must hold before any of this is deployed.",
    )
    approved_by: str = Field(
        default="",
        description=(
            "Human who approved these assignments (self-attested). Empty means "
            "not yet approved; promotion to COOPERATIVE_DESIGN_APPROVED requires it."
        ),
    )
    approved_at: Optional[datetime] = Field(
        default=None, description="When the assignments were approved (UTC)."
    )
    notes: str = Field(default="", description="Anything else worth recording.")

    def assignment(self, step_id: str) -> StepAssignment:
        """Look up a step's assignment. Raises KeyError for unassigned steps."""
        for a in self.assignments:
            if a.step_id == step_id:
                return a
        raise KeyError(f"step '{step_id}' has no assignment in '{self.workflow_id}'")

    @property
    def approved(self) -> bool:
        """Whether a named human has approved these assignments."""
        return bool(self.approved_by.strip())

    @property
    def agent_assigned_steps(self) -> list[StepAssignment]:
        """Assignments where an AI agent participates in any capacity."""
        return [a for a in self.assignments if a.executor_class.involves_agent]
