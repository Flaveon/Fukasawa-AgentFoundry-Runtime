# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Phase 5 tests — cooperative builder and export, the Gate E evidence.

Three tests here are the ones the phase-4 completion note singled out as easy
to get wrong, and each has a class of its own:

* ``TestExportRespectsEffectiveExecutor`` — an override is the human's
  decision and is what governs. Reading ``recommended_executor`` would silently
  hand a step back to the table.
* ``TestBoundedAutonomousAgentRequiresGate`` — the most autonomous class
  exports only behind an explicit approval gate.
* ``TestNotReadyNeverExportsToAnAgent`` — a step nobody has characterized well
  enough to assign must reach no agent at all.

Everything else is structure. Those three are the safety properties.
"""

from pathlib import Path

import pytest
import yaml

from src.foundry.generator import generate_packages
from src.foundry.workflow_export import (
    ExportRefusedError,
    build_cooperative_workflow,
    export_workflow,
    steps_kept_human,
)
from src.governance.cooperation import apply_override, assess_workflow
from src.schemas.cooperation import (
    CooperationAssessment,
    CooperativeWorkflow,
    ExecutorClass,
    StepAssignment,
)
from src.schemas.human_workflow import (
    AccountableWorkflow,
    ApprovalGate,
    DataSensitivity,
    Determinism,
    ExceptionPath,
    JudgmentLoad,
    PromotionLineage,
    Repeatability,
    Reversibility,
    RiskLevel,
    StepCharacteristics,
    StepOutput,
    WorkflowMaturity,
    WorkflowStep,
)
from src.schemas.workflow_brief import BriefStatus, TaskDepth

ROOT = Path(__file__).resolve().parent.parent
PILOT_DIR = ROOT / "examples" / "workflows" / "substack-publication"


# ---------------------------------------------------------------- fixtures


def step(
    step_id: str,
    *,
    actor: str = "operator",
    next_steps: list[str] | None = None,
    judgment: JudgmentLoad = JudgmentLoad.NONE,
    repeat: Repeatability = Repeatability.ROUTINE,
    determinism: Determinism = Determinism.DETERMINISTIC,
    risk: RiskLevel = RiskLevel.LOW,
    reversibility: Reversibility = Reversibility.REVERSIBLE,
    sensitivity: DataSensitivity = DataSensitivity.PUBLIC,
    **kw,
) -> WorkflowStep:
    """A characterized step. Defaults land on DETERMINISTIC_AUTOMATION."""
    return WorkflowStep(
        step_id=step_id,
        name=step_id,
        actor=actor,
        decision_authority=kw.pop("authority", actor),
        next_steps=next_steps if next_steps is not None else [],
        outputs=kw.pop(
            "outputs",
            [StepOutput(name="result", artifact_type="file", evidence_requirement="the file exists")],
        ),
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


def workflow(steps: list[WorkflowStep], *, gates: list[ApprovalGate] | None = None) -> AccountableWorkflow:
    """A minimal promoted workflow wrapping the given steps."""
    return AccountableWorkflow(
        workflow_id="test-flow",
        name="Test Flow",
        maturity=WorkflowMaturity.COOPERATION_READY,
        purpose="exercise the export",
        trigger="a test runs",
        owners=["operator", "reviewer"],
        steps=steps,
        gates=gates or [],
        completion_contract="every step reached its declared state",
        exception_policy="stop and ask the operator",
        lineage=PromotionLineage(
            source_workflow_id="test-flow",
            source_version="1",
            from_maturity=WorkflowMaturity.MAPPED,
            to_maturity=WorkflowMaturity.ACCOUNTABLE,
            promoted_by="operator",
        ),
    )


def assignment(step_id: str, executor: ExecutorClass, **kw) -> StepAssignment:
    """A hand-built assignment, for testing export in isolation of the builder."""
    return StepAssignment(
        step_id=step_id,
        executor_class=executor,
        executor_identity=kw.pop("executor_identity", f"{step_id}-agent"),
        human_owner=kw.pop("human_owner", "operator"),
        escalation_target=kw.pop("escalation_target", "reviewer"),
        evidence_output=kw.pop("evidence_output", "the file exists"),
        **kw,
    )


def cooperative(assignments: list[StepAssignment], *, approved_by: str = "flaveon") -> CooperativeWorkflow:
    """An approved cooperative workflow wrapping the given assignments."""
    return CooperativeWorkflow(
        workflow_id="test-flow",
        name="Test Flow",
        assignments=assignments,
        approved_by=approved_by,
    )


@pytest.fixture()
def pilot() -> AccountableWorkflow:
    """The Substack pilot, promoted to COOPERATION_READY."""
    return AccountableWorkflow.model_validate(
        yaml.safe_load((PILOT_DIR / "accountable-workflow.yaml").read_text(encoding="utf-8"))
    )


@pytest.fixture()
def pilot_assessments() -> list[CooperationAssessment]:
    """The pilot's stage-4 artifact, including its one recorded override."""
    raw = yaml.safe_load((PILOT_DIR / "cooperation-assessment.yaml").read_text(encoding="utf-8"))
    return [CooperationAssessment.model_validate(a) for a in raw["assessments"]]


