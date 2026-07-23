# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Agent Spec schema — the brief's declaration of the agents it needs.

Phase 2 extends the WorkflowBrief with an ``agents`` section: before Agent
Foundry can generate a package for an owner named in a transition, the brief
must declare who that agent is, how deep it may reason, where it escalates,
and how it deploys. This is the Complexity Gate in schema form — the Agent
Foundry doctrine requires the human to answer "what is the lowest reasoning
level this task actually needs?" before any build proceeds, and the answer
lives here, editable by non-developers.

Source doctrine: agent_foundry_gpt_builder_brief_v_1 (Complexity Gate,
Deployment Method taxonomy) and the Fukasawa Task Depth Framework levels.
"""

from enum import Enum

from pydantic import BaseModel, Field


class DeploymentMethod(str, Enum):
    """The Agent Foundry deployment taxonomy (builder brief, methods 1-10).

    FILE_PACKAGE is the doctrine default: portable, inspectable,
    version-trackable, and promotable to any other method without rewriting
    the agent definition.
    """

    PASTE_INJECT = "paste_inject"
    FILE_PACKAGE = "file_package"
    API_CONFIG = "api_config"
    WORKFLOW_AUTOMATION = "workflow_automation"
    PYTHON_FRAMEWORK = "python_framework"
    REST_API = "rest_api"
    CLI_TOOL = "cli_tool"
    CONTAINER = "container"
    PROTOCOL_EXTENSION = "protocol_extension"
    EVENT_DRIVEN = "event_driven"


class AgentSpec(BaseModel):
    """One agent the workflow needs, declared in the brief.

    Owners in the brief's transitions that are NOT declared here are treated
    as humans. Declaring an agent is what makes it buildable — and what
    subjects it to depth-boundary enforcement.
    """

    agent_name: str = Field(
        pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$",
        description=(
            "Slug identifying this agent (lowercase, hyphen-separated). Must "
            "match the owner string used in the brief's transitions."
        ),
    )
    depth_level: int = Field(
        ge=0,
        le=5,
        description=(
            "Fukasawa Task Depth level: 0 rule task, 1 first-inference, "
            "2 local triage, 3 diagnostic agent, 4 workflow coordinator, "
            "5 strategist (redesign-only — never buildable for execution). "
            "The agent must not reason above this level."
        ),
    )
    responsibilities: str = Field(
        min_length=1,
        description="Plain-language statement of what this agent does — and implicitly, nothing else.",
    )
    escalation_target: str = Field(
        min_length=1,
        description=(
            "Who receives work this agent cannot handle — a human name or "
            "another agent's slug. Required: an agent with nowhere to "
            "escalate will improvise, and improvisation is non-conformance."
        ),
    )
    deployment_method: DeploymentMethod = Field(
        default=DeploymentMethod.FILE_PACKAGE,
        description=(
            "How this agent deploys, from the Agent Foundry taxonomy. "
            "Defaults to file_package per doctrine."
        ),
    )
    allowed_tools: list[str] = Field(
        default_factory=list,
        description="Tools this agent may use. Empty means file I/O within its workspace paths only.",
    )
    forbidden: list[str] = Field(
        default_factory=list,
        description="Behaviors explicitly denied to this agent, recorded in CONTRACT.md.",
    )
