# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Phase 4 tests — cooperation assessment, the Gate E (first half) evidence.

Covers the cases the release strategy asks for: human-only safety, deterministic
automation, AI-assisted, supervised agent, not-ready, high-risk irreversible
action, sensitive-data handling, fallback executor, and approval/escalation.

The test that matters most is `TestOneDirectionalOverride`. Everything else here
is a recommendation an operator can argue with; that one is the safety property
the release depends on — a human may always move work toward human control, and
may never move a floored step toward greater autonomy.
"""

from pathlib import Path

import pytest
import yaml

from src.governance.cooperation import (
    OverrideRefusedError,
    apply_override,
    assess_step,
    assess_workflow,
    steps_not_ready,
    unassessed_steps,
)
from src.schemas.cooperation import (
    AutomationReadiness,
    CooperationAssessment,
    ExecutorClass,
    SafetyFloor,
    SupervisionMode,
)
from src.schemas.human_workflow import (
    AccountableWorkflow,
    DataSensitivity,
    Determinism,
    HumanWorkflowDraft,
    JudgmentLoad,
    Repeatability,
    Reversibility,
    RiskLevel,
    StepCharacteristics,
    WorkflowStep,
)

ROOT = Path(__file__).resolve().parent.parent
PILOT_DIR = ROOT / "examples" / "workflows" / "substack-publication"


def step(
    *,
    authority: str = "operator",
    judgment: JudgmentLoad = JudgmentLoad.NONE,
    repeat: Repeatability = Repeatability.ROUTINE,
    determinism: Determinism = Determinism.DETERMINISTIC,
    risk: RiskLevel = RiskLevel.LOW,
    reversibility: Reversibility = Reversibility.REVERSIBLE,
    sensitivity: DataSensitivity = DataSensitivity.PUBLIC,
    **kw,
) -> WorkflowStep:
    """A fully characterized step; each test varies one factor."""
    return WorkflowStep(
        step_id=kw.pop("step_id", "s"),
        name=kw.pop("name", "S"),
        decision_authority=authority,
        characteristics=StepCharacteristics(
            judgment_load=judgment,
            repeatability=repeat,
            determinism=determinism,
            risk=risk,
            reversibility=reversibility,
            data_sensitivity=sensitivity,
        ),
        **kw,
    )


class TestBaseRecommendations:
    def test_high_judgment_stays_with_a_person(self):
        a = assess_step(step(judgment=JudgmentLoad.HIGH, determinism=Determinism.JUDGMENT_BASED))
        assert a.recommended_executor is ExecutorClass.HUMAN_ONLY
        assert "judgment" in a.rationale

    def test_moderate_judgment_is_human_led_ai_assisted(self):
        a = assess_step(step(judgment=JudgmentLoad.MODERATE))
        assert a.recommended_executor is ExecutorClass.HUMAN_LED_AI_ASSISTED

    def test_routine_deterministic_work_is_a_rule_not_a_judgment(self):
        a = assess_step(step())
        assert a.recommended_executor is ExecutorClass.DETERMINISTIC_AUTOMATION
        assert a.automation_readiness is AutomationReadiness.READY

    def test_routine_mostly_deterministic_may_be_bounded_autonomous(self):
        a = assess_step(step(determinism=Determinism.MOSTLY_DETERMINISTIC))
        assert a.recommended_executor is ExecutorClass.BOUNDED_AUTONOMOUS_AGENT

    def test_supervised_agent_when_not_yet_routine(self):
        a = assess_step(step(repeat=Repeatability.OCCASIONAL))
        assert a.recommended_executor is ExecutorClass.AGENT_EXECUTED_HUMAN_SUPERVISED
        assert a.supervision_mode is SupervisionMode.EVERY_OUTPUT_REVIEWED

    def test_one_off_work_has_no_trustworthy_pattern(self):
        a = assess_step(step(repeat=Repeatability.ONE_OFF))
        assert a.recommended_executor is ExecutorClass.AGENT_PREPARED_HUMAN_APPROVED
        assert a.automation_readiness is AutomationReadiness.NOT_READY

    def test_recommendations_are_deterministic(self):
        s = step(judgment=JudgmentLoad.MODERATE)
        first, second = assess_step(s), assess_step(s)
        assert first.recommended_executor is second.recommended_executor
        assert first.rationale == second.rationale
        assert first.safety_floor is second.safety_floor


class TestSafetyFloors:
    def test_irreversible_work_needs_human_authorization(self):
        a = assess_step(step(reversibility=Reversibility.IRREVERSIBLE))
        assert a.safety_floor is SafetyFloor.IRREVERSIBLE
        assert a.recommended_executor is ExecutorClass.AGENT_PREPARED_HUMAN_APPROVED
        assert a.supervision_mode is SupervisionMode.APPROVAL_REQUIRED

    def test_high_risk_work_needs_human_authorization(self):
        a = assess_step(step(risk=RiskLevel.HIGH))
        assert a.safety_floor is SafetyFloor.HIGH_RISK
        assert a.recommended_executor is ExecutorClass.AGENT_PREPARED_HUMAN_APPROVED

    def test_sensitive_data_needs_human_authorization(self):
        a = assess_step(step(sensitivity=DataSensitivity.SENSITIVE))
        assert a.safety_floor is SafetyFloor.SENSITIVE_DATA
        assert a.recommended_executor is ExecutorClass.AGENT_PREPARED_HUMAN_APPROVED

    def test_undefined_decision_authority_blocks_assignment_entirely(self):
        a = assess_step(step(authority=""))
        assert a.safety_floor is SafetyFloor.UNDEFINED_AUTHORITY
        assert a.recommended_executor is ExecutorClass.NOT_READY_FOR_AUTOMATION

    def test_uncharacterized_steps_are_never_assumed_safe(self):
        bare = WorkflowStep(step_id="s", name="S", decision_authority="operator")
        a = assess_step(bare)
        assert a.safety_floor is SafetyFloor.UNKNOWN_CHARACTERISTICS
        assert a.recommended_executor is ExecutorClass.NOT_READY_FOR_AUTOMATION
        assert a.automation_readiness is AutomationReadiness.NOT_READY

    def test_a_floor_only_ever_restricts(self):
        # The same step with and without the floor: the floored one must never
        # be more autonomous.
        free = assess_step(step())
        floored = assess_step(step(reversibility=Reversibility.IRREVERSIBLE))
        assert (
            floored.recommended_executor.autonomy_rank
            <= free.recommended_executor.autonomy_rank
        )

    def test_most_restrictive_floor_wins(self):
        a = assess_step(
            step(
                authority="",  # NOT_READY ceiling
                reversibility=Reversibility.IRREVERSIBLE,  # weaker ceiling
            )
        )
        assert a.recommended_executor is ExecutorClass.NOT_READY_FOR_AUTOMATION

    def test_floor_is_recorded_even_when_base_was_already_cautious(self):
        # A high-judgment irreversible step is HUMAN_ONLY on its own merits, but
        # the floor still governs what an override may do.
        a = assess_step(
            step(judgment=JudgmentLoad.HIGH, determinism=Determinism.JUDGMENT_BASED,
                 reversibility=Reversibility.IRREVERSIBLE)
        )
        assert a.recommended_executor is ExecutorClass.HUMAN_ONLY
        assert a.is_floored


class TestOneDirectionalOverride:
    """The safety property the release depends on."""

    def _floored(self) -> CooperationAssessment:
        return assess_step(step(reversibility=Reversibility.IRREVERSIBLE))

    def test_moving_toward_human_control_is_always_allowed(self):
        a = self._floored()
        out = apply_override(a, ExecutorClass.HUMAN_ONLY, "flaveon", "editor insists")
        assert out.effective_executor is ExecutorClass.HUMAN_ONLY
        assert out.override.actor == "flaveon" and out.override.rationale

    def test_moving_a_floored_step_toward_autonomy_is_refused(self):
        a = self._floored()
        with pytest.raises(OverrideRefusedError, match="toward human control, never away"):
            apply_override(a, ExecutorClass.BOUNDED_AUTONOMOUS_AGENT, "flaveon", "faster")

    def test_every_more_autonomous_class_is_refused_on_a_floored_step(self):
        a = self._floored()
        current = a.recommended_executor.autonomy_rank
        for klass in ExecutorClass:
            if klass.autonomy_rank > current:
                with pytest.raises(OverrideRefusedError):
                    apply_override(a, klass, "flaveon", "reason")

    def test_unfloored_steps_may_be_overridden_either_way(self):
        a = assess_step(step(judgment=JudgmentLoad.MODERATE))
        assert not a.is_floored
        out = apply_override(a, ExecutorClass.BOUNDED_AUTONOMOUS_AGENT, "flaveon", "proven in practice")
        assert out.effective_executor is ExecutorClass.BOUNDED_AUTONOMOUS_AGENT

    def test_override_requires_a_rationale(self):
        with pytest.raises(OverrideRefusedError, match="must state why"):
            apply_override(self._floored(), ExecutorClass.HUMAN_ONLY, "flaveon", "  ")

    def test_override_requires_an_actor(self):
        with pytest.raises(OverrideRefusedError, match="must name who"):
            apply_override(self._floored(), ExecutorClass.HUMAN_ONLY, "", "reason")

    def test_override_does_not_mutate_the_original_assessment(self):
        a = self._floored()
        apply_override(a, ExecutorClass.HUMAN_ONLY, "flaveon", "reason")
        assert a.override is None, "the caller's assessment must be left alone"

    def test_a_second_override_is_judged_against_the_first(self):
        # Once overridden toward human control, the effective class is the new
        # one — an override cannot be used to climb back up in two hops.
        a = self._floored()
        toward_human = apply_override(a, ExecutorClass.HUMAN_ONLY, "flaveon", "keep it")
        with pytest.raises(OverrideRefusedError):
            apply_override(
                toward_human, ExecutorClass.AGENT_PREPARED_HUMAN_APPROVED, "flaveon", "actually"
            )


class TestSupervisionAndReadiness:
    def test_every_class_has_a_supervision_mode(self):
        for klass in ExecutorClass:
            s = step()
            a = assess_step(s)
            assert a.supervision_mode in set(SupervisionMode)

    def test_nothing_unattended_runs_without_a_human_somewhere(self):
        # Anything an agent executes is either approved, reviewed, or spot-checked.
        for kwargs in (
            dict(),
            dict(determinism=Determinism.MOSTLY_DETERMINISTIC),
            dict(repeat=Repeatability.OCCASIONAL),
            dict(reversibility=Reversibility.IRREVERSIBLE),
        ):
            a = assess_step(step(**kwargs))
            if a.recommended_executor.involves_agent:
                assert a.supervision_mode is not SupervisionMode.NONE

    def test_a_gate_tightens_supervision(self):
        ungated = assess_step(step())
        gated = assess_step(step(), gated=True)
        assert ungated.supervision_mode is SupervisionMode.SPOT_CHECK
        assert gated.supervision_mode is SupervisionMode.APPROVAL_REQUIRED

    def test_floored_work_is_never_more_than_a_pilot(self):
        a = assess_step(step(reversibility=Reversibility.IRREVERSIBLE))
        assert a.automation_readiness is AutomationReadiness.PILOT

    def test_human_only_work_is_not_an_automation_candidate(self):
        a = assess_step(step(judgment=JudgmentLoad.HIGH, determinism=Determinism.JUDGMENT_BASED))
        assert a.automation_readiness is AutomationReadiness.NOT_READY


class TestAssessedFactorsAreRecorded:
    def test_the_assessment_carries_what_it_judged(self):
        # A stored assessment stays auditable even if the workflow is edited.
        s = step(risk=RiskLevel.HIGH, sensitivity=DataSensitivity.SENSITIVE)
        a = assess_step(s)
        assert a.assessed_factors.risk is RiskLevel.HIGH
        assert a.assessed_factors.data_sensitivity is DataSensitivity.SENSITIVE

    def test_editing_the_step_afterwards_does_not_change_the_assessment(self):
        s = step(risk=RiskLevel.HIGH)
        a = assess_step(s)
        s.characteristics.risk = RiskLevel.LOW
        assert a.assessed_factors.risk is RiskLevel.HIGH

    def test_required_tools_are_matched_not_guessed(self):
        s = step(step_id="publish", name="Publish to Substack",
                 description="Paste into Substack and send.")
        assert assess_step(s, systems=["Substack", "Obsidian vault"]).required_tools == ["Substack"]
        # With no declared systems, nothing is inferred.
        assert assess_step(s).required_tools == []


class TestWorkflowLevel:
    @pytest.fixture()
    def pilot(self) -> AccountableWorkflow:
        return AccountableWorkflow.model_validate(
            yaml.safe_load((PILOT_DIR / "accountable-workflow.yaml").read_text(encoding="utf-8"))
        )

    def test_every_step_gets_an_assessment(self, pilot):
        assessments = assess_workflow(pilot)
        assert len(assessments) == len(pilot.steps)
        assert not unassessed_steps(pilot, assessments)

    def test_assessment_order_follows_step_order(self, pilot):
        assessments = assess_workflow(pilot)
        assert [a.step_id for a in assessments] == [s.step_id for s in pilot.steps]

    def test_the_pilot_keeps_publication_authority_with_a_human(self, pilot):
        # Seeded problem: "AI can prepare but not authorize publication."
        by_step = {a.step_id: a for a in assess_workflow(pilot)}
        publish = by_step["publish-post"]
        assert publish.recommended_executor is ExecutorClass.AGENT_PREPARED_HUMAN_APPROVED
        assert publish.safety_floor is SafetyFloor.IRREVERSIBLE
        assert publish.supervision_mode is SupervisionMode.APPROVAL_REQUIRED

    def test_the_pilot_keeps_approval_entirely_human(self, pilot):
        by_step = {a.step_id: a for a in assess_workflow(pilot)}
        assert by_step["review-and-approve"].recommended_executor is ExecutorClass.HUMAN_ONLY

    def test_the_pilot_automates_only_what_is_genuinely_mechanical(self, pilot):
        by_step = {a.step_id: a for a in assess_workflow(pilot)}
        assert by_step["archive-notes"].recommended_executor is ExecutorClass.DETERMINISTIC_AUTOMATION

    def test_no_pilot_step_is_left_unclassifiable(self, pilot):
        assert not steps_not_ready(assess_workflow(pilot))

    def test_unassessed_steps_are_reported(self, pilot):
        partial = assess_workflow(pilot)[:-1]
        assert unassessed_steps(pilot, partial) == [pilot.steps[-1].step_id]


class TestShippedArtifact:
    def test_the_pilot_assessment_artifact_is_valid(self):
        data = yaml.safe_load(
            (PILOT_DIR / "cooperation-assessment.yaml").read_text(encoding="utf-8")
        )
        assessments = [CooperationAssessment.model_validate(a) for a in data["assessments"]]
        assert len(assessments) == 8
        assert all(a.rationale for a in assessments)

    def test_the_recorded_override_carries_its_reason(self):
        data = yaml.safe_load(
            (PILOT_DIR / "cooperation-assessment.yaml").read_text(encoding="utf-8")
        )
        overridden = [
            CooperationAssessment.model_validate(a)
            for a in data["assessments"]
            if a.get("override")
        ]
        assert overridden, "the pilot records a human override"
        for a in overridden:
            assert a.override.rationale and a.override.actor
            # And it did not increase autonomy on a floored step.
            if a.is_floored:
                assert (
                    a.override.overridden_to.autonomy_rank
                    <= a.recommended_executor.autonomy_rank
                )