# ------------------------------------------------- the three safety properties


class TestExportRespectsEffectiveExecutor:
    """An override governs. The table only recommends."""

    def test_export_follows_the_override_not_the_recommendation(self):
        # The table would put this step on an agent; the human says no.
        steps = [step("s1", next_steps=[])]
        assessments = assess_workflow(workflow(steps))
        assert assessments[0].recommended_executor is ExecutorClass.DETERMINISTIC_AUTOMATION

        overridden = apply_override(
            assessments[0],
            ExecutorClass.HUMAN_ONLY,
            actor="flaveon",
            rationale="this one stays with me",
        )
        assert overridden.recommended_executor is ExecutorClass.DETERMINISTIC_AUTOMATION
        assert overridden.effective_executor is ExecutorClass.HUMAN_ONLY

        coop = build_cooperative_workflow(workflow(steps), [overridden], approved_by="flaveon")
        assert coop.assignments[0].executor_class is ExecutorClass.HUMAN_ONLY

        brief = export_workflow(coop, workflow(steps))
        # The recommendation would have produced a ROUTINE agent-owned
        # transition and an agent package. The override produced neither.
        assert brief.agents == []
        assert brief.transitions[0].depth is TaskDepth.CONSCIOUS
        assert brief.transitions[0].owner == "operator"

    def test_override_toward_autonomy_is_also_honoured(self):
        # The rule is one-directional at assessment time, not at export time:
        # on an unfloored step a human may widen, and export must follow that
        # too. Reading recommended_executor would silently narrow it back.
        steps = [step("s1", judgment=JudgmentLoad.HIGH, next_steps=[])]
        assessments = assess_workflow(workflow(steps))
        assert assessments[0].recommended_executor is ExecutorClass.HUMAN_ONLY

        overridden = apply_override(
            assessments[0],
            ExecutorClass.DETERMINISTIC_AUTOMATION,
            actor="flaveon",
            rationale="we wrote a script for this last month",
        )
        coop = build_cooperative_workflow(workflow(steps), [overridden], approved_by="flaveon")
        brief = export_workflow(coop, workflow(steps))

        assert [a.agent_name for a in brief.agents] == ["s1-agent"]
        assert brief.transitions[0].depth is TaskDepth.ROUTINE

    def test_pilot_override_reaches_the_export(self, pilot, pilot_assessments):
        # request-artwork is AGENT_EXECUTED_HUMAN_SUPERVISED by the table and
        # HUMAN_LED_AI_ASSISTED by the operator's recorded decision.
        recorded = next(a for a in pilot_assessments if a.step_id == "request-artwork")
        assert recorded.recommended_executor is ExecutorClass.AGENT_EXECUTED_HUMAN_SUPERVISED
        assert recorded.effective_executor is ExecutorClass.HUMAN_LED_AI_ASSISTED

        coop = build_cooperative_workflow(pilot, pilot_assessments, approved_by="flaveon")
        assert coop.assignment("request-artwork").executor_class is ExecutorClass.HUMAN_LED_AI_ASSISTED

        brief = export_workflow(coop, pilot)
        # Had export read the recommendation, this step would have produced a
        # request-artwork-agent package.
        assert "request-artwork-agent" not in [a.agent_name for a in brief.agents]


