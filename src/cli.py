# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Fukasawa CLI — the operator's entry point to the runtime.

Commands:
    fukasawa run <brief.yaml>        start a workflow from a brief file
    fukasawa status <workflow_id>    show current state of all capsules
    fukasawa history <workflow_id>   print the full run ledger
    fukasawa review <capsule_id>     open a human review gate for a capsule
    fukasawa nonconformance list     show all capsules in NON_CONFORMANCE

All state lives in a local SQLite file (default: ./fukasawa.db). No network
calls happen anywhere in this program.
"""

from typing import Optional

import typer
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from src.runtime.ledger import DEFAULT_DB_PATH, RunLedger
from src.runtime.review_gate import ReviewDecision, open_review_gate
from src.runtime.state_machine import NonConformanceError, WorkflowRuntime
from src.schemas.process_capsule import CapsuleStatus, ProcessCapsule
from src.schemas.workflow_brief import TaskDepth, Transition, WorkflowBrief

app = typer.Typer(
    name="fukasawa",
    help="Local-first workflow governance runtime for human-agent collaboration.",
    no_args_is_help=True,
)
nonconformance_app = typer.Typer(help="Inspect non-conforming capsules.")
app.add_typer(nonconformance_app, name="nonconformance")

console = Console()

_DB_OPTION = typer.Option(
    DEFAULT_DB_PATH, "--db", help="Path to the SQLite ledger database."
)


def _apply_decision(
    runtime: WorkflowRuntime,
    brief: WorkflowBrief,
    capsule: ProcessCapsule,
    transition: Transition,
    evidence: str,
    decision: ReviewDecision,
) -> ProcessCapsule:
    """Carry out a reviewer's decision from a review gate."""
    if decision is ReviewDecision.REJECT:
        note = Prompt.ask("Rejection reason", console=console, default="rejected at review gate")
        capsule = runtime.mark_non_conformance(brief, capsule, note)
        console.print("[red]REJECTED — capsule sent to NON_CONFORMANCE.[/red]")
        return capsule
    if decision is ReviewDecision.FLAG:
        note = Prompt.ask("Flag note", console=console, default="flagged for later review")
        runtime.flag(brief, capsule, note)
        console.print("[yellow]FLAGGED — recorded for later review, continuing.[/yellow]")
    capsule = runtime.advance(brief, capsule, transition.to_state, evidence)
    console.print(
        f"[green]-> {capsule.state}[/green] "
        f"({capsule.status.value})"
    )
    return capsule


def _attempt_transition(
    runtime: WorkflowRuntime,
    brief: WorkflowBrief,
    capsule: ProcessCapsule,
    transition: Transition,
    evidence: str,
) -> ProcessCapsule:
    """Attempt one transition, opening a review gate first if it is CONSCIOUS-depth."""
    if brief.depth_of(transition) is TaskDepth.CONSCIOUS:
        decision = open_review_gate(brief, capsule, transition, evidence, console)
        return _apply_decision(runtime, brief, capsule, transition, evidence, decision)
    capsule = runtime.advance(brief, capsule, transition.to_state, evidence)
    console.print(f"[green]-> {capsule.state}[/green] ({capsule.status.value})")
    return capsule


@app.command()
def run(
    brief_path: str = typer.Argument(..., help="Path to a workflow brief YAML file."),
    assigned_to: Optional[str] = typer.Option(
        None, help="Who the first capsule is assigned to. Defaults to the brief owner."
    ),
    db: str = _DB_OPTION,
) -> None:
    """Start a workflow from a brief file and walk it interactively."""
    runtime = WorkflowRuntime(RunLedger(db))
    brief = runtime.load_brief(brief_path)
    capsule = runtime.start(brief, assigned_to=assigned_to)
    console.print(
        f"[bold]{brief.title}[/bold] started — capsule [cyan]{capsule.id}[/cyan] "
        f"in state [yellow]{capsule.state}[/yellow]\n"
    )

    while capsule.status not in (CapsuleStatus.COMPLETE, CapsuleStatus.NON_CONFORMANCE):
        options = runtime.valid_transitions(brief, capsule)
        if not options:
            break  # terminal state; advance() has already marked COMPLETE
        targets = [t.to_state for t in options]
        console.print(f"Current state: [yellow]{capsule.state}[/yellow]")
        choice = Prompt.ask(
            "Next state (or 'quit' to pause)",
            choices=targets + ["quit"],
            console=console,
        )
        if choice == "quit":
            console.print(
                f"Paused. Resume later with: fukasawa review {capsule.id}"
            )
            return
        transition = next(t for t in options if t.to_state == choice)
        prompt_text = (
            f"Evidence ({transition.evidence_required})"
            if transition.evidence_required
            else "Evidence (optional)"
        )
        evidence = Prompt.ask(prompt_text, console=console, default="")
        try:
            capsule = _attempt_transition(runtime, brief, capsule, transition, evidence)
        except NonConformanceError as exc:
            console.print(f"[red]NON-CONFORMANCE:[/red] {exc}")
            # Missing evidence leaves the capsule in place — loop lets the
            # operator retry. A frozen capsule exits via the while condition.
            capsule = runtime.ledger.load_capsule(capsule.id)
        console.print()

    if capsule.status is CapsuleStatus.COMPLETE:
        console.print(
            f"[bold green]COMPLETE[/bold green] — {brief.completion_criteria}"
        )
    elif capsule.status is CapsuleStatus.NON_CONFORMANCE:
        console.print(
            f"[bold red]Workflow halted in NON_CONFORMANCE.[/bold red] "
            f"See: fukasawa nonconformance list"
        )


