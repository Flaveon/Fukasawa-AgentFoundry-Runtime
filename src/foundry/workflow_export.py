# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Cooperative workflow builder and export to the existing runtime.

The last stage of the lifecycle:

    AccountableWorkflow + CooperationAssessment[]
        -> CooperativeWorkflow        (build: assign every step)
        -> WorkflowBrief              (export: flatten onto the runtime)
        -> generate_packages()        (existing, untouched)

Two rules govern everything in this module, and both are easy to get wrong:

1. **The export reads ``effective_executor``, never ``recommended_executor``.**
   An override is a human's decision about their own workflow, and it is what
   governs. The decision table only proposes.
2. **A safety floor cannot be crossed by exporting.** The classes that require
   a human to authorize each execution export behind a real approval gate, not
   behind a field that records one.

Flattening happens here and nowhere earlier. ``AccountableWorkflow``
deliberately declares no states or transitions: what the runtime calls a state
is the step graph itself, and flattening before assignment would destroy the
per-step attributes the cooperation assessment reads.
"""

from typing import Iterable

from src.schemas.agent_spec import AgentSpec
from src.schemas.cooperation import (
    CooperationAssessment,
    CooperativeWorkflow,
    ExecutorClass,
    StepAssignment,
)
from src.schemas.human_workflow import AccountableWorkflow, WorkflowStep
from src.schemas.workflow_brief import (
    BriefStatus,
    TaskDepth,
    Transition,
    WorkflowBrief,
)


class ExportRefusedError(Exception):
    """Raised when doctrine forbids an export.

    The message always names what to fix, never merely what failed — this is
    read by an operator who did not write the runtime.
    """


# --------------------------------------------------------------- policy tables
#
# ADR-006 section "Export mapping" fixes these. They are published here and in
# docs/cooperation-classification-guide.md so a non-developer can predict an
# export before running it, exactly as they can predict a classification.

#: Task depth each executor class exports to.
#:
#: ADR-006 says AGENT_EXECUTED_HUMAN_SUPERVISED and DETERMINISTIC_AUTOMATION
#: export to "ROUTINE or GUIDED"; the split resolves by definition rather than
#: by preference. GUIDED means "a human confirms the output", which is what
#: EVERY_OUTPUT_REVIEWED supervision already is, so the supervised-agent class
#: is GUIDED. ROUTINE means "safe to automate, no reasoning needed", which is
#: what DETERMINISTIC_AUTOMATION is by definition.
_DEPTH_BY_CLASS: dict[ExecutorClass, TaskDepth] = {
    ExecutorClass.NOT_READY_FOR_AUTOMATION: TaskDepth.CONSCIOUS,
    ExecutorClass.HUMAN_ONLY: TaskDepth.CONSCIOUS,
    ExecutorClass.HUMAN_LED_AI_ASSISTED: TaskDepth.GUIDED,
    ExecutorClass.AGENT_PREPARED_HUMAN_APPROVED: TaskDepth.GUIDED,
    ExecutorClass.DETERMINISTIC_AUTOMATION: TaskDepth.ROUTINE,
    ExecutorClass.AGENT_EXECUTED_HUMAN_SUPERVISED: TaskDepth.GUIDED,
    ExecutorClass.BOUNDED_AUTONOMOUS_AGENT: TaskDepth.GUIDED,
}

#: Fukasawa task depth level for the agent an executor class exports to.
#:
#: ADR-006 names escalation_target, forbidden and fallback for the AgentSpec
#: but not depth_level, which AgentSpec requires. Derived from the class here
#: so the value is deterministic and testable rather than hand-entered per
#: workflow. Never 4 (a coordinator manages a whole workflow — that is this
#: runtime's job, not an exported agent's) and never 5 (redesign-only; the
#: generator refuses it outright).
#:
#: HUMAN_LED_AI_ASSISTED appears for completeness but is unreachable: that
#: class exports a human-owned transition, so no agent is declared for it.
#: See ``_AGENT_OWNED``.
_AGENT_DEPTH_LEVEL: dict[ExecutorClass, int] = {
    ExecutorClass.DETERMINISTIC_AUTOMATION: 0,  # rule task, no reasoning
    ExecutorClass.HUMAN_LED_AI_ASSISTED: 1,  # one bounded inference, assisting
    ExecutorClass.AGENT_PREPARED_HUMAN_APPROVED: 2,  # local triage, then hand off
    ExecutorClass.AGENT_EXECUTED_HUMAN_SUPERVISED: 2,  # local triage under review
    ExecutorClass.BOUNDED_AUTONOMOUS_AGENT: 3,  # diagnostic agent within bounds
}

#: Classes where an agent or script owns the transition and gets an AgentSpec.
#:
#: HUMAN_LED_AI_ASSISTED is deliberately absent. That class means a person does
#: the work and AI helps, so the human owns the transition; an AgentSpec
#: declared for it would own nothing, and ``_build_capsule`` in the frozen
#: generator refuses an agent that owns no transitions. The assistance is
#: recorded in ``allowed_tools`` instead, which is what it is — a tool, not a
#: governed executor.
_AGENT_OWNED = frozenset(
    {
        ExecutorClass.DETERMINISTIC_AUTOMATION,
        ExecutorClass.AGENT_EXECUTED_HUMAN_SUPERVISED,
        ExecutorClass.AGENT_PREPARED_HUMAN_APPROVED,
        ExecutorClass.BOUNDED_AUTONOMOUS_AGENT,
    }
)

#: Classes that may only reach their next state through a human approval gate.
#:
#: AGENT_PREPARED_HUMAN_APPROVED is "an agent prepares, a human authorizes" by
#: definition. BOUNDED_AUTONOMOUS_AGENT requires a gate per ADR-006, and export
#: refuses it when the assignment names none.
_GATED = frozenset(
    {
        ExecutorClass.AGENT_PREPARED_HUMAN_APPROVED,
        ExecutorClass.BOUNDED_AUTONOMOUS_AGENT,
    }
)

#: What each exported executor is explicitly forbidden to do, by class.
#:
#: Stated rather than implied, because these become the generated package's
#: CONTRACT.md. Every agent-owned class inherits the two universal denials.
_UNIVERSAL_DENIALS = (
    "reason above the declared depth level",
    "improvise a path when no transition matches — escalate instead",
)
_DENIALS_BY_CLASS: dict[ExecutorClass, tuple[str, ...]] = {
    ExecutorClass.AGENT_PREPARED_HUMAN_APPROVED: (
        "let this step take effect before the approval gate records a decision",
    ),
    ExecutorClass.BOUNDED_AUTONOMOUS_AGENT: (
        "let this step take effect before the approval gate records a decision",
        "widen its own bounds, tools, or permissions",
    ),
    ExecutorClass.AGENT_EXECUTED_HUMAN_SUPERVISED: (
        "proceed past an output a human has not yet reviewed",
    ),
    ExecutorClass.DETERMINISTIC_AUTOMATION: (
        "substitute judgment for the rule when the rule does not fit — escalate",
    ),
}


# ------------------------------------------------------------------- the build


def _agent_name_for(step_id: str) -> str:
    """Slug for the agent that executes a step, when the step is agent-owned.

    Derived from the step id so the name is stable across rebuilds and so an
    operator reading a package can tell which step it came from.
    """
    return f"{step_id}-agent"


def _escalation_target_for(step: WorkflowStep, workflow: AccountableWorkflow) -> str:
    """Who this step's executor escalates to when blocked or uncertain.

    The first declared workflow owner who is not performing the step; failing
    that, the first owner. An agent with nowhere to escalate improvises, and
    improvisation is non-conformance — so this never returns empty.
    """
    for owner in workflow.owners:
        if owner != step.actor:
            return owner
    return workflow.owners[0]


def _evidence_for(step: WorkflowStep) -> str:
    """The step's evidence requirement, as one plain-language statement.

    Joined from the step's declared outputs. HW-010 makes an output without an
    evidence requirement a blocking finding, so a promoted workflow always has
    these; an empty result means the step declares no outputs at all.
    """
    return "; ".join(o.evidence_requirement for o in step.outputs if o.evidence_requirement)


def _gate_at(step_id: str, workflow: AccountableWorkflow) -> str:
    """Gate id guarding a step, or empty when the step is not gated."""
    return next((g.gate_id for g in workflow.gates if g.at_step == step_id), "")


def build_cooperative_workflow(
    workflow: AccountableWorkflow,
    assessments: Iterable[CooperationAssessment],
    *,
    approved_by: str = "",
    version: str = "1",
) -> CooperativeWorkflow:
    """Assign every step of an accountable workflow to an executor.

    The assignment reads each assessment's ``effective_executor``, so a human
    override governs and the table's recommendation does not. Nothing here
    re-classifies: the decision was made in ``src/governance/cooperation.py``
    and this only records what follows from it.

    ``approved_by`` is a human act. Left empty the artifact is unapproved, and
    ``export_workflow`` refuses it — nothing reaches the Agent Foundry path
    without a named person having approved the assignments.
    """
    by_step = {a.step_id: a for a in assessments}
    missing = [s.step_id for s in workflow.steps if s.step_id not in by_step]
    if missing:
        raise ExportRefusedError(
            f"workflow '{workflow.workflow_id}' cannot be assigned: no cooperation "
            f"assessment for step(s) {missing}. Assess every step before building "
            f"the cooperative workflow."
        )

    assignments: list[StepAssignment] = []
    for step in workflow.steps:
        assessment = by_step[step.step_id]
        executor = assessment.effective_executor
        agent_owned = executor in _AGENT_OWNED

        assignments.append(
            StepAssignment(
                step_id=step.step_id,
                executor_class=executor,
                # NOT_READY_FOR_AUTOMATION assigns nobody: that is the honest
                # answer the class exists to express.
                executor_identity=(
                    ""
                    if executor is ExecutorClass.NOT_READY_FOR_AUTOMATION
                    else _agent_name_for(step.step_id)
                    if agent_owned
                    else step.actor
                ),
                # The step's declared actor stays accountable whatever executes
                # it. Automation moves the work, never the accountability.
                human_owner=step.actor,
                approval_gate=_gate_at(step.step_id, workflow),
                escalation_target=_escalation_target_for(step, workflow),
                # Matched from the assessment, never inferred. Guessing what a
                # step touches would put unearned confidence into an agent's
                # permissions.
                allowed_tools=list(assessment.required_tools),
                prohibited_actions=(
                    list(_UNIVERSAL_DENIALS + _DENIALS_BY_CLASS.get(executor, ()))
                    if agent_owned
                    else []
                ),
                evidence_output=_evidence_for(step),
                # Falling back toward a human is always safe.
                fallback_executor=ExecutorClass.HUMAN_ONLY,
            )
        )

    return CooperativeWorkflow(
        workflow_id=workflow.workflow_id,
        name=workflow.name,
        version=version,
        source_workflow_version=workflow.version,
        assignments=assignments,
        assessment_ids=[by_step[s.step_id].assessment_id for s in workflow.steps],
        required_agent_packages=sorted(
            a.executor_identity
            for a in assignments
            if a.executor_class in _AGENT_OWNED and a.executor_identity
        ),
        approved_by=approved_by,
        approved_at=None,
    )


# ------------------------------------------------------------------ the export


def _gate_state(step_id: str, taken: set[str]) -> str:
    """Name the state a step waits in while a human decides.

    A gate is a place the work sits, not a flag on a transition, so it needs a
    state of its own. Uniquified against the states already in use so a step
    literally named ``x-pending-approval`` cannot collide with the gate for
    step ``x``.
    """
    candidate = f"{step_id}-pending-approval"
    while candidate in taken:
        candidate += "-gate"
    return candidate


def _terminal_state(taken: set[str]) -> str:
    """Name the state a finished workflow rests in, avoiding collisions."""
    candidate = "complete"
    while candidate in taken:
        candidate = f"workflow-{candidate}"
    return candidate


def _agent_specs(
    cooperative: CooperativeWorkflow, workflow: AccountableWorkflow
) -> list[AgentSpec]:
    """Declare one agent per agent-owned assignment.

    Only classes in ``_AGENT_OWNED`` appear. An assignment whose executor is a
    person, or which is NOT_READY_FOR_AUTOMATION, produces no agent — the whole
    point of exporting NOT_READY is that the step stays with a human.
    """
    specs: list[AgentSpec] = []
    for assignment in cooperative.assignments:
        if assignment.executor_class not in _AGENT_OWNED:
            continue
        step = workflow.step(assignment.step_id)
        specs.append(
            AgentSpec(
                agent_name=assignment.executor_identity,
                depth_level=_AGENT_DEPTH_LEVEL[assignment.executor_class],
                responsibilities=step.action or step.description or step.name,
                escalation_target=assignment.escalation_target,
                allowed_tools=list(assignment.allowed_tools),
                forbidden=list(assignment.prohibited_actions),
            )
        )
    return specs


def _check_exportable(
    cooperative: CooperativeWorkflow, workflow: AccountableWorkflow
) -> None:
    """Refuse an export that would cross a line the assessment drew.

    Three refusals, each naming what to fix:

    * an unapproved artifact — approval is a human act, not a default;
    * a step with no assignment — export must not invent one;
    * a BOUNDED_AUTONOMOUS_AGENT step with no approval gate, which ADR-006
      permits to export **only** behind an explicit gate.
    """
    if not cooperative.approved:
        raise ExportRefusedError(
            f"cooperative workflow '{cooperative.workflow_id}' has not been "
            f"approved. A named human must approve the executor assignments "
            f"before they reach the Agent Foundry path — set approved_by."
        )

    assigned = {a.step_id for a in cooperative.assignments}
    unassigned = [s.step_id for s in workflow.steps if s.step_id not in assigned]
    if unassigned:
        raise ExportRefusedError(
            f"cooperative workflow '{cooperative.workflow_id}' does not assign "
            f"step(s) {unassigned}. Every step must be assigned before export."
        )

    ungated = [
        a.step_id
        for a in cooperative.assignments
        if a.executor_class is ExecutorClass.BOUNDED_AUTONOMOUS_AGENT
        and not a.approval_gate.strip()
    ]
    if ungated:
        raise ExportRefusedError(
            f"step(s) {ungated} are assigned BOUNDED_AUTONOMOUS_AGENT with no "
            f"approval gate. A bounded autonomous agent exports only behind an "
            f"explicit gate: declare a gate at the step, or assign a class that "
            f"keeps a human in the loop."
        )


def export_workflow(
    cooperative: CooperativeWorkflow, workflow: AccountableWorkflow
) -> WorkflowBrief:
    """Flatten an approved cooperative workflow onto the existing runtime.

    Each step becomes a state; each ``next_steps`` edge becomes a transition
    owned by the executor of the step being left, carrying that step's evidence
    requirement and its class's task depth.

    Steps whose class requires a human to authorize each execution are split
    into two transitions — the executor's work, then the human's decision, with
    a real state in between. This is not decoration. The existing runtime opens
    its review gate on CONSCIOUS-depth transitions, and ``WorkflowBrief``
    refuses a CONSCIOUS transition owned by an agent, so "a gated agent step"
    is unrepresentable as one transition. Splitting it makes the approval a
    place the work waits and an event the ledger records.

    Raises ``ExportRefusedError`` when the artifact is unapproved, a step is
    unassigned, or a BOUNDED_AUTONOMOUS_AGENT step names no approval gate.
    """
    _check_exportable(cooperative, workflow)

    step_ids = [s.step_id for s in workflow.steps]
    states: list[str] = list(step_ids)
    taken = set(states)

    # Gate states first, so the terminal state cannot take a name a gate needs.
    gate_states: dict[str, str] = {}
    for assignment in cooperative.assignments:
        if assignment.executor_class in _GATED:
            name = _gate_state(assignment.step_id, taken)
            gate_states[assignment.step_id] = name
            states.append(name)
            taken.add(name)

    terminal = _terminal_state(taken)
    states.append(terminal)

    transitions: list[Transition] = []
    # The runtime resolves a move by the first transition matching
    # (from_state, to_state), so a second transition on the same pair is
    # unreachable — its owner and evidence requirement would never apply. One
    # edge per pair, first emitted wins, which is always the declared path
    # rather than a recovery that happens to land on the same state.
    seen: set[tuple[str, str]] = set()

    def emit(
        from_state: str, to_state: str, owner: str, evidence: str, depth: TaskDepth
    ) -> None:
        """Add a transition unless this edge already exists."""
        if (from_state, to_state) in seen:
            return
        seen.add((from_state, to_state))
        transitions.append(
            Transition(
                from_state=from_state,
                to_state=to_state,
                owner=owner,
                evidence_required=evidence,
                depth=depth,
            )
        )

    for step in workflow.steps:
        assignment = cooperative.assignment(step.step_id)
        executor = assignment.executor_class
        depth = _DEPTH_BY_CLASS[executor]
        owner = assignment.executor_identity or assignment.human_owner
        evidence = assignment.evidence_output
        # A terminal step still has somewhere to go: the runtime needs a state
        # that means finished, or the last step looks like a dead end.
        destinations = step.next_steps or [terminal]

        if step.step_id in gate_states:
            waiting = gate_states[step.step_id]
            # The executor's half: prepare the work and park it for a decision.
            emit(step.step_id, waiting, owner, evidence, depth)
            # The human's half: CONSCIOUS, so the runtime pauses at the gate.
            for destination in destinations:
                emit(waiting, destination, assignment.human_owner, "", TaskDepth.CONSCIOUS)
        else:
            for destination in destinations:
                emit(step.step_id, destination, owner, evidence, depth)

        # Declared recovery paths are real allowed movements. Omitting them
        # would turn a rehearsed recovery into a non-conformance at runtime.
        # They carry no evidence requirement of their own, because the
        # exception is often that the evidence could not be produced.
        #
        # When a recovery lands on a state the step already reaches, `emit`
        # keeps the declared edge and drops this one. The recovery stays
        # possible — it is the same move — but it inherits the declared path's
        # evidence requirement. That is the conservative direction (it asks for
        # more, never less) and it is the only shape the runtime can express,
        # since a brief has one edge per state pair.
        for path in step.exception_paths:
            if path.next_step and path.next_step in taken:
                emit(step.step_id, path.next_step, path.owner, "", TaskDepth.GUIDED)

    # The workflow default only applies to transitions that set no depth of
    # their own, and every transition above sets one. Taking the most demanding
    # depth keeps the default honest if one is ever added by hand.
    ranked = [TaskDepth.ROUTINE, TaskDepth.GUIDED, TaskDepth.CONSCIOUS]
    workflow_depth = max(
        (t.depth for t in transitions if t.depth is not None),
        key=ranked.index,
        default=TaskDepth.GUIDED,
    )

    return WorkflowBrief(
        id=workflow.workflow_id,
        title=workflow.name,
        owner=workflow.owners[0],
        task_depth=workflow_depth,
        initial_state=step_ids[0],
        states=states,
        transitions=transitions,
        completion_criteria=workflow.completion_contract,
        exception_path=workflow.exception_policy,
        # The human approved the assignments; that approval is what makes the
        # brief buildable. generate_packages refuses anything less.
        status=BriefStatus.APPROVED,
        agents=_agent_specs(cooperative, workflow),
    )


def steps_kept_human(cooperative: CooperativeWorkflow) -> list[str]:
    """Step ids that exported to a person rather than to an agent.

    Not an error and not a warning. A workflow may legitimately keep work with
    people, and NOT_READY_FOR_AUTOMATION steps are meant to stay human until
    the facts about them change. Surfaced so an operator sees what remains
    manual without reading the whole brief.
    """
    return [
        a.step_id
        for a in cooperative.assignments
        if a.executor_class not in _AGENT_OWNED
    ]