class TestBoundedAutonomousAgentRequiresGate:
    """The most autonomous class exports only behind an explicit gate."""

    def test_export_refused_without_an_approval_gate(self):
        steps = [step("s1", next_steps=[])]
        coop = cooperative(
            [assignment("s1", ExecutorClass.BOUNDED_AUTONOMOUS_AGENT, approval_gate="")]
        )
        with pytest.raises(ExportRefusedError) as exc:
            export_workflow(coop, workflow(steps))
        assert "BOUNDED_AUTONOMOUS_AGENT" in str(exc.value)
        assert "s1" in str(exc.value)

    def test_export_allowed_with_a_gate_and_splits_at_it(self):
        steps = [step("s1", next_steps=["s2"]), step("s2", next_steps=[])]
        coop = cooperative(
            [
                assignment("s1", ExecutorClass.BOUNDED_AUTONOMOUS_AGENT, approval_gate="g1"),
                assignment("s2", ExecutorClass.HUMAN_ONLY, executor_identity="operator"),
            ]
        )
        brief = export_workflow(coop, workflow(steps))

        assert "s1-pending-approval" in brief.states
        agent_half = next(t for t in brief.transitions if t.from_state == "s1")
        human_half = next(t for t in brief.transitions if t.from_state == "s1-pending-approval")

        assert agent_half.to_state == "s1-pending-approval"
        assert agent_half.owner == "s1-agent"
        assert human_half.owner == "operator"
        # CONSCIOUS is what makes the runtime pause: a gate that does not stop
        # execution is not a gate.
        assert human_half.depth is TaskDepth.CONSCIOUS

    def test_the_agent_never_owns_the_conscious_half(self):
        # WorkflowBrief refuses an agent-owned CONSCIOUS transition outright,
        # so this is belt and braces — but it is the exact doctrine the split
        # exists to respect, and it should fail loudly if the split regresses.
        steps = [step("s1", next_steps=[])]
        coop = cooperative(
            [assignment("s1", ExecutorClass.BOUNDED_AUTONOMOUS_AGENT, approval_gate="g1")]
        )
        brief = export_workflow(coop, workflow(steps))
        agent_names = {a.agent_name for a in brief.agents}
        conscious_owners = {
            t.owner for t in brief.transitions if brief.depth_of(t) is TaskDepth.CONSCIOUS
        }
        assert not (conscious_owners & agent_names)


class TestNotReadyNeverExportsToAnAgent:
    """A step nobody has characterized well enough to assign stays human."""

    def test_no_agent_spec_is_emitted(self):
        steps = [step("s1", next_steps=[])]
        coop = cooperative(
            [
                assignment(
                    "s1",
                    ExecutorClass.NOT_READY_FOR_AUTOMATION,
                    executor_identity="",
                    human_owner="operator",
                )
            ]
        )
        brief = export_workflow(coop, workflow(steps))
        assert brief.agents == []

    def test_the_transition_is_owned_by_the_human(self):
        steps = [step("s1", next_steps=[])]
        coop = cooperative(
            [assignment("s1", ExecutorClass.NOT_READY_FOR_AUTOMATION, executor_identity="")]
        )
        brief = export_workflow(coop, workflow(steps))
        assert brief.transitions[0].owner == "operator"
        assert brief.transitions[0].depth is TaskDepth.CONSCIOUS

    def test_unknown_characteristics_reach_export_as_human_work(self):
        # The realistic route in: an uncharacterized step floors at
        # NOT_READY_FOR_AUTOMATION, and that must survive all the way out.
        uncharacterized = WorkflowStep(
            step_id="s1", name="s1", actor="operator", decision_authority="operator"
        )
        wf = workflow([uncharacterized])
        assessments = assess_workflow(wf)
        assert assessments[0].effective_executor is ExecutorClass.NOT_READY_FOR_AUTOMATION

        coop = build_cooperative_workflow(wf, assessments, approved_by="flaveon")
        brief = export_workflow(coop, wf)

        assert brief.agents == []
        assert coop.required_agent_packages == []
        assert coop.assignment("s1").executor_identity == ""
        assert "s1" in steps_kept_human(coop)