@app.command()
def status(
    workflow_id: str = typer.Argument(..., help="Workflow id from the brief."),
    db: str = _DB_OPTION,
) -> None:
    """Show the current state of every capsule in a workflow."""
    ledger = RunLedger(db)
    try:
        brief = ledger.load_workflow(workflow_id)
    except Exception:
        console.print(f"[red]Unknown workflow:[/red] {workflow_id}")
        raise typer.Exit(1)
    table = Table(title=f"{brief.title} ({workflow_id})")
    for col in ("Capsule", "State", "Status", "Assigned to", "Evidence"):
        table.add_column(col)
    for capsule in ledger.capsules_for(workflow_id):
        table.add_row(
            capsule.id,
            capsule.state,
            capsule.status.value,
            capsule.assigned_to,
            capsule.evidence or "-",
        )
    console.print(table)


@app.command()
def history(
    workflow_id: str = typer.Argument(..., help="Workflow id from the brief."),
    db: str = _DB_OPTION,
) -> None:
    """Print the full append-only run ledger for a workflow."""
    ledger = RunLedger(db)
    events = ledger.history(workflow_id)
    if not events:
        console.print(f"No ledger events for workflow '{workflow_id}'.")
        raise typer.Exit(1)
    table = Table(title=f"Run ledger — {workflow_id}")
    for col in ("#", "Time (UTC)", "From", "To", "Owner", "Evidence", "OK", "Note"):
        table.add_column(col)
    for ev in events:
        table.add_row(
            str(ev["event_id"]),
            ev["timestamp"][:19],
            ev["from_state"] or "-",
            ev["to_state"],
            ev["owner"],
            ev["evidence"] or "-",
            "[green]yes[/green]" if ev["conforming"] else "[red]NO[/red]",
            ev["note"] or "-",
        )
    console.print(table)


@app.command()
def review(
    capsule_id: str = typer.Argument(..., help="Capsule id to review."),
    db: str = _DB_OPTION,
) -> None:
    """Open a human review gate for a specific capsule and act on the decision."""
    ledger = RunLedger(db)
    runtime = WorkflowRuntime(ledger)
    try:
        capsule = ledger.load_capsule(capsule_id)
    except Exception:
        console.print(f"[red]Unknown capsule:[/red] {capsule_id}")
        raise typer.Exit(1)
    brief = ledger.load_workflow(capsule.workflow_id)
    options = runtime.valid_transitions(brief, capsule)
    if not options:
        console.print(
            f"Capsule {capsule.id} is in terminal state "
            f"[yellow]{capsule.state}[/yellow] ({capsule.status.value}); nothing to review."
        )
        raise typer.Exit(0)
    if len(options) == 1:
        transition = options[0]
    else:
        choice = Prompt.ask(
            "Which transition?",
            choices=[t.to_state for t in options],
            console=console,
        )
        transition = next(t for t in options if t.to_state == choice)
    evidence = capsule.evidence
    if transition.evidence_required and not evidence:
        evidence = Prompt.ask(
            f"Evidence ({transition.evidence_required})", console=console, default=""
        )
    decision = open_review_gate(brief, capsule, transition, evidence, console)
    try:
        _apply_decision(runtime, brief, capsule, transition, evidence, decision)
    except NonConformanceError as exc:
        console.print(f"[red]NON-CONFORMANCE:[/red] {exc}")
        raise typer.Exit(1)


@nonconformance_app.command("list")
def nonconformance_list(db: str = _DB_OPTION) -> None:
    """Show all capsules currently in NON_CONFORMANCE status."""
    ledger = RunLedger(db)
    capsules = ledger.non_conforming_capsules()
    if not capsules:
        console.print("[green]No capsules in NON_CONFORMANCE.[/green]")
        return
    table = Table(title="Non-conforming capsules")
    for col in ("Capsule", "Workflow", "State", "Note"):
        table.add_column(col)
    for capsule in capsules:
        table.add_row(
            capsule.id,
            capsule.workflow_id,
            capsule.state,
            capsule.non_conformance_note or "-",
        )
    console.print(table)


if __name__ == "__main__":
    app()
