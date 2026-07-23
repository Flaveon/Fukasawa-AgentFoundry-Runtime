# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Schema validation tests: required fields and contract rules.

These tests exist so the runtime-state contract's rules stay enforced as
code evolves — a schema that silently stops requiring blocked_reason would
quietly break every future handoff.
"""

import pytest
from pydantic import ValidationError

from src.schemas.observation_packet import ObservationPacket
from src.schemas.runtime_state import (
    CheckResult,
    CompletedCheck,
    HumanGate,
    RunStatus,
    RuntimeState,
)
from src.schemas.workflow_brief import TaskDepth, WorkflowBrief


def _minimal_brief_dict(**overrides) -> dict:
    """A valid brief dict; tests mutate it to prove specific failures."""
    data = {
        "id": "test-flow",
        "title": "Test Flow",
        "owner": "operator",
        "task_depth": "GUIDED",
        "initial_state": "START",
        "states": ["START", "DONE"],
        "transitions": [
            {"from_state": "START", "to_state": "DONE", "owner": "worker"}
        ],
        "completion_criteria": "reaches DONE",
        "exception_path": "stop and ask",
    }
    data.update(overrides)
    return data


def _run_state(**overrides) -> RuntimeState:
    """A valid RuntimeState; tests mutate kwargs to prove contract rules."""
    data = dict(
        run_id="run-1",
        workflow_id="test-flow",
        workflow_name="Test Flow",
        capsule_id="cap-1",
        operator="operator",
        current_state="START",
        task_depth=TaskDepth.GUIDED,
    )
    data.update(overrides)
    return RuntimeState(**data)


class TestWorkflowBrief:
    def test_valid_brief_passes(self):
        brief = WorkflowBrief.model_validate(_minimal_brief_dict())
        assert brief.id == "test-flow"

    def test_missing_required_field_fails_naming_the_field(self):
        data = _minimal_brief_dict()
        del data["completion_criteria"]
        with pytest.raises(ValidationError) as exc:
            WorkflowBrief.model_validate(data)
        assert "completion_criteria" in str(exc.value)

    def test_transition_to_unknown_state_fails(self):
        data = _minimal_brief_dict(
            transitions=[
                {"from_state": "START", "to_state": "NOWHERE", "owner": "worker"}
            ]
        )
        with pytest.raises(ValidationError, match="unknown state 'NOWHERE'"):
            WorkflowBrief.model_validate(data)

    def test_initial_state_must_be_declared(self):
        with pytest.raises(ValidationError, match="initial_state"):
            WorkflowBrief.model_validate(_minimal_brief_dict(initial_state="GHOST"))

    def test_bad_slug_id_fails(self):
        with pytest.raises(ValidationError):
            WorkflowBrief.model_validate(_minimal_brief_dict(id="Not A Slug!"))


class TestRuntimeStateContract:
    def test_blocked_requires_reason_and_next_action(self):
        with pytest.raises(ValidationError, match="blocked_reason"):
            _run_state(status=RunStatus.BLOCKED, next_action="resume it")
        with pytest.raises(ValidationError, match="next_action"):
            _run_state(status=RunStatus.BLOCKED, blocked_reason="waiting on editor")
        # Both present: valid.
        state = _run_state(
            status=RunStatus.BLOCKED,
            blocked_reason="waiting on editor",
            next_action="resume after sign-off",
        )
        assert state.status is RunStatus.BLOCKED

    def test_human_review_requires_gate_reason(self):
        with pytest.raises(ValidationError, match="human_gate.reason"):
            _run_state(status=RunStatus.HUMAN_REVIEW)
        state = _run_state(
            status=RunStatus.HUMAN_REVIEW,
            human_gate=HumanGate(required=True, reason="CONSCIOUS transition"),
        )
        assert state.human_gate.reason

    def test_completion_requires_a_passing_check(self):
        with pytest.raises(ValidationError, match="verification check"):
            _run_state(status=RunStatus.COMPLETE)
        # A failing check is not enough.
        with pytest.raises(ValidationError, match="verification check"):
            _run_state(
                status=RunStatus.COMPLETE,
                completed_checks=[
                    CompletedCheck(check="output exists", result=CheckResult.FAIL)
                ],
            )
        state = _run_state(
            status=RunStatus.COMPLETE,
            completed_checks=[
                CompletedCheck(check="output exists", result=CheckResult.PASS)
            ],
        )
        assert state.status is RunStatus.COMPLETE

    def test_artifacts_must_have_paths(self):
        with pytest.raises(ValidationError):
            _run_state().inputs.append(None)  # type: ignore[arg-type]
            RuntimeState.model_validate(
                {**_run_state().model_dump(), "inputs": [{"path": "", "kind": "x"}]}
            )


class TestObservationPacket:
    def test_confidence_and_missing_evidence_are_required(self):
        base = dict(
            id="obs-1",
            run_id="run-1",
            capsule_id="cap-1",
            observer="worker",
            observation="draft is 1450 words",
        )
        with pytest.raises(ValidationError, match="confidence"):
            ObservationPacket.model_validate(base)
        with pytest.raises(ValidationError, match="missing_evidence"):
            ObservationPacket.model_validate({**base, "confidence": "high"})
        packet = ObservationPacket.model_validate(
            {**base, "confidence": "high", "missing_evidence": "none"}
        )
        assert packet.confidence.value == "high"

    def test_observation_may_not_be_empty(self):
        with pytest.raises(ValidationError):
            ObservationPacket.model_validate(
                dict(
                    id="obs-1",
                    run_id="run-1",
                    capsule_id="cap-1",
                    observer="worker",
                    observation="",
                    confidence="low",
                    missing_evidence="none",
                )
            )
