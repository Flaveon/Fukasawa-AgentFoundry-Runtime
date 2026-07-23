# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Workflow Graph schemas — the orchestration kernel's contract layer.

A GraphSpec is a small, YAML-editable state graph laid over a workflow
brief: each node does one piece of work (through an adapter, or by pausing
for a human) and may advance the workflow's capsule through one of the
brief's declared transitions. The graph never invents movement — every
capsule advance still goes through the same state machine, ledger, and
non-conformance machinery as a manual run.

GraphRunState is the kernel's checkpoint: persisted after every node so a
graph run survives process death and resumes exactly where it stopped.
The graph stays inspectable as plain data — no framework UI required.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from src.schemas.workflow_brief import WorkflowBrief


class NodeKind(str, Enum):
    """What a node is.

    DETERMINISTIC — rule work through an adapter; same input, same output.
    AGENT         — reasoning work delegated through an adapter.
    HUMAN_GATE    — execution pauses; a human decides APPROVE/REJECT/FLAG.
    """

    DETERMINISTIC = "deterministic"
    AGENT = "agent"
    HUMAN_GATE = "human_gate"


class RetryPolicy(BaseModel):
    """How many times a failing node is retried before the run blocks."""

    max_attempts: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Total attempts allowed (1 = no retry). After the last failure the run blocks.",
    )


class ProducesTransition(BaseModel):
    """The workflow transition a successful node performs."""

    to_state: str = Field(
        description="Target state from the brief. The transition must exist from the capsule's current state."
    )
    evidence_template: str = Field(
        default="",
        description=(
            "Template for the transition evidence. May reference adapter "
            "outputs as {output_name}. Empty means: use the adapter's own "
            "evidence string."
        ),
    )


class GraphNode(BaseModel):
    """One unit of orchestrated work."""

    node_id: str = Field(
        pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$",
        description="Slug identifying this node within the graph.",
    )
    kind: NodeKind = Field(description="deterministic, agent, or human_gate.")
    adapter: str = Field(
        default="",
        description="Adapter name for deterministic/agent nodes (e.g. 'filesystem', 'shell'). Empty for human gates.",
    )
    params: dict = Field(
        default_factory=dict,
        description=(
            "Adapter parameters. String values may contain {variable} "
            "placeholders resolved from the run's variables."
        ),
    )
    produces_transition: Optional[ProducesTransition] = Field(
        default=None,
        description="The capsule transition this node performs on success, if any.",
    )
    retry: RetryPolicy = Field(
        default_factory=RetryPolicy,
        description="Retry policy for adapter failures. Human gates never retry.",
    )
    next: Optional[str] = Field(
        default=None,
        description="node_id executed after this one succeeds. None ends the graph.",
    )
    gate_reason: str = Field(
        default="",
        description="Human gates: why a human must decide here. Required for human_gate nodes.",
    )

    @model_validator(mode="after")
    def _check_kind_requirements(self) -> "GraphNode":
        """Adapters for working nodes, reasons for gates — no silent defaults."""
        if self.kind is NodeKind.HUMAN_GATE:
            if not self.gate_reason.strip():
                raise ValueError(
                    f"human_gate node '{self.node_id}' must state gate_reason — "
                    f"a pause nobody can explain is a stall, not a gate"
                )
            if self.adapter:
                raise ValueError(
                    f"human_gate node '{self.node_id}' cannot have an adapter — "
                    f"the human is not a tool to call"
                )
        else:
            if not self.adapter:
                raise ValueError(
                    f"{self.kind.value} node '{self.node_id}' must name an adapter"
                )
        return self