# ------------------------------------------------------------- the build stage


class TestBuild:
    def test_every_step_is_assigned(self, pilot, pilot_assessments):
        coop = build_cooperative_workflow(pilot, pilot_assessments, approved_by="flaveon")
        assert [a.step_id for a in coop.assignments] == [s.step_id for s in pilot.steps]

    def test_build_refuses_an_unassessed_step(self, pilot, pilot_assessments):
        with pytest.raises(ExportRefusedError) as exc:
            build_cooperative_workflow(pilot, pilot_assessments[:-1], approved_by="flaveon")
        assert "archive-notes" in str(exc.value)

    def test_every_assignment_names_a_human_owner_and_escalation_target(
        self, pilot, pilot_assessments
    ):
        # Including the fully automated ones. Automation moves the work, never
        # the accountability.
        coop = build_cooperative_workflow(pilot, pilot_assessments, approved_by="flaveon")
        for a in coop.assignments:
            assert a.human_owner.strip()
            assert a.escalation_target.strip()
            assert a.escalation_target != a.human_owner or len(pilot.owners) == 1

    def test_fallback_is_always_human(self, pilot, pilot_assessments):
        coop = build_cooperative_workflow(pilot, pilot_assessments, approved_by="flaveon")
        assert all(a.fallback_executor is ExecutorClass.HUMAN_ONLY for a in coop.assignments)

    def test_tools_are_matched_never_inferred(self, pilot, pilot_assessments):
        # The pilot's assessments declare no required tools, so no assignment
        # may claim any. Guessing would put unearned confidence into an agent's
        # permissions.
        coop = build_cooperative_workflow(pilot, pilot_assessments, approved_by="flaveon")
        assert all(a.allowed_tools == [] for a in coop.assignments)

    def test_agent_owned_steps_state_their_prohibitions(self, pilot, pilot_assessments):
        coop = build_cooperative_workflow(pilot, pilot_assessments, approved_by="flaveon")
        publish = coop.assignment("publish-post")
        assert any("depth level" in p for p in publish.prohibited_actions)
        assert any("approval gate" in p for p in publish.prohibited_actions)

    def test_unapproved_by_default(self, pilot, pilot_assessments):
        coop = build_cooperative_workflow(pilot, pilot_assessments)
        assert not coop.approved


# ------------------------------------------------------------ the export stage


class TestExportRefusals:
    def test_unapproved_workflow_is_refused(self):
        steps = [step("s1", next_steps=[])]
        coop = cooperative([assignment("s1", ExecutorClass.HUMAN_ONLY)], approved_by="")
        with pytest.raises(ExportRefusedError) as exc:
            export_workflow(coop, workflow(steps))
        assert "approved_by" in str(exc.value)

    def test_unassigned_step_is_refused(self):
        steps = [step("s1", next_steps=["s2"]), step("s2", next_steps=[])]
        coop = cooperative([assignment("s1", ExecutorClass.HUMAN_ONLY)])
        with pytest.raises(ExportRefusedError) as exc:
            export_workflow(coop, workflow(steps))
        assert "s2" in str(exc.value)


