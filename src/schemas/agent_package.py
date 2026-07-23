# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Agent Package schemas — the transfer contract and the package manifest.

Two objects live here:

* ``AgentCapsuleContract`` — the Agent Foundry Process Capsule Standard: the
  YAML transfer contract (``process_capsule.yaml``) every agent package must
  carry before it is considered transferable or promotable. This is a
  *design-time* contract; it is distinct from the runtime's ProcessCapsule,
  which is one *execution instance* moving through a workflow.

* ``AgentPackageManifest`` — the machine-readable summary of a generated
  package: what files it contains, its depth level, maturity, deployment
  method, and workspace profile. This is what ``fukasawa package validate``
  checks a package directory against.

Source doctrine: agent_foundry_gpt_builder_brief_v_1 (Process Capsule
Standard, File Purposes, C-Pax Directory Profile, Deployment Method).
"""

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, model_validator

from src.schemas.agent_spec import DeploymentMethod


class Maturity(str, Enum):
    """Agent maturity ladder. Promotion requires human review and evidence.

    Every generated package starts at DRAFT — the generator is not allowed
    to claim testing that has not happened.
    """

    DRAFT = "draft"
    TESTED = "tested"
    VALIDATED = "validated"


class CapsuleStep(BaseModel):
    """One step in the capsule's procedure."""

    name: str = Field(min_length=1, description="What this step does, stated plainly.")
    depth_level: int = Field(
        ge=0,
        le=5,
        description=(
            "Reasoning depth this step needs. Must not exceed the owning "
            "agent's declared depth_level — that is the boundary the "
            "validator enforces."
        ),
    )
    deterministic: bool = Field(
        description="True if the step is a rule (same input, same output); false if it reasons."
    )
    reasoning_justification: str = Field(
        default="",
        description=(
            "Why reasoning is needed. Required for non-deterministic steps "
            "(spec rule: any non-deterministic step must declare why)."
        ),
    )


class CapsuleInput(BaseModel):
    """One input the capsule's task requires."""

    name: str = Field(min_length=1, description="Input name.")
    type: str = Field(default="", description="Input type or artifact kind.")
    required: bool = Field(default=True, description="Whether the task can start without it.")
    source: str = Field(default="", description="Where this input comes from (path or producer).")


class KnownFailure(BaseModel):
    """One known way this task fails, and what to do about it."""

    failure: str = Field(min_length=1, description="The failure mode.")
    signal: str = Field(default="", description="How the failure announces itself.")
    response: str = Field(default="", description="What the agent should do when it happens.")


class EscalationRule(BaseModel):
    """One condition under which the agent must hand the work up."""

    condition: str = Field(min_length=1, description="When to escalate.")
    target: str = Field(min_length=1, description="Who receives the escalation.")
    requested_checks: str = Field(
        default="", description="What the escalation target should verify."
    )


class CapsuleOutputSchema(BaseModel):
    """The shape every completed run of this capsule must produce.

    The four fields are mandatory per the Process Capsule Standard: a result
    without status, evidence, confidence, and a recommended next step is not
    a handoff, it is a shrug.
    """

    status: str = Field(min_length=1, description="Allowed status values, e.g. 'done | blocked'.")
    evidence: str = Field(min_length=1, description="What evidence the output must include.")
    confidence: str = Field(min_length=1, description="How confidence is expressed.")
    recommended_next_step: str = Field(
        min_length=1, description="What the output must say about what happens next."
    )


class AgentCapsuleContract(BaseModel):
    """The transfer contract for one agent capability (process_capsule.yaml).

    Without this file, no agent may inherit tasks from another — it is the
    precondition for capability lift.
    """

    task_name: str = Field(min_length=1, description="The task this capsule transfers.")
    owner_agent: str = Field(min_length=1, description="Slug of the agent that owns this task.")
    workflow_id: str = Field(
        default="", description="The workflow brief this capsule was generated from."
    )
    maturity: Maturity = Field(
        default=Maturity.DRAFT,
        description="Maturity of this capability. Generated packages always start at draft.",
    )
    depth_level: int = Field(
        ge=0, le=5, description="The owning agent's declared depth level."
    )
    inputs: list[CapsuleInput] = Field(
        min_length=1, description="What the task needs to start."
    )
    steps: list[CapsuleStep] = Field(min_length=1, description="The procedure, in order.")
    known_failures: list[KnownFailure] = Field(
        default_factory=list, description="Failure modes observed or anticipated."
    )
    escalation_rules: list[EscalationRule] = Field(
        min_length=1,
        description="When and to whom the agent escalates. Required for Level 1+ (and harmless for Level 0).",
    )
    output_schema: CapsuleOutputSchema = Field(
        description="The mandatory shape of every completed output."
    )

    @model_validator(mode="after")
    def _check_capsule_rules(self) -> "AgentCapsuleContract":
        """Enforce Process Capsule Standard rules.

        * No step may exceed the agent's declared depth level.
        * Non-deterministic steps must justify why reasoning is needed.
        * A validated maturity claim requires eval evidence — which the
          generator never has, so it cannot be set at generation time.
        """
        for step in self.steps:
            if step.depth_level > self.depth_level:
                raise ValueError(
                    f"step '{step.name}' is depth {step.depth_level} but the "
                    f"agent is declared depth {self.depth_level} — steps cannot "
                    f"reach above the agent's level"
                )
            if not step.deterministic and not step.reasoning_justification.strip():
                raise ValueError(
                    f"step '{step.name}' is non-deterministic but does not "
                    f"declare why reasoning is needed"
                )
        return self


class AgentPackageManifest(BaseModel):
    """Machine-readable summary of one generated agent package (manifest.json)."""

    agent_name: str = Field(description="Slug of the packaged agent.")
    workflow_id: str = Field(description="The workflow brief this package was generated from.")
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the package was generated (UTC).",
    )
    depth_level: int = Field(ge=0, le=5, description="Declared reasoning depth.")
    maturity: Maturity = Field(
        default=Maturity.DRAFT, description="Always draft at generation time."
    )
    owner: str = Field(description="The human responsible for this agent (the brief's owner).")
    escalation_target: str = Field(description="Where this agent escalates.")
    deployment_method: DeploymentMethod = Field(description="How this agent deploys.")
    workspace_profile: str = Field(
        default="generic",
        description="'c-pax' when the target workspace uses numbered directories, else 'generic'.",
    )
    files: list[str] = Field(
        description="Every file in the package, relative to the package root."
    )
