# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Workflow Brief schema.

A WorkflowBrief is the governance artifact for a workflow: it declares the
states a piece of work can be in, who owns each transition between states,
and what evidence must exist before a transition is allowed to happen.

Briefs are written in YAML by humans and validated here. If a rule about how
a workflow behaves can live in this schema instead of in runtime code, it
belongs here — schemas can be edited by non-developers, runtime logic cannot.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from src.schemas.agent_spec import AgentSpec


class BriefStatus(str, Enum):
    """Review status of the brief itself.

    DRAFT    — being written; runnable for exploration, not buildable.
    REVIEWED — a human has read it; still not buildable.
    APPROVED — signed off; agent packages may be generated from it.
    """

    DRAFT = "draft"
    REVIEWED = "reviewed"
    APPROVED = "approved"


class TaskDepth(str, Enum):
    """How much human judgment a decision requires.

    ROUTINE   — the decision has been made enough times to become a default.
                Safe to automate.
    GUIDED    — the decision needs a consistent frame but not a rigid rule.
                A human confirms the output.
    CONSCIOUS — the decision involves taste, ethics, responsibility, or
                meaning. A human owns it entirely; execution pauses at a
                review gate.
    """

    ROUTINE = "ROUTINE"
    GUIDED = "GUIDED"
    CONSCIOUS = "CONSCIOUS"


class Transition(BaseModel):
    """One allowed movement between two states in a workflow.

    A transition that is not listed in the brief does not exist: attempting
    it at runtime is a non-conformance, not an error to be worked around.
    """

    from_state: str = Field(
        description="The state the work must currently be in for this transition to apply."
    )
    to_state: str = Field(
        description="The state the work moves to when this transition completes."
    )
    owner: str = Field(
        description=(
            "Who is responsible for this transition — a human name or an "
            "agent identifier. Owners are plain strings defined in the brief, "
            "never hardcoded in the runtime."
        )
    )
    evidence_required: str = Field(
        default="",
        description=(
            "Plain-language description of the evidence that must be produced "
            "before this transition is allowed (e.g. 'final filename and "
            "destination path'). Empty string means no evidence is required."
        ),
    )
    depth: Optional[TaskDepth] = Field(
        default=None,
        description=(
            "Task depth for this specific transition. If omitted, the "
            "workflow's overall task_depth applies. Set to CONSCIOUS to force "
            "a human review gate on this transition regardless of the "
            "workflow default. This lives in the schema — not the runtime — "
            "so a non-developer can add or remove a review gate by editing "
            "the brief YAML."
        ),
    )


class WorkflowBrief(BaseModel):
    """The complete declaration of a governed workflow.

    Loaded from a YAML file. Validation here guarantees the runtime never
    sees a brief whose transitions reference undeclared states.
    """

    id: str = Field(
        pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$",
        description="Unique slug identifying this workflow (lowercase, hyphen-separated).",
    )
    title: str = Field(description="Human-readable name of the workflow.")
    owner: str = Field(description="The human responsible for this workflow as a whole.")
    task_depth: TaskDepth = Field(
        description=(
            "Default task depth for every transition in this workflow. "
            "Individual transitions may override it with their own depth."
        )
    )
    initial_state: str = Field(
        description="The state a new process capsule starts in. Must appear in states."
    )
    states: list[str] = Field(
        min_length=1,
        description="Every valid state name in this workflow. Transitions may only reference these.",
    )
    transitions: list[Transition] = Field(
        description="Every allowed state-to-state movement. Anything not listed here is a non-conformance."
    )
    completion_criteria: str = Field(
        description="Plain-language definition of done for this workflow."
    )
    exception_path: str = Field(
        description=(
            "What happens when no transition matches — the human-readable "
            "escalation instruction shown when work hits a dead end."
        )
    )
    status: BriefStatus = Field(
        default=BriefStatus.DRAFT,
        description=(
            "Review status of this brief. Agent packages can only be "
            "generated from an approved brief."
        ),
    )
    agents: list[AgentSpec] = Field(
        default_factory=list,
        description=(
            "The agents this workflow needs, with their depth levels and "
            "escalation targets. Transition owners not declared here are "
            "treated as humans. Empty is valid for human-only workflows."
        ),
    )

    @model_validator(mode="after")
    def _check_states_are_consistent(self) -> "WorkflowBrief":
        """Reject briefs whose initial state or transitions reference unknown states."""
        known = set(self.states)
        if self.initial_state not in known:
            raise ValueError(
                f"initial_state '{self.initial_state}' is not in states {sorted(known)}"
            )
        for t in self.transitions:
            for endpoint in (t.from_state, t.to_state):
                if endpoint not in known:
                    raise ValueError(
                        f"transition {t.from_state} -> {t.to_state} references "
                        f"unknown state '{endpoint}'"
                    )
        if len(known) != len(self.states):
            raise ValueError("states list contains duplicates")
        return self

    @model_validator(mode="after")
    def _check_agents_are_consistent(self) -> "WorkflowBrief":
        """Enforce agent-related doctrine at validation time.

        * Agent names must be unique.
        * A CONSCIOUS-depth transition cannot be owned by a declared agent —
          CONSCIOUS decisions involve taste, ethics, responsibility, or
          meaning, and a human owns them entirely.
        * A ROUTINE workflow cannot depend on a Level 5 agent (doctrine:
          routine execution never needs a strategist).
        """
        names = [a.agent_name for a in self.agents]
        if len(names) != len(set(names)):
            raise ValueError("agents list contains duplicate agent_name entries")
        agent_names = set(names)
        for t in self.transitions:
            if t.owner in agent_names and self.depth_of(t) is TaskDepth.CONSCIOUS:
                raise ValueError(
                    f"transition {t.from_state} -> {t.to_state} is CONSCIOUS-depth "
                    f"but owned by agent '{t.owner}' — CONSCIOUS decisions must be "
                    f"owned by a human"
                )
        if self.task_depth is TaskDepth.ROUTINE:
            for a in self.agents:
                if a.depth_level == 5:
                    raise ValueError(
                        f"agent '{a.agent_name}' is Level 5 but the workflow is "
                        f"ROUTINE — routine execution cannot depend on a strategist"
                    )
        return self

    def agent_spec(self, owner: str) -> Optional[AgentSpec]:
        """Return the AgentSpec for an owner string, or None if the owner is human."""
        return next((a for a in self.agents if a.agent_name == owner), None)

    def transitions_from(self, state: str) -> list[Transition]:
        """Return every transition whose from_state matches the given state."""
        return [t for t in self.transitions if t.from_state == state]

    def depth_of(self, transition: Transition) -> TaskDepth:
        """Resolve the effective task depth of a transition.

        A transition's own depth wins; otherwise the workflow default applies.
        """
        return transition.depth if transition.depth is not None else self.task_depth