class TestExportStructure:
    def test_each_step_becomes_a_state(self, pilot, pilot_assessments):
        coop = build_cooperative_workflow(pilot, pilot_assessments, approved_by="flaveon")
        brief = export_workflow(coop, pilot)
        for s in pilot.steps:
            assert s.step_id in brief.states

    def test_the_first_step_is_the_initial_state(self, pilot, pilot_assessments):
        coop = build_cooperative_workflow(pilot, pilot_assessments, approved_by="flaveon")
        brief = export_workflow(coop, pilot)
        assert brief.initial_state == pilot.steps[0].step_id

    def test_a_terminal_step_reaches_a_completion_state(self, pilot, pilot_assessments):
        coop = build_cooperative_workflow(pilot, pilot_assessments, approved_by="flaveon")
        brief = export_workflow(coop, pilot)
        assert "complete" in brief.states
        assert any(t.from_state == "archive-notes" and t.to_state == "complete" for t in brief.transitions)

    def test_completion_state_avoids_a_colliding_step_name(self):
        steps = [step("complete", next_steps=[])]
        coop = cooperative([assignment("complete", ExecutorClass.HUMAN_ONLY)])
        brief = export_workflow(coop, workflow(steps))
        assert "workflow-complete" in brief.states

    def test_evidence_requirement_carries_from_the_step_output(self, pilot, pilot_assessments):
        coop = build_cooperative_workflow(pilot, pilot_assessments, approved_by="flaveon")
        brief = export_workflow(coop, pilot)
        leaving_publish = next(t for t in brief.transitions if t.from_state == "publish-post" and t.to_state != "publish-post")
        assert "live post URL" in leaving_publish.evidence_required

    def test_declared_recovery_paths_become_transitions(self, pilot, pilot_assessments):
        coop = build_cooperative_workflow(pilot, pilot_assessments, approved_by="flaveon")
        brief = export_workflow(coop, pilot)
        # The gate's on_reject loop: a rehearsed recovery must not be a
        # non-conformance at runtime.
        assert any(
            t.from_state == "review-and-approve" and t.to_state == "draft-article"
            for t in brief.transitions
        )

    def test_one_transition_per_state_pair(self, pilot, pilot_assessments):
        # The runtime resolves a move by the first matching pair, so a second
        # transition on the same pair would be unreachable — its owner and
        # evidence requirement silently dead.
        coop = build_cooperative_workflow(pilot, pilot_assessments, approved_by="flaveon")
        brief = export_workflow(coop, pilot)
        pairs = [(t.from_state, t.to_state) for t in brief.transitions]
        assert len(pairs) == len(set(pairs))

    def test_a_recovery_onto_a_declared_path_keeps_the_declared_edge(self):
        steps = [
            step(
                "s1",
                next_steps=["s2"],
                exception_paths=[
                    ExceptionPath(
                        failure_mode="it went sideways",
                        owner="reviewer",
                        handling="skip ahead",
                        next_step="s2",
                    )
                ],
            ),
            step("s2", next_steps=[]),
        ]
        coop = cooperative(
            [
                assignment("s1", ExecutorClass.DETERMINISTIC_AUTOMATION),
                assignment("s2", ExecutorClass.HUMAN_ONLY),
            ]
        )
        brief = export_workflow(coop, workflow(steps))
        edges = [t for t in brief.transitions if (t.from_state, t.to_state) == ("s1", "s2")]
        assert len(edges) == 1
        # The declared path wins, so the evidence requirement survives. The
        # recovery is still possible; it asks for more, never less.
        assert edges[0].owner == "s1-agent"
        assert edges[0].evidence_required == "the file exists"

    def test_approved_workflow_exports_an_approved_brief(self, pilot, pilot_assessments):
        coop = build_cooperative_workflow(pilot, pilot_assessments, approved_by="flaveon")
        brief = export_workflow(coop, pilot)
        assert brief.status is BriefStatus.APPROVED


