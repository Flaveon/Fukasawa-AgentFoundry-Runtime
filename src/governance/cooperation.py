# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Cooperation assessment — deciding who should do each step, and how watched.

Given an accountable workflow, this answers one question per step: what is the
most appropriate executor, and what supervision does that executor need. The
answer comes from a **published decision table** over facts the step already
declares — never from a model. A human can read
``docs/cooperation-classification-guide.md`` and predict the output before
running it, which is what makes a classification explainable rather than merely
automatic.

Two mechanisms, in this order:

1. **The base recommendation** reads judgment load, determinism and
   repeatability — how much thinking the step needs, how reliably the same
   inputs give the same result, and how often it recurs.
2. **Safety floors** then cap that recommendation. A floor can only ever move
   work *toward* human control, never away from it. Irreversible effects, high
   risk, sensitive data, undefined decision authority, and uncharacterized
   steps all impose one.

The rule that makes the whole thing safe rather than merely configurable:

    **Overrides are one-directional.** A human may always move a step toward
    human control. A human may never move a floored step toward greater
    autonomy.

That is enforced in code by comparing ``ExecutorClass.autonomy_rank``, not left
to convention — see ``apply_override``. It mirrors doctrine the runtime already
enforces elsewhere: a CONSCIOUS-depth transition cannot be owned by an agent.