class GraphSpec(BaseModel):
    """A complete workflow graph, loaded from YAML."""

    graph_id: str = Field(
        pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$",
        description="Unique slug for this graph.",
    )
    workflow: str = Field(
        description="Id of the WorkflowBrief this graph orchestrates."
    )
    description: str = Field(
        default="", description="What this graph automates, in plain language."
    )
    nodes: list[GraphNode] = Field(
        min_length=1,
        description="Execution starts at the first node and follows 'next' links.",
    )

    @model_validator(mode="after")
    def _check_graph_shape(self) -> "GraphSpec":
        """Node ids unique; every next-reference resolves; no self-loops."""
        ids = [n.node_id for n in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("graph contains duplicate node_id entries")
        known = set(ids)
        for n in self.nodes:
            if n.next is not None and n.next not in known:
                raise ValueError(
                    f"node '{n.node_id}' points to unknown next node '{n.next}'"
                )
            if n.next == n.node_id:
                raise ValueError(f"node '{n.node_id}' points at itself")
        return self

    @property
    def entry_node(self) -> GraphNode:
        """Execution starts at the first declared node."""
        return self.nodes[0]

    def node(self, node_id: str) -> GraphNode:
        """Look up a node by id. Raises KeyError for unknown ids."""
        for n in self.nodes:
            if n.node_id == node_id:
                return n
        raise KeyError(f"no node '{node_id}' in graph '{self.graph_id}'")

    def validate_against_brief(self, brief: WorkflowBrief) -> list[str]:
        """Cross-check the graph against the brief it claims to orchestrate.

        Returns findings (empty = consistent). Walks the linear path from the
        entry node, tracking the capsule state each transition-producing node
        would leave it in, and verifies every produced transition exists in
        the brief at that point.
        """
        findings: list[str] = []
        if self.workflow != brief.id:
            findings.append(
                f"graph orchestrates '{self.workflow}' but brief is '{brief.id}'"
            )
            return findings
        state = brief.initial_state
        node: Optional[GraphNode] = self.entry_node
        visited: set[str] = set()
        while node is not None and node.node_id not in visited:
            visited.add(node.node_id)
            if node.produces_transition is not None:
                target = node.produces_transition.to_state
                valid = [t.to_state for t in brief.transitions_from(state)]
                if target not in valid:
                    findings.append(
                        f"node '{node.node_id}' produces transition "
                        f"{state} -> {target}, but the brief only allows "
                        f"{state} -> {valid or 'nothing'}"
                    )
                state = target
            node = self.node(node.next) if node.next else None
        return findings


class GraphRunStatus(str, Enum):
    """Where a graph run stands."""

    RUNNING = "running"
    PAUSED_HUMAN = "paused_human"
    BLOCKED = "blocked"
    COMPLETE = "complete"
    FAILED = "failed"


class NodeExecution(BaseModel):
    """One attempt at one node — the kernel's trace unit."""

    node_id: str = Field(description="The node that ran.")
    attempt: int = Field(ge=1, description="1-based attempt number.")
    ok: bool = Field(description="Whether the attempt succeeded.")
    evidence: str = Field(default="", description="What the attempt produced or observed.")
    note: str = Field(default="", description="Failure detail or gate decision.")
    executed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the attempt finished (UTC).",
    )


class GraphRunState(BaseModel):
    """The kernel's durable checkpoint, saved after every node execution."""

    graph_run_id: str = Field(description="Unique id for this graph run.")
    graph_id: str = Field(description="The GraphSpec being executed.")
    workflow_id: str = Field(description="The workflow brief being advanced.")
    run_id: str = Field(
        description="The underlying workflow run (RuntimeState) this graph drives."
    )
    capsule_id: str = Field(description="The capsule being advanced.")
    graph_hash: str = Field(
        default="",
        description=(
            "SHA-256 of the graph spec at run start. Pinned so a resume "
            "cannot silently continue under a different graph than the one "
            "the run began with."
        ),
    )
    status: GraphRunStatus = Field(default=GraphRunStatus.RUNNING)
    current_node: str = Field(
        description="The node to execute next (or the gate currently pausing the run)."
    )
    attempts_on_current: int = Field(
        default=0,
        ge=0,
        description="Failed attempts already spent on the current node.",
    )
    variables: dict[str, str] = Field(
        default_factory=dict,
        description="Run variables substituted into node params ({name} placeholders).",
    )
    history: list[NodeExecution] = Field(
        default_factory=list,
        description="Every node attempt, in order — the inspectable trace.",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Touched on every checkpoint.",
    )

    def touch(self) -> None:
        """Update the checkpoint timestamp."""
        self.updated_at = datetime.now(timezone.utc)