class TestDepthMapping:
    @pytest.mark.parametrize(
        "executor,depth",
        [
            (ExecutorClass.NOT_READY_FOR_AUTOMATION, TaskDepth.CONSCIOUS),
            (ExecutorClass.HUMAN_ONLY, TaskDepth.CONSCIOUS),
            (ExecutorClass.HUMAN_LED_AI_ASSISTED, TaskDepth.GUIDED),
            (ExecutorClass.AGENT_PREPARED_HUMAN_APPROVED, TaskDepth.GUIDED),
            (ExecutorClass.DETERMINISTIC_AUTOMATION, TaskDepth.ROUTINE),
            (ExecutorClass.AGENT_EXECUTED_HUMAN_SUPERVISED, TaskDepth.GUIDED),
        ],
    )
    def test_executor_class_maps_to_its_declared_depth(self, executor, depth):
        steps = [step("s1", next_steps=[])]
        coop = cooperative([assignment("s1", executor)])
        brief = export_workflow(coop, workflow(steps))
        leaving = next(t for t in brief.transitions if t.from_state == "s1")
        assert leaving.depth is depth

    @pytest.mark.parametrize(
        "executor,level",
        [
            (ExecutorClass.DETERMINISTIC_AUTOMATION, 0),
            (ExecutorClass.AGENT_PREPARED_HUMAN_APPROVED, 2),
            (ExecutorClass.AGENT_EXECUTED_HUMAN_SUPERVISED, 2),
        ],
    )
    def test_agent_depth_level_follows_the_executor_class(self, executor, level):
        steps = [step("s1", next_steps=[])]
        coop = cooperative([assignment("s1", executor)])
        brief = export_workflow(coop, workflow(steps))
        assert brief.agents[0].depth_level == level

    def test_no_exported_agent_is_ever_level_five(self, pilot, pilot_assessments):
        # Level 5 is redesign-only and the generator refuses it outright, so an
        # export that could produce one would be unbuildable.
        coop = build_cooperative_workflow(pilot, pilot_assessments, approved_by="flaveon")
        brief = export_workflow(coop, pilot)
        assert all(a.depth_level <= 3 for a in brief.agents)

    def test_human_led_ai_assisted_declares_no_agent(self):
        # A person does the work and AI helps, so the human owns the
        # transition. An AgentSpec here would own nothing, and the generator
        # refuses an agent that owns no transitions.
        steps = [step("s1", next_steps=[])]
        coop = cooperative(
            [assignment("s1", ExecutorClass.HUMAN_LED_AI_ASSISTED, executor_identity="operator")]
        )
        brief = export_workflow(coop, workflow(steps))
        assert brief.agents == []


class TestFeedsTheExistingGenerator:
    """Phase 5 consumes the proven build path unchanged."""

    def test_exported_brief_generates_agent_packages(self, pilot, pilot_assessments, tmp_path):
        coop = build_cooperative_workflow(pilot, pilot_assessments, approved_by="flaveon")
        brief = export_workflow(coop, pilot)

        packages, report = generate_packages(
            brief, tmp_path / "out", explicit_paths={
                "context": "context/",
                "tasks_ready": "tasks/ready/",
                "tasks_blocked": "tasks/blocked/",
                "outputs": "outputs/",
                "logs": "logs/",
                "agent_config": "agents/",
                "archive": "archive/",
            }
        )
        assert report.exists()
        assert {p.name for p in packages} == set(coop.required_agent_packages)
        for pkg in packages:
            assert (pkg / "SKILL.md").exists()
            assert (pkg / "CONTRACT.md").exists()
            assert (pkg / "process_capsule.yaml").exists()

    def test_every_declared_agent_owns_at_least_one_transition(self, pilot, pilot_assessments):
        # generate_packages refuses an agent that owns nothing, so the export
        # must never declare one.
        coop = build_cooperative_workflow(pilot, pilot_assessments, approved_by="flaveon")
        brief = export_workflow(coop, pilot)
        for agent in brief.agents:
            assert [t for t in brief.transitions if t.owner == agent.agent_name]


class TestDeterminism:
    def test_the_same_inputs_always_export_the_same_brief(self, pilot, pilot_assessments):
        # No clock, no uuid, no model in the export path: two runs must be
        # byte-identical or the artifact cannot be reviewed by diff.
        first = export_workflow(
            build_cooperative_workflow(pilot, pilot_assessments, approved_by="flaveon"), pilot
        )
        second = export_workflow(
            build_cooperative_workflow(pilot, pilot_assessments, approved_by="flaveon"), pilot
        )
        assert first.model_dump() == second.model_dump()
