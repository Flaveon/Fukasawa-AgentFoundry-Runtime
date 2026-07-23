# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Human review gate.

When a capsule reaches a CONSCIOUS-depth transition, execution pauses here.
The human operator sees the current state, the proposed next state, the
evidence provided, and the workflow's completion criteria — then decides:

* APPROVE — the transition proceeds.
* REJECT  — the capsule is sent to NON_CONFORMANCE.
* FLAG    — the concern is recorded for later review; progress continues.

This module only presents and collects the decision. Acting on it (advancing,
freezing, flagging) is the runtime's job, so the gate stays honest: it cannot
move work anywhere by itself.
"""

from enum import Enum

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from src.schemas.process_capsule import ProcessCapsule
from src.schemas.workflow_brief import Transition, WorkflowBrief


class ReviewDecision(str, Enum):
    """The three outcomes a human reviewer can choose at a gate."""

    APPROVE = "APPROVE"
    REJECT = "REJECT"
    FLAG = "FLAG"


def open_review_gate(
    brief: WorkflowBrief,
    capsule: ProcessCapsule,
    transition: Transition,
    evidence: str,
    console: Console | None = None,
) -> ReviewDecision:
    """Pause execution and ask the human operator to decide.

    Presents everything the operator needs to judge the move — current state,
    proposed next state, evidence provided, and the completion criteria —
    and keeps asking until one of APPROVE, REJECT, or FLAG is typed.
    """
    console = console or Console()

    details = Table.grid(padding=(0, 2))
    details.add_column(style="bold cyan", justify="right")
    details.add_column()
    details.add_row("Capsule", capsule.id)
    details.add_row("Assigned to", capsule.assigned_to)
    details.add_row("Current state", f"[yellow]{capsule.state}[/yellow]")
    details.add_row("Proposed next state", f"[green]{transition.to_state}[/green]")
    details.add_row("Transition owner", transition.owner)
    details.add_row("Evidence required", transition.evidence_required or "(none)")
    details.add_row("Evidence provided", evidence or "[red](none)[/red]")
    details.add_row("Completion criteria", brief.completion_criteria)

    console.print(
        Panel(
            details,
            title="[bold]HUMAN REVIEW GATE — CONSCIOUS decision[/bold]",
            subtitle="APPROVE / REJECT / FLAG",
            border_style="magenta",
        )
    )

    decision = Prompt.ask(
        "Decision",
        choices=[d.value for d in ReviewDecision],
        console=console,
    )
    return ReviewDecision(decision)