Nothing here decides anything beyond a recommendation. Assignment, approval and
export are later steps, and every one of them keeps a human in the loop.
"""

import uuid
from typing import Iterable, Optional

from src.schemas.cooperation import (
    AutomationReadiness,
    CooperationAssessment,
    ExecutorClass,
    ExecutorOverride,
    SafetyFloor,
    SupervisionMode,
)
from src.schemas.human_workflow import (
    AccountableWorkflow,
    DataSensitivity,
    Determinism,
    JudgmentLoad,
    Repeatability,
    Reversibility,
    RiskLevel,
    StepCharacteristics,
    WorkflowStep,
)


class OverrideRefusedError(Exception):
    """Raised when an override would increase autonomy on a floored step."""


#: What each floor caps autonomy at. A floor is a ceiling, never a promotion:
#: applying one can only move a recommendation toward human control.
#:
#: Listed in precedence order — when several apply, the most restrictive wins,
#: and ties resolve to the first listed so the outcome is deterministic.
_FLOOR_CEILINGS: list[tuple[SafetyFloor, ExecutorClass]] = [
    # Nobody has said who decides here. Assigning an executor to a step with no
    # decision owner would hand authority to whoever happens to run it.
    (SafetyFloor.UNDEFINED_AUTHORITY, ExecutorClass.NOT_READY_FOR_AUTOMATION),
    # The step has not been characterized enough to judge. Unknown is never
    # treated as safe.
    (SafetyFloor.UNKNOWN_CHARACTERISTICS, ExecutorClass.NOT_READY_FOR_AUTOMATION),
    # The effect cannot be undone. A human authorizes before it takes effect.
    (SafetyFloor.IRREVERSIBLE, ExecutorClass.AGENT_PREPARED_HUMAN_APPROVED),
    # A wrong outcome causes serious damage.
    (SafetyFloor.HIGH_RISK, ExecutorClass.AGENT_PREPARED_HUMAN_APPROVED),
    # Sensitive data is handled here.
    (SafetyFloor.SENSITIVE_DATA, ExecutorClass.AGENT_PREPARED_HUMAN_APPROVED),
]

#: Supervision that each executor class requires. Derived from the class rather
#: than assessed separately: how closely work is watched follows from who is
#: doing it and how much latitude they have.
_SUPERVISION: dict[ExecutorClass, SupervisionMode] = {
    ExecutorClass.NOT_READY_FOR_AUTOMATION: SupervisionMode.APPROVAL_REQUIRED,
    ExecutorClass.HUMAN_ONLY: SupervisionMode.NONE,
    ExecutorClass.HUMAN_LED_AI_ASSISTED: SupervisionMode.EVERY_OUTPUT_REVIEWED,
    ExecutorClass.AGENT_PREPARED_HUMAN_APPROVED: SupervisionMode.APPROVAL_REQUIRED,
    ExecutorClass.DETERMINISTIC_AUTOMATION: SupervisionMode.SPOT_CHECK,
    ExecutorClass.AGENT_EXECUTED_HUMAN_SUPERVISED: SupervisionMode.EVERY_OUTPUT_REVIEWED,
    ExecutorClass.BOUNDED_AUTONOMOUS_AGENT: SupervisionMode.SPOT_CHECK,
}


def _unknown_factors(c: StepCharacteristics) -> list[str]:
    """Names of characteristics left uncharacterized, in declaration order."""
    return [
        name
        for name, value in (
            ("judgment_load", c.judgment_load),
            ("repeatability", c.repeatability),
            ("determinism", c.determinism),
            ("risk", c.risk),
            ("reversibility", c.reversibility),
            ("data_sensitivity", c.data_sensitivity),
        )
        if value.value == "UNKNOWN"
    ]


def _base_recommendation(c: StepCharacteristics) -> tuple[ExecutorClass, str]:
    """The recommendation before safety floors, with the reason for it.

    Reads only judgment load, determinism and repeatability: how much thinking
    the step needs, how reliably it repeats, and how often it recurs. Risk,
    reversibility and sensitivity are deliberately *not* consulted here — they
    are floors, applied afterwards, so that raising them can only ever restrict
    a recommendation and never widen one.
    """
    # Taste, ethics, responsibility and meaning stay with people. This mirrors
    # the CONSCIOUS depth rule the workflow brief already enforces.
    if c.judgment_load is JudgmentLoad.HIGH:
        return (
            ExecutorClass.HUMAN_ONLY,
            "the step demands high human judgment, which is not delegable",
        )

    if c.judgment_load is JudgmentLoad.MODERATE:
        return (
            ExecutorClass.HUMAN_LED_AI_ASSISTED,
            "the step needs real judgment, so a person leads and AI assists",
        )

    # Low or no judgment. How repeatable and deterministic is it?
    if c.repeatability is Repeatability.ONE_OFF:
        return (
            ExecutorClass.AGENT_PREPARED_HUMAN_APPROVED,
            "the step happens too rarely to have a trustworthy pattern, so an "
            "agent may prepare but a human authorizes",
        )

    if c.determinism is Determinism.DETERMINISTIC:
        if c.repeatability is Repeatability.ROUTINE:
            return (
                ExecutorClass.DETERMINISTIC_AUTOMATION,
                "the step is routine and always produces the same result from "
                "the same inputs, so it is a rule, not a judgment",
            )
        return (
            ExecutorClass.AGENT_EXECUTED_HUMAN_SUPERVISED,
            "the step is deterministic but not yet routine, so an agent runs it "
            "under observation",
        )

    if c.determinism is Determinism.MOSTLY_DETERMINISTIC:
        if c.repeatability is Repeatability.ROUTINE and c.judgment_load is JudgmentLoad.NONE:
            return (
                ExecutorClass.BOUNDED_AUTONOMOUS_AGENT,
                "the step is routine, nearly deterministic and needs no "
                "judgment, so an agent may act within stated bounds",
            )
        return (
            ExecutorClass.AGENT_EXECUTED_HUMAN_SUPERVISED,
            "the step is mostly deterministic, so an agent runs it while a "
            "human watches the output",
        )

    # Judgment-based work with little declared judgment load is a contradiction
    # in the description; treat it as needing a person until it is clarified.
    return (
        ExecutorClass.HUMAN_LED_AI_ASSISTED,
        "the step's outcome varies with interpretation, so a person leads it",
    )


def _applicable_floors(
    c: StepCharacteristics, decision_authority: str
) -> list[tuple[SafetyFloor, ExecutorClass]]:
    """Every safety floor this step triggers, in precedence order."""
    unknown = _unknown_factors(c)
    triggered: list[tuple[SafetyFloor, ExecutorClass]] = []
    for floor, ceiling in _FLOOR_CEILINGS:
        if floor is SafetyFloor.UNDEFINED_AUTHORITY and not decision_authority.strip():
            triggered.append((floor, ceiling))
        elif floor is SafetyFloor.UNKNOWN_CHARACTERISTICS and unknown:
            triggered.append((floor, ceiling))
        elif floor is SafetyFloor.IRREVERSIBLE and c.reversibility is Reversibility.IRREVERSIBLE:
            triggered.append((floor, ceiling))
        elif floor is SafetyFloor.HIGH_RISK and c.risk is RiskLevel.HIGH:
            triggered.append((floor, ceiling))
        elif floor is SafetyFloor.SENSITIVE_DATA and c.data_sensitivity is DataSensitivity.SENSITIVE:
            triggered.append((floor, ceiling))
    return triggered


def _readiness(
    executor: ExecutorClass, c: StepCharacteristics, floored: bool
) -> AutomationReadiness:
    """Whether this step is ready to be automated today.

    Kept separate from the executor class because a step can be *suitable* for
    automation in principle while lacking the repetition or the clarity to do
    it safely yet — the same evidence-before-capability discipline the agent
    maturity model uses.
    """
    if executor in (
        ExecutorClass.NOT_READY_FOR_AUTOMATION,
        ExecutorClass.HUMAN_ONLY,
    ):
        return AutomationReadiness.NOT_READY
    if _unknown_factors(c) or c.repeatability is Repeatability.ONE_OFF:
        return AutomationReadiness.NOT_READY
    if floored:
        return AutomationReadiness.PILOT
    if c.repeatability is Repeatability.ROUTINE and c.determinism in (
        Determinism.DETERMINISTIC,
        Determinism.MOSTLY_DETERMINISTIC,
    ):
        return AutomationReadiness.READY
    return AutomationReadiness.PILOT


def _required_tools(step: WorkflowStep, systems: Iterable[str]) -> list[str]:
    """Systems this step visibly touches, matched against the declared list.

    Deterministic substring matching against the workflow's own systems, sorted
    so the output never depends on iteration order. A step that names no system
    reports none rather than guessing.
    """
    haystack = " ".join(
        [step.name, step.description, step.action]
        + [i.name for i in step.inputs]
        + [i.source for i in step.inputs]
        + [o.name for o in step.outputs]
    ).lower()
    return sorted({s for s in systems if s.strip() and s.strip().lower() in haystack})


def assess_step(
    step: WorkflowStep,
    *,
    workflow_id: str = "",
    gated: bool = False,
    systems: Iterable[str] = (),
) -> CooperationAssessment:
    """Assess one step and recommend how it should be executed.

    ``gated`` marks a step guarded by an approval gate; it never widens the
    recommendation, only tightens supervision, because a gate is evidence a
    human already decided this needs their eyes.
    """
    c = step.characteristics
    base, reason = _base_recommendation(c)
    floors = _applicable_floors(c, step.decision_authority)

    executor, floor, floor_reason = base, SafetyFloor.NONE, ""
    if floors:
        # The most restrictive ceiling wins; ties resolve by declaration order.
        floor, ceiling = min(floors, key=lambda f: (f[1].autonomy_rank, floors.index(f)))
        if ceiling.autonomy_rank < executor.autonomy_rank:
            executor = ceiling
            floor_reason = f"; capped by the {floor.value} safety floor"
        else:
            # The floor applies but the base was already at least as cautious.
            # Record it anyway: the constraint is real and governs overrides.
            floor_reason = f"; the {floor.value} safety floor also applies"

    supervision = _SUPERVISION[executor]
    if gated and supervision is SupervisionMode.SPOT_CHECK:
        supervision = SupervisionMode.APPROVAL_REQUIRED

    return CooperationAssessment(
        assessment_id=f"ca-{uuid.uuid4().hex[:8]}",
        workflow_id=workflow_id,
        step_id=step.step_id,
        recommended_executor=executor,
        rationale=reason + floor_reason,
        assessed_factors=c.model_copy(deep=True),
        safety_floor=floor,
        required_tools=_required_tools(step, systems),
        supervision_mode=supervision,
        automation_readiness=_readiness(executor, c, floor is not SafetyFloor.NONE),
    )


def assess_workflow(
    workflow: AccountableWorkflow, systems: Iterable[str] = ()
) -> list[CooperationAssessment]:
    """Assess every step of an accountable workflow, in declaration order.

    Deterministic apart from the generated assessment ids: the same workflow
    always yields the same recommendations, floors and rationales.

    ``systems`` is the workflow's declared tool list, which lives on the
    observed draft rather than the promoted artifact — pass it through from
    there when you want ``required_tools`` populated. Left empty, tools are
    reported as none rather than inferred, because guessing what a step touches
    would put unearned confidence into an agent's permissions later.
    """
    gated_steps = {g.at_step for g in workflow.gates}
    return [
        assess_step(
            step,
            workflow_id=workflow.workflow_id,
            gated=step.step_id in gated_steps,
            systems=systems,
        )
        for step in workflow.steps
    ]


def apply_override(
    assessment: CooperationAssessment,
    to_class: ExecutorClass,
    actor: str,
    rationale: str,
) -> CooperationAssessment:
    """Record a human's decision to override the recommendation.

    **One-directional.** Moving a step toward human control is always allowed —
    a person may always decide to keep something themselves. Moving a *floored*
    step toward greater autonomy is refused: the floor exists because of a fact
    about the work (it cannot be undone, it handles sensitive data, nobody owns
    the decision), and that fact does not change because someone would prefer
    it did.

    On an unfloored step, any override is permitted with a rationale — the
    decision table is guidance there, not doctrine.
    """
    if not actor.strip():
        raise OverrideRefusedError("an override must name who made it")
    if not rationale.strip():
        raise OverrideRefusedError(
            "an override must state why; without a reason it is "
            "indistinguishable from a mis-click, and this decision governs who "
            "may act unsupervised"
        )
    current = assessment.effective_executor
    if assessment.is_floored and to_class.autonomy_rank > current.autonomy_rank:
        raise OverrideRefusedError(
            f"step '{assessment.step_id}' hit the {assessment.safety_floor.value} "
            f"safety floor, so it cannot be moved from "
            f"{current.value} to the more autonomous {to_class.value}. "
            f"Overrides may always move work toward human control, never away "
            f"from it. Change the step's characteristics if the underlying fact "
            f"is wrong."
        )
    updated = assessment.model_copy(deep=True)
    updated.override = ExecutorOverride(
        overridden_to=to_class, rationale=rationale, actor=actor
    )
    return updated


def unassessed_steps(
    workflow: AccountableWorkflow, assessments: Iterable[CooperationAssessment]
) -> list[str]:
    """Step ids with no assessment — what the COOPERATION_READY gate checks."""
    assessed = {a.step_id for a in assessments}
    return [s.step_id for s in workflow.steps if s.step_id not in assessed]


def steps_not_ready(
    assessments: Iterable[CooperationAssessment],
) -> list[CooperationAssessment]:
    """Assessments still resolving to NOT_READY_FOR_AUTOMATION.

    Not an error: a workflow may legitimately keep steps with people. It is
    surfaced so a human sees what remains unautomated and why, rather than
    discovering it at export.
    """
    return [
        a
        for a in assessments
        if a.effective_executor is ExecutorClass.NOT_READY_FOR_AUTOMATION
    ]
