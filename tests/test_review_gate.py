import pytest
from unittest.mock import patch, MagicMock
from rich.console import Console

from src.runtime.review_gate import open_review_gate, ReviewDecision
from src.schemas.process_capsule import ProcessCapsule
from src.schemas.workflow_brief import WorkflowBrief, Transition, TaskDepth

@pytest.fixture
def dummy_brief():
    return WorkflowBrief(
        id="test-flow",
        title="Test Flow",
        owner="operator",
        task_depth=TaskDepth.CONSCIOUS,
        initial_state="START",
        states=["START", "DONE"],
        transitions=[
            Transition(from_state="START", to_state="DONE", owner="worker", evidence_required="some proof")
        ],
        completion_criteria="reaches DONE",
        exception_path="stop and ask",
    )

@pytest.fixture
def dummy_capsule():
    return ProcessCapsule(
        id="cap-1",
        workflow_id="test-flow",
        state="START",
        assigned_to="worker"
    )

@pytest.mark.parametrize("mock_input,expected_decision", [
    ("APPROVE", ReviewDecision.APPROVE),
    ("REJECT", ReviewDecision.REJECT),
    ("FLAG", ReviewDecision.FLAG),
])
def test_open_review_gate_decisions(dummy_brief, dummy_capsule, mock_input, expected_decision):
    transition = dummy_brief.transitions[0]

    with patch("rich.prompt.Prompt.ask", return_value=mock_input) as mock_ask:
        decision = open_review_gate(
            brief=dummy_brief,
            capsule=dummy_capsule,
            transition=transition,
            evidence="test evidence"
        )
        assert decision == expected_decision
        mock_ask.assert_called_once()


def test_open_review_gate_custom_console(dummy_brief, dummy_capsule):
    transition = dummy_brief.transitions[0]
    custom_console = MagicMock(spec=Console)

    with patch("rich.prompt.Prompt.ask", return_value="APPROVE") as mock_ask:
        decision = open_review_gate(
            brief=dummy_brief,
            capsule=dummy_capsule,
            transition=transition,
            evidence="test evidence",
            console=custom_console
        )
        assert decision == ReviewDecision.APPROVE
        mock_ask.assert_called_once_with("Decision", choices=["APPROVE", "REJECT", "FLAG"], console=custom_console)
        custom_console.print.assert_called_once()

def test_open_review_gate_empty_evidence(dummy_brief, dummy_capsule):
    transition = dummy_brief.transitions[0]
    # Also test empty evidence required
    transition.evidence_required = ""

    with patch("rich.prompt.Prompt.ask", return_value="APPROVE") as mock_ask:
        decision = open_review_gate(
            brief=dummy_brief,
            capsule=dummy_capsule,
            transition=transition,
            evidence=""
        )
        assert decision == ReviewDecision.APPROVE
        mock_ask.assert_called_once()
