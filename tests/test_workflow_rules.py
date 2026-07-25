# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Phase 2 validator tests — the Gate C evidence.

Every rule gets both halves of the required pair:

* **negative** — the rule stays silent on ``clean-workflow.yaml``, a realistic
  well-formed workflow. This is the false-positive guard: the baseline is a
  plausible real workflow rather than a stub, so a rule that over-fires is
  caught here.
* **positive** — a *copy* of that same baseline with exactly one defect
  introduced. Because only one thing changed, a fired finding is attributable
  to that defect, and the assertion can check the exact rule id, location,
  field, severity, and blocking policy.

Cross-cutting tests cover determinism, finding-id uniqueness, the blocking
table matching the approved directive, and behavior on a sparse real-world
capture where nothing is characterized.
"""

from pathlib import Path

import pytest
import yaml

from src.governance.workflow_rules import (
    BLOCKING_RULE_IDS,
    RULES,
    WorkflowIndex,
    validate_workflow,
)
from src.schemas.findings import Severity
from src.schemas.human_workflow import (
    ApprovalGate,
    ExceptionPath,
    HumanWorkflowDraft,
    RiskLevel,
    StepInput,
    StepOutput,
    WorkflowStep,
)

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "workflows"
CLEAN = FIXTURES / "clean-workflow.yaml"
SPARSE = FIXTURES / "uncharacterized-workflow.yaml"
PILOT = ROOT / "examples" / "workflows" / "substack-publication" / "observed-workflow.yaml"

#: The blocking policy fixed by the approved Codex directive §4. This table is
#: the contract; if a rule's policy drifts from it, that is a defect.
EXPECTED_BLOCKING = {
    "HW-001": True, "HW-002": True, "HW-003": True, "HW-004": True,
    "HW-005": True, "HW-006": True, "HW-007": True, "HW-008": True,
    "HW-009": True, "HW-010": True, "HW-011": True, "HW-012": True,
    "HW-013": False, "HW-014": False, "HW-015": True, "HW-016": True,
}


def _load(path: Path) -> HumanWorkflowDraft:
    """Load a fixture workflow."""
    return HumanWorkflowDraft.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@pytest.fixture()
def clean() -> HumanWorkflowDraft:
    """A well-formed workflow that reports zero findings."""
    return _load(CLEAN)


def _fired(draft: HumanWorkflowDraft, rule_id: str):
    """Findings from one rule only, so a positive test cannot be polluted."""
    return validate_workflow(draft, rule_ids=[rule_id]).findings


def _assert_silent(draft: HumanWorkflowDraft, rule_id: str) -> None:
    """The rule must not fire on this (valid) workflow."""
    found = _fired(draft, rule_id)
    assert found == [], f"{rule_id} false positive: {[f.message for f in found]}"


# ------------------------------------------------------------------ baseline


class TestBaselineIsClean:
    def test_clean_fixture_reports_nothing_at_all(self, clean):
        # The single most important test in this file: a good workflow must
        # produce an empty report, or operators will learn to ignore findings.
        report = validate_workflow(clean)
        assert report.findings == [], [f.message for f in report.findings]
        assert report.promotion_ready

    def test_registry_matches_the_approved_blocking_table(self):
        assert set(RULES) == set(EXPECTED_BLOCKING)
        for rule_id, blocking in EXPECTED_BLOCKING.items():
            assert RULES[rule_id].blocking is blocking, f"{rule_id} policy drifted"

    def test_blocking_count_is_fourteen_of_sixteen(self):
        assert len(RULES) == 16
        assert len(BLOCKING_RULE_IDS) == 14

    def test_severity_agrees_with_blocking_policy(self):
        for rule in RULES.values():
            expected = Severity.ERROR if rule.blocking else Severity.WARNING
            assert rule.severity is expected, f"{rule.rule_id} severity/policy mismatch"

    def test_every_rule_has_actionable_metadata(self):
        for rule in RULES.values():
            assert rule.title and rule.description and rule.remediation
            assert rule.version


# ------------------------------------------------------------- per-rule pairs


class TestHW001UndefinedTrigger:
    def test_silent_when_trigger_is_stated(self, clean):
        _assert_silent(clean, "HW-001")

    def test_fires_when_trigger_is_empty(self, clean):
        clean.trigger = ""
        found = _fired(clean, "HW-001")
        assert len(found) == 1
        assert found[0].rule.rule_id == "HW-001"
        assert found[0].location.field == "trigger"
        assert found[0].blocking and found[0].severity is Severity.ERROR
        assert found[0].remediation

    def test_placeholder_counts_as_undefined(self, clean):
        clean.trigger = "TBD"
        assert len(_fired(clean, "HW-001")) == 1


class TestHW002UndefinedOutcome:
    def test_silent_on_complete_workflow(self, clean):
        _assert_silent(clean, "HW-002")

    def test_fires_when_outcome_missing(self, clean):
        clean.claimed_outcome = ""
        found = _fired(clean, "HW-002")
        assert [f.location.field for f in found] == ["claimed_outcome"]

    def test_fires_separately_when_nothing_terminates(self, clean):
        # Make every reachable step lead somewhere: no terminal step remains.
        clean.step("pay-claim").next_steps = ["review-claim"]
        clean.step("decline-claim").next_steps = ["review-claim"]
        found = _fired(clean, "HW-002")
        assert [f.location.field for f in found] == ["steps"]
        assert "never terminates" in found[0].message

    def test_two_distinct_defects_yield_two_findings(self, clean):
        clean.claimed_outcome = ""
        clean.step("pay-claim").next_steps = ["review-claim"]
        clean.step("decline-claim").next_steps = ["review-claim"]
        found = _fired(clean, "HW-002")
        assert len(found) == 2
        assert len({f.finding_id for f in found}) == 2


class TestHW003MissingStepOwner:
    def test_silent_when_every_step_is_owned(self, clean):
        _assert_silent(clean, "HW-003")

    def test_fires_per_unowned_step(self, clean):
        clean.step("pay-claim").actor = ""
        clean.step("decline-claim").actor = "  "
        found = _fired(clean, "HW-003")
        assert {f.location.step_id for f in found} == {"pay-claim", "decline-claim"}
        assert all(f.location.field == "actor" and f.blocking for f in found)


class TestHW004DecisionAuthority:
    def test_silent_when_authority_is_named(self, clean):
        _assert_silent(clean, "HW-004")

    def test_fires_on_branching_step_without_authority(self, clean):
        clean.step("review-claim").decision_authority = ""   # 2 next_steps
        found = _fired(clean, "HW-004")
        assert [f.location.step_id for f in found] == ["review-claim"]
        assert found[0].blocking

    def test_fires_on_ambiguous_authority(self, clean):
        clean.step("review-claim").decision_authority = "the team"
        found = _fired(clean, "HW-004")
        assert "ambiguous" in found[0].message
        assert found[0].location.detail == "the team"

    def test_fires_on_high_risk_step_without_authority(self, clean):
        step = clean.step("submit-claim")             # linear, but make it risky
        step.decision_authority = ""
        step.characteristics.risk = RiskLevel.HIGH
        assert [f.location.step_id for f in _fired(clean, "HW-004")] == ["submit-claim"]

    def test_does_not_demand_authority_from_a_purely_linear_step(self, clean):
        # The deliberate narrowing: a step that always does the same next thing
        # decides nothing, so requiring an authority would be noise.
        step = clean.step("submit-claim")
        step.decision_authority = ""
        assert step.next_steps == ["review-claim"]
        _assert_silent(clean, "HW-004")

    def test_fires_on_gate_without_approver(self, clean):
        clean.gates[0].approver = ""
        found = _fired(clean, "HW-004")
        assert found[0].location.gate_id == "finance-approval"


class TestHW005DanglingReference:
    def test_silent_when_all_routes_resolve(self, clean):
        _assert_silent(clean, "HW-005")

    def test_fires_on_unknown_next_step(self, clean):
        clean.step("pay-claim").next_steps = ["archive-it"]
        found = _fired(clean, "HW-005")
        assert found[0].location.detail == "archive-it"
        assert found[0].location.field == "next_steps"

    def test_fires_on_unknown_exception_target(self, clean):
        clean.step("review-claim").exception_paths[0].next_step = "nowhere"
        found = _fired(clean, "HW-005")
        assert found[0].location.field == "exception_paths.next_step"

    def test_fires_on_gate_pointing_nowhere(self, clean):
        clean.gates[0].on_approve = "ghost-step"
        found = _fired(clean, "HW-005")
        assert found[0].location.field == "on_approve"

    def test_ignores_reject_text_that_is_not_a_step_id(self, clean):
        # on_reject may hold a stated action; HW-015 judges it, not HW-005.
        clean.gates[0].on_reject = "send it back to the employee with a note"
        _assert_silent(clean, "HW-005")


class TestHW006UnreachableStep:
    def test_silent_when_everything_is_reachable(self, clean):
        _assert_silent(clean, "HW-006")

    def test_fires_on_orphan_step(self, clean):
        clean.steps.append(WorkflowStep(step_id="orphan", name="Orphan", actor="x"))
        found = _fired(clean, "HW-006")
        assert [f.location.step_id for f in found] == ["orphan"]
        assert found[0].blocking

    def test_step_reachable_only_via_a_failure_path_is_still_reachable(self, clean):
        # Arriving by way of an exception is still arriving.
        clean.steps.append(
            WorkflowStep(
                step_id="fix-receipt", name="Fix receipt", actor="employee",
                outputs=[StepOutput(name="receipt", artifact_type="file", evidence_requirement="file exists")],
            )
        )
        clean.step("review-claim").exception_paths[0].next_step = "fix-receipt"
        _assert_silent(clean, "HW-006")

    def test_step_reachable_only_via_a_gate_approval_is_still_reachable(self, clean):
        clean.step("review-claim").next_steps = ["decline-claim"]  # drop direct route
        assert clean.gates[0].on_approve == "pay-claim"
        _assert_silent(clean, "HW-006")


class TestHW007DeadEnd:
    def test_silent_when_terminal_steps_produce_output(self, clean):
        _assert_silent(clean, "HW-007")

    def test_fires_when_a_step_produces_nothing_and_leads_nowhere(self, clean):
        clean.step("pay-claim").outputs = []
        found = _fired(clean, "HW-007")
        assert [f.location.step_id for f in found] == ["pay-claim"]
        assert "dead end" in found[0].message

    def test_fires_on_failure_with_neither_handling_nor_route(self, clean):
        exc = clean.step("review-claim").exception_paths[0]
        exc.handling = ""
        exc.next_step = None
        found = _fired(clean, "HW-007")
        assert found[0].location.field == "exception_paths"

    def test_terminal_step_with_output_is_not_a_dead_end(self, clean):
        assert clean.step("decline-claim").next_steps == []
        assert clean.step("decline-claim").outputs
        _assert_silent(clean, "HW-007")


class TestHW008ImplicitHandoff:
    def test_silent_when_handoff_carries_a_verifiable_artifact(self, clean):
        # submit-claim (employee) -> review-claim (finance-reviewer) is a real
        # cross-actor handoff, and it passes because the artifact is verifiable.
        assert clean.step("submit-claim").actor != clean.step("review-claim").actor
        _assert_silent(clean, "HW-008")

    def test_fires_when_cross_actor_handoff_has_no_verifiable_output(self, clean):
        clean.step("submit-claim").outputs = []
        found = _fired(clean, "HW-008")
        assert found[0].location.step_id == "submit-claim"
        assert found[0].location.detail == "review-claim"
        assert found[0].blocking

    def test_fires_when_output_lacks_evidence_requirement(self, clean):
        clean.step("submit-claim").outputs[0].evidence_requirement = ""
        assert len(_fired(clean, "HW-008")) == 1

    def test_same_actor_transition_is_not_a_handoff(self, clean):
        # review-claim -> pay-claim share an actor; stripping outputs must not
        # make it a handoff finding.
        clean.step("review-claim").outputs = []
        found = _fired(clean, "HW-008")
        assert all(f.location.detail != "pay-claim" for f in found)


class TestHW009MissingInputSource:
    def test_silent_when_sources_are_named(self, clean):
        _assert_silent(clean, "HW-009")

    def test_fires_on_required_input_without_source(self, clean):
        clean.step("review-claim").inputs[0].source = ""
        found = _fired(clean, "HW-009")
        assert found[0].location.field == "inputs.source"
        assert found[0].location.detail == "expense claim"

    def test_optional_input_without_source_is_not_reported(self, clean):
        clean.step("review-claim").inputs.append(
            StepInput(name="prior claims", source="", required=False)
        )
        _assert_silent(clean, "HW-009")


class TestHW010UnverifiableOutput:
    def test_silent_when_outputs_are_typed_and_verifiable(self, clean):
        _assert_silent(clean, "HW-010")

    def test_missing_type_and_missing_evidence_are_two_findings(self, clean):
        clean.step("pay-claim").outputs[0].artifact_type = ""
        clean.step("pay-claim").outputs[0].evidence_requirement = ""
        found = _fired(clean, "HW-010")
        assert {f.location.field for f in found} == {
            "outputs.artifact_type", "outputs.evidence_requirement",
        }
        assert len({f.finding_id for f in found}) == 2


class TestHW011UnhandledFailureMode:
    def test_silent_when_observed_failures_have_paths(self, clean):
        _assert_silent(clean, "HW-011")

    def test_fires_on_observed_failure_with_no_matching_path(self, clean):
        clean.observed_exceptions.append("The expense portal is down for maintenance.")
        found = _fired(clean, "HW-011")
        assert len(found) == 1
        assert "portal" in found[0].location.detail

    def test_reworded_failure_still_counts_as_handled(self, clean):
        # People never restate a failure the same way twice; word overlap is
        # what makes this rule usable rather than pedantic.
        clean.observed_exceptions = ["Receipt missing or illegible for a line item."]
        _assert_silent(clean, "HW-011")


class TestHW012UnownedException:
    def test_silent_when_exceptions_are_owned(self, clean):
        _assert_silent(clean, "HW-012")

    def test_fires_on_unowned_exception(self, clean):
        clean.step("review-claim").exception_paths[0].owner = ""
        found = _fired(clean, "HW-012")
        assert found[0].location.field == "exception_paths.owner"
        assert found[0].blocking

    def test_fires_on_ambiguous_exception_owner(self, clean):
        clean.step("review-claim").exception_paths[0].owner = "whoever"
        found = _fired(clean, "HW-012")
        assert "ambiguous" in found[0].message


class TestHW013MemoryDependency:
    def test_silent_when_nothing_is_unwritten(self, clean):
        _assert_silent(clean, "HW-013")

    def test_fires_per_unwritten_rule_but_never_blocks(self, clean):
        clean.unwritten_rules = ["Ask Dave before approving anything over 500."]
        found = _fired(clean, "HW-013")
        assert len(found) == 1
        # Non-blocking by design: recording an unwritten rule is honesty, and
        # punishing it would teach people to hide it.
        assert not found[0].blocking
        assert found[0].severity is Severity.WARNING
        assert not found[0].blocks_promotion

    def test_fires_on_memory_phrase_in_step_text(self, clean):
        clean.step("review-claim").description = "The reviewer just knows which vendors are fine."
        found = _fired(clean, "HW-013")
        assert found[0].location.field == "description"

    def test_does_not_block_promotion_even_unaccepted(self, clean):
        clean.unwritten_rules = ["Something nobody wrote down."]
        assert validate_workflow(clean).promotion_ready


class TestHW014AmbiguousCriteria:
    def test_silent_when_conditions_state_criteria(self, clean):
        _assert_silent(clean, "HW-014")

    def test_fires_on_feel_based_exit_condition(self, clean):
        clean.step("pay-claim").exit_condition = "Payment is done when it looks fine."
        found = _fired(clean, "HW-014")
        assert found[0].location.step_id == "pay-claim"
        assert not found[0].blocking

    def test_fires_on_gate_with_no_criteria(self, clean):
        clean.gates[0].criteria = ""
        found = _fired(clean, "HW-014")
        assert found[0].location.gate_id == "finance-approval"
        assert "no criteria" in found[0].message

    def test_text_with_a_real_criterion_is_left_alone(self, clean):
        # Contains "compliant"/"approved" language but also states a criterion,
        # so the rule must stay quiet — this is the false-positive edge.
        clean.step("pay-claim").exit_condition = (
            "The claim is approved when at least one reviewer has signed it."
        )
        _assert_silent(clean, "HW-014")

    def test_numeric_criterion_suppresses_the_finding(self, clean):
        clean.step("pay-claim").exit_condition = "Complete when all 3 receipts are attached."
        _assert_silent(clean, "HW-014")


class TestHW015GateWithoutNextAction:
    def test_silent_when_rejection_is_routed(self, clean):
        _assert_silent(clean, "HW-015")

    def test_fires_when_a_gate_cannot_say_what_no_means(self, clean):
        clean.gates[0].on_reject = ""
        found = _fired(clean, "HW-015")
        assert found[0].location.field == "on_reject"
        assert found[0].blocking

    def test_stated_action_counts_as_a_rejection_path(self, clean):
        clean.gates[0].on_reject = "return the claim to the employee with the reason"
        _assert_silent(clean, "HW-015")


class TestHW016UnsupportedCompletion:
    def test_silent_when_evidence_exists(self, clean):
        _assert_silent(clean, "HW-016")

    def test_fires_when_nothing_can_prove_the_claim(self, clean):
        for step in clean.steps:
            for out in step.outputs:
                out.evidence_requirement = ""
        found = _fired(clean, "HW-016")
        assert len(found) == 1
        assert found[0].location.field == "claimed_outcome"
        assert found[0].blocking

    def test_stays_quiet_when_the_outcome_itself_is_undefined(self, clean):
        # HW-002 owns that defect; reporting both would be two findings for one
        # root cause.
        clean.claimed_outcome = ""
        for step in clean.steps:
            for out in step.outputs:
                out.evidence_requirement = ""
        _assert_silent(clean, "HW-016")


# ------------------------------------------------------------- cross-cutting


class TestDeterminismAndIds:
    def test_two_runs_produce_identical_reports(self):
        pilot = _load(PILOT)
        a = validate_workflow(pilot).model_dump(exclude={"evaluated_at"})
        b = validate_workflow(pilot).model_dump(exclude={"evaluated_at"})
        assert a == b

    def test_finding_ids_are_unique_within_a_report(self):
        for path in (PILOT, SPARSE):
            report = validate_workflow(_load(path))
            ids = [f.finding_id for f in report.findings]
            assert len(ids) == len(set(ids)), f"duplicate finding ids in {path.name}"

    def test_finding_ids_locate_the_defect(self):
        report = validate_workflow(_load(PILOT), rule_ids=["HW-003"])
        assert report.findings[0].finding_id == "HW-003:publish-post/actor"

    def test_findings_are_sorted_by_rule_then_location(self):
        report = validate_workflow(_load(PILOT))
        keys = [
            (f.rule.rule_id, f.location.step_id, f.location.gate_id, f.location.field)
            for f in report.findings
        ]
        assert keys == sorted(keys)

    def test_every_finding_has_a_location_and_remediation(self):
        for f in validate_workflow(_load(PILOT)).findings:
            assert f.location.workflow_id
            assert f.location.step_id or f.location.gate_id or f.location.field
            assert f.remediation and f.message


class TestPilotReport:
    """The pilot must actually catch its seeded problems."""

    def test_pilot_is_not_promotable(self):
        report = validate_workflow(_load(PILOT))
        assert not report.promotion_ready
        assert report.unresolved_blocking

    def test_pilot_triggers_the_expected_rules(self):
        report = validate_workflow(_load(PILOT))
        fired = {f.rule.rule_id for f in report.findings}
        # The seeded defects, each mapped in the pilot's header comment.
        assert {
            "HW-002", "HW-003", "HW-004", "HW-005", "HW-006",
            "HW-008", "HW-009", "HW-010", "HW-011", "HW-012",
            "HW-013", "HW-014",
        } <= fired

    def test_pilot_does_not_trigger_rules_it_satisfies(self):
        report = validate_workflow(_load(PILOT))
        fired = {f.rule.rule_id for f in report.findings}
        # Trigger is stated (HW-001); no dead ends (HW-007); the published post
        # carries evidence (HW-016).
        assert not fired & {"HW-001", "HW-007", "HW-016"}

    def test_seeded_structural_defects_are_found_precisely(self):
        report = validate_workflow(_load(PILOT))
        dangling = [f for f in report.findings if f.rule.rule_id == "HW-005"]
        assert [f.location.detail for f in dangling] == ["promote-post"]
        unreachable = [f for f in report.findings if f.rule.rule_id == "HW-006"]
        assert [f.location.step_id for f in unreachable] == ["archive-notes"]


class TestSparseCapture:
    """A real first interview is mostly blank. It must still work."""

    def test_sparse_capture_validates_without_crashing(self):
        report = validate_workflow(_load(SPARSE))
        assert report.findings
        assert not report.promotion_ready

    def test_sparse_capture_reports_the_obvious_gaps(self):
        fired = {f.rule.rule_id for f in validate_workflow(_load(SPARSE)).findings}
        assert {"HW-001", "HW-003", "HW-009", "HW-010", "HW-015"} <= fired

    def test_uncharacterized_steps_do_not_break_decision_authority(self):
        # All characteristics are UNKNOWN, so HW-004 must fall back to the
        # structural signals (branching, gates) without error.
        report = validate_workflow(_load(SPARSE), rule_ids=["HW-004"])
        assert all(f.rule.rule_id == "HW-004" for f in report.findings)

    def test_placeholders_are_not_accepted_as_values(self):
        sparse = _load(SPARSE)
        assert sparse.purpose.strip() == "TBD"
        # 'TBD' in trigger would be undefined too; the fixture leaves it empty.
        sparse.trigger = "TBD"
        assert len(_fired(sparse, "HW-001")) == 1


class TestWorkflowIndex:
    def test_empty_workflow_has_no_reachable_steps(self):
        idx = WorkflowIndex.build(HumanWorkflowDraft(workflow_id="w", name="W"))
        assert idx.reachable == set()
        assert idx.terminal_steps() == []

    def test_empty_workflow_validates_cleanly_for_step_rules(self):
        # No steps means no step-level findings; the workflow-level ones still
        # apply. This must not raise.
        report = validate_workflow(HumanWorkflowDraft(workflow_id="w", name="W"))
        fired = {f.rule.rule_id for f in report.findings}
        assert "HW-001" in fired            # no trigger
        assert not fired & {"HW-003", "HW-006", "HW-007"}

    def test_gates_are_indexed_by_step(self, clean):
        idx = WorkflowIndex.build(clean)
        assert [g.gate_id for g in idx.gates_by_step["review-claim"]] == ["finance-approval"]

    def test_self_referential_route_does_not_hang(self, clean):
        clean.step("pay-claim").next_steps = ["pay-claim"]
        idx = WorkflowIndex.build(clean)
        assert "pay-claim" in idx.reachable
