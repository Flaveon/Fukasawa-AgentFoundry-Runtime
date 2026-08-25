# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Fukasawa CLI — the operator's entry point to the runtime.

Commands:
    fukasawa run <brief.yaml>           start a workflow from a brief file
    fukasawa resume <run_id>            continue a persisted run
    fukasawa status <workflow_id>       show current state of all capsules
    fukasawa history <workflow_id>      print the full run ledger
    fukasawa review <capsule_id>        open a human review gate for a capsule
    fukasawa validate brief <path>      validate a workflow brief file
    fukasawa validate capsule <ref>     validate a capsule file or stored capsule
    fukasawa runs list                  list all tracked runs
    fukasawa runs show <run_id>         show a run's full durable state
    fukasawa runs block <run_id>        block a run with reason + next action
    fukasawa runs complete <run_id>     complete a run with a verification check
    fukasawa nonconformance list        show capsules in NON_CONFORMANCE
    fukasawa nonconformance records     show structured non-conformance records
    fukasawa bundle export <brief>      pack a signed, shareable workflow bundle
    fukasawa bundle inspect <bundle>    verify a bundle's signature and hashes
    fukasawa bundle import <bundle>     verify and unpack a trusted bundle

The workflow lifecycle, in the order you use it:

    fukasawa workflow init <id>              write a draft skeleton to fill in
    fukasawa workflow validate <draft>       check it against the 16 rules
    fukasawa workflow findings <draft>       list findings without gating
    fukasawa workflow accept-risk <draft>    record a decision on an advisory finding
    fukasawa workflow promote <draft> --by   advance one maturity step
    fukasawa workflow assess-cooperation <id>   recommend an executor per step
    fukasawa workflow build-cooperative <id>    assign every step
    fukasawa workflow export-agent-brief <id>   flatten into a runnable brief
    fukasawa workflow status <id>            where it sits, and what is missing

Every `workflow` command accepts `--json`. Their exit codes are stable:
0 success, 1 your input was wrong, 2 understood and blocked for now,
3 understood and refused as a matter of doctrine.

All state lives in a local SQLite file (default: ./fukasawa.db). Run handoff
files are written to ./run_handoffs/. No network calls happen anywhere in
this program.
"""

import json as jsonlib
import re
from pathlib import Path
from typing import Optional

import typer
import yaml
from pydantic import ValidationError
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from src import resources
from src.foundry.generator import BuildRefusedError, generate_packages
from src.foundry.validator import validate_package
from src.foundry.workflow_export import (
    ExportRefusedError,
    build_cooperative_workflow,
    export_workflow,
    steps_kept_human,
)
from src.governance.cooperation import (
    OverrideRefusedError,
    apply_override,
    assess_workflow,
    steps_not_ready,
)
from src.governance.evals import load_eval_case, run_eval_case
from src.governance.maturity import PromotionRefusedError, assess, promote
from src.governance.workflow_promotion import (
    PromotionRefusedError as WorkflowPromotionRefused,
)
from src.governance.workflow_promotion import (
    RiskAcceptanceRefusedError,
    accept_risk,
    at_recorded_maturity,
    reattach_acceptances,
)
from src.governance.workflow_promotion import promote as promote_workflow
from src.governance.workflow_rules import validate_workflow
from src.schemas.cooperation import ExecutorClass, SafetyFloor
from src.schemas.findings import ValidationReport, WorkflowFinding
from src.schemas.human_workflow import HumanWorkflowDraft, WorkflowMaturity
from src.schemas.templates import DRAFT_SKELETON
from src.kernel.kernel import (
    GraphRunner,
    GraphSpecError,
    UntrustedGraphError,
    graph_fingerprint,
    load_graph,
)
from src.schemas.graph import GraphRunStatus
from src.security.trust import TrustStore
from src.runtime.handoff import DEFAULT_HANDOFF_DIR, write_handoff
from src.runtime.ledger import DEFAULT_DB_PATH, RunLedger
from src.runtime.review_gate import ReviewDecision, open_review_gate
from src.runtime.state_machine import NonConformanceError, WorkflowRuntime
from src.schemas.process_capsule import CapsuleStatus, ProcessCapsule
from src.schemas.runtime_state import CheckResult, CompletedCheck, RunStatus, RuntimeState
from src.schemas.workflow_brief import TaskDepth, Transition, WorkflowBrief

app = typer.Typer(
    name="fukasawa",
    help="Local-first workflow governance runtime for human-agent collaboration.",
    no_args_is_help=True,
)
nonconformance_app = typer.Typer(help="Inspect non-conforming capsules and records.")
validate_app = typer.Typer(help="Validate briefs and capsules with clear errors.")
runs_app = typer.Typer(help="Inspect and manage tracked runs.")
package_app = typer.Typer(help="Generate and validate agent packages (Agent Foundry).")
eval_app = typer.Typer(help="Run eval cases against recorded runs.")
maturity_app = typer.Typer(help="Evidence-based maturity assessment and promotion.")
graph_app = typer.Typer(help="Run workflow graphs through the orchestration kernel.")
trust_app = typer.Typer(help="Manage signing identity and trusted keys.")
model_app = typer.Typer(help="Inspect and test configured model endpoints.")
node_app = typer.Typer(help="Tell Fukasawa what computers can run AI for it.")
bundle_app = typer.Typer(help="Export and import signed, shareable workflow bundles.")
workflow_app = typer.Typer(
    help="Capture, validate, promote, assess and export a human workflow."
)
app.add_typer(nonconformance_app, name="nonconformance")
app.add_typer(validate_app, name="validate")
app.add_typer(runs_app, name="runs")
app.add_typer(package_app, name="package")
app.add_typer(eval_app, name="eval")
app.add_typer(maturity_app, name="maturity")
app.add_typer(graph_app, name="graph")
app.add_typer(trust_app, name="trust")
app.add_typer(model_app, name="model")
app.add_typer(node_app, name="node")
app.add_typer(bundle_app, name="bundle")
app.add_typer(workflow_app, name="workflow")

console = Console()

_DB_OPTION = typer.Option(
    DEFAULT_DB_PATH, "--db", help="Path to the SQLite ledger database."
)
_HANDOFF_OPTION = typer.Option(
    DEFAULT_HANDOFF_DIR, "--handoff-dir", help="Directory for emitted run handoff files."
)


def _print_validation_error(exc: ValidationError, subject: str) -> None:
    """Render a Pydantic validation error as a readable checklist, not a traceback."""
    table = Table(title=f"[red]{subject} failed validation[/red]", show_lines=False)
    table.add_column("Field", style="bold cyan")
    table.add_column("Problem")
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"]) or "(root)"
        # escape() keeps literal brackets (e.g. regex character classes in
        # Pydantic messages) from being swallowed as Rich markup.
        table.add_row(escape(loc), escape(err["msg"]))
    console.print(table)


# --------------------------------------------------------------- shared loop


def _emit_handoff(
    runtime: WorkflowRuntime,
    brief: WorkflowBrief,
    capsule: ProcessCapsule,
    run: RuntimeState,
    handoff_dir: str,
) -> None:
    """Write the run's handoff file and tell the operator where it is."""
    path = write_handoff(run, brief, capsule, handoff_dir)
    console.print(f"Handoff written: [cyan]{path}[/cyan]")


def _apply_decision(
    runtime: WorkflowRuntime,
    brief: WorkflowBrief,
    capsule: ProcessCapsule,
    transition: Transition,
    evidence: str,
    decision: ReviewDecision,
    run: RuntimeState,
) -> ProcessCapsule:
    """Carry out a reviewer's decision from a review gate."""
    if decision is ReviewDecision.REJECT:
        note = Prompt.ask(
            "Rejection reason", console=console, default="rejected at review gate"
        )
        runtime.resolve_gate(run, approved=False)
        capsule = runtime.mark_non_conformance(brief, capsule, note, run=run)
        console.print("[red]REJECTED — capsule sent to NON_CONFORMANCE.[/red]")
        return capsule
    if decision is ReviewDecision.FLAG:
        note = Prompt.ask(
            "Flag note", console=console, default="flagged for later review"
        )
        runtime.flag(brief, capsule, note)
        console.print(
            "[yellow]FLAGGED — recorded for later review, continuing.[/yellow]"
        )
    runtime.resolve_gate(run, approved=True)
    capsule = runtime.advance(brief, capsule, transition.to_state, evidence, run=run)
    console.print(f"[green]-> {capsule.state}[/green] ({capsule.status.value})")
    return capsule


def _attempt_transition(
    runtime: WorkflowRuntime,
    brief: WorkflowBrief,
    capsule: ProcessCapsule,
    transition: Transition,
    evidence: str,
    run: RuntimeState,
) -> ProcessCapsule:
    """Attempt one transition, opening a review gate first if it is CONSCIOUS-depth."""
    if brief.depth_of(transition) is TaskDepth.CONSCIOUS:
        runtime.enter_human_review(
            run,
            reason=(
                f"CONSCIOUS-depth transition {capsule.state} -> {transition.to_state}"
            ),
            reviewer=run.operator,
        )
        decision = open_review_gate(brief, capsule, transition, evidence, console)
        return _apply_decision(
            runtime, brief, capsule, transition, evidence, decision, run
        )
    capsule = runtime.advance(brief, capsule, transition.to_state, evidence, run=run)
    console.print(f"[green]-> {capsule.state}[/green] ({capsule.status.value})")
    return capsule


def _interactive_loop(
    runtime: WorkflowRuntime,
    brief: WorkflowBrief,
    capsule: ProcessCapsule,
    run: RuntimeState,
    handoff_dir: str,
) -> None:
    """Walk a capsule through its workflow interactively until done, frozen, or paused.

    Shared by `run` and `resume` — the loop itself has no idea whether the
    run is fresh or restored, which is exactly the point of durable state.
    """
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
            reason = Prompt.ask(
                "Why are you pausing?", console=console, default="operator paused"
            )
            next_action = Prompt.ask(
                "Next action for whoever resumes",
                console=console,
                default=f"fukasawa resume {run.run_id}",
            )
            runtime.block_run(run, reason, next_action)
            _emit_handoff(runtime, brief, capsule, run, handoff_dir)
            console.print(f"Paused. Resume with: fukasawa resume {run.run_id}")
            return
        transition = next(t for t in options if t.to_state == choice)
        prompt_text = (
            f"Evidence ({transition.evidence_required})"
            if transition.evidence_required
            else "Evidence (optional)"
        )
        evidence = Prompt.ask(prompt_text, console=console, default="")
        try:
            from_state = capsule.state
            capsule = _attempt_transition(
                runtime, brief, capsule, transition, evidence, run
            )
            if capsule.state != from_state:
                # Every completed transition is a direct observation: what
                # moved, and on what evidence. Recorded automatically so the
                # observation-discipline eval has something real to inspect.
                runtime.record_observation(
                    run,
                    capsule,
                    observer=transition.owner,
                    observation=(
                        f"transition {from_state} -> {capsule.state} completed"
                        + (f"; evidence: {evidence}" if evidence else "")
                    ),
                    confidence="high",
                    missing_evidence="none" if evidence else "no evidence was required",
                )
            artifact = Prompt.ask(
                "Output artifact path (Enter to skip)", console=console, default=""
            )
            if artifact.strip():
                runtime.add_output_artifact(
                    run, artifact.strip(), kind="artifact", produced_by=transition.owner
                )
        except NonConformanceError as exc:
            console.print(f"[red]NON-CONFORMANCE:[/red] {exc}")
            # Missing evidence leaves the capsule in place — loop lets the
            # operator retry. A frozen capsule exits via the while condition.
            capsule = runtime.ledger.load_capsule(capsule.id)
            run = runtime.ledger.load_run(run.run_id)
        console.print()

    if capsule.status is CapsuleStatus.COMPLETE:
        console.print(f"[bold green]COMPLETE[/bold green] — {brief.completion_criteria}")
    elif capsule.status is CapsuleStatus.NON_CONFORMANCE:
        console.print(
            "[bold red]Workflow halted in NON_CONFORMANCE.[/bold red] "
            "See: fukasawa nonconformance list"
        )
    _emit_handoff(runtime, brief, capsule, run, handoff_dir)


# ------------------------------------------------------------------ commands


@app.command()
def gui() -> None:
    """Launch the desktop app (validate a brief, build a workflow)."""
    try:
        from src.gui.app import main as gui_main
    except ImportError:
        console.print(
            "[red]The GUI needs customtkinter.[/red] Install it with: "
            "pip install 'fukasawa-agentfoundry-runtime[gui]'"
        )
        raise typer.Exit(1)
    gui_main()


@app.command()
def run(
    brief_path: str = typer.Argument(..., help="Path to a workflow brief YAML file."),
    assigned_to: Optional[str] = typer.Option(
        None, help="Who the first capsule is assigned to. Defaults to the brief owner."
    ),
    operator: Optional[str] = typer.Option(
        None, help="The human operating this run. Defaults to the brief owner."
    ),
    db: str = _DB_OPTION,
    handoff_dir: str = _HANDOFF_OPTION,
) -> None:
    """Start a workflow from a brief file and walk it interactively."""
    runtime = WorkflowRuntime(RunLedger(db))
    try:
        brief = runtime.load_brief(brief_path)
    except ValidationError as exc:
        _print_validation_error(exc, f"Brief '{brief_path}'")
        raise typer.Exit(1)
    capsule, run_state = runtime.start(
        brief, assigned_to=assigned_to, operator=operator, brief_path=brief_path
    )
    console.print(
        f"[bold]{brief.title}[/bold] started — run [cyan]{run_state.run_id}[/cyan], "
        f"capsule [cyan]{capsule.id}[/cyan] in state [yellow]{capsule.state}[/yellow]\n"
    )
    _interactive_loop(runtime, brief, capsule, run_state, handoff_dir)


@app.command()
def resume(
    run_id: str = typer.Argument(..., help="Run id to resume (see: fukasawa runs list)."),
    db: str = _DB_OPTION,
    handoff_dir: str = _HANDOFF_OPTION,
) -> None:
    """Continue a persisted run from exactly where it left off."""
    runtime = WorkflowRuntime(RunLedger(db))
    try:
        brief, capsule, run_state = runtime.resume_run(run_id)
    except Exception:
        console.print(f"[red]Unknown run:[/red] {run_id}")
        raise typer.Exit(1)
    if run_state.status in (RunStatus.COMPLETE, RunStatus.FAILED):
        console.print(
            f"Run {run_id} is already [bold]{run_state.status.value}[/bold]; nothing to resume."
        )
        raise typer.Exit(0)
    console.print(
        f"Resuming [bold]{brief.title}[/bold] — run [cyan]{run_state.run_id}[/cyan] "
        f"at state [yellow]{capsule.state}[/yellow]\n"
    )
    _interactive_loop(runtime, brief, capsule, run_state, handoff_dir)


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
    handoff_dir: str = _HANDOFF_OPTION,
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
    run_state = next(
        (r for r in ledger.list_runs(capsule.workflow_id) if r.capsule_id == capsule_id),
        None,
    )
    if run_state is None:
        console.print(f"[red]No tracked run found for capsule:[/red] {capsule_id}")
        raise typer.Exit(1)
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
    runtime.enter_human_review(
        run_state,
        reason=f"review requested for {capsule.state} -> {transition.to_state}",
        reviewer=run_state.operator,
    )
    decision = open_review_gate(brief, capsule, transition, evidence, console)
    try:
        capsule = _apply_decision(
            runtime, brief, capsule, transition, evidence, decision, run_state
        )
    except NonConformanceError as exc:
        console.print(f"[red]NON-CONFORMANCE:[/red] {exc}")
        raise typer.Exit(1)
    finally:
        _emit_handoff(runtime, brief, capsule, run_state, handoff_dir)


# ------------------------------------------------------------------ validate


@validate_app.command("brief")
def validate_brief(
    path: str = typer.Argument(..., help="Path to a workflow brief YAML file."),
) -> None:
    """Validate a workflow brief file, reporting problems field by field."""
    file = resources.resolve(path)
    if not file.exists():
        console.print(f"[red]No such file:[/red] {path}")
        raise typer.Exit(1)
    try:
        raw = yaml.safe_load(file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        console.print(f"[red]Not valid YAML:[/red] {exc}")
        raise typer.Exit(1)
    try:
        brief = WorkflowBrief.model_validate(raw)
    except ValidationError as exc:
        _print_validation_error(exc, f"Brief '{path}'")
        raise typer.Exit(1)
    conscious = sum(
        1 for t in brief.transitions if brief.depth_of(t).value == "CONSCIOUS"
    )
    console.print(
        Panel(
            f"[bold]{brief.title}[/bold] (`{brief.id}`)\n"
            f"owner: {brief.owner} — default depth: {brief.task_depth.value}\n"
            f"{len(brief.states)} states, {len(brief.transitions)} transitions, "
            f"{conscious} human review gate(s)",
            title="[green]Brief is valid[/green]",
            border_style="green",
        )
    )


@validate_app.command("capsule")
def validate_capsule(
    ref: str = typer.Argument(
        ..., help="Path to a capsule YAML/JSON file, or a stored capsule id."
    ),
    db: str = _DB_OPTION,
) -> None:
    """Validate a capsule from a file or re-validate one stored in the ledger."""
    file = Path(ref)
    if file.exists():
        try:
            raw = yaml.safe_load(file.read_text(encoding="utf-8"))
            capsule = ProcessCapsule.model_validate(raw)
        except yaml.YAMLError as exc:
            console.print(f"[red]Not valid YAML/JSON:[/red] {exc}")
            raise typer.Exit(1)
        except ValidationError as exc:
            _print_validation_error(exc, f"Capsule file '{ref}'")
            raise typer.Exit(1)
    else:
        try:
            capsule = RunLedger(db).load_capsule(ref)
        except ValidationError as exc:
            _print_validation_error(exc, f"Stored capsule '{ref}'")
            raise typer.Exit(1)
        except Exception:
            console.print(
                f"[red]'{ref}' is neither an existing file nor a stored capsule id.[/red]"
            )
            raise typer.Exit(1)
    console.print(
        Panel(
            f"[bold]{capsule.id}[/bold] — workflow `{capsule.workflow_id}`\n"
            f"state: {capsule.state} — status: {capsule.status.value} — "
            f"assigned to {capsule.assigned_to}",
            title="[green]Capsule is valid[/green]",
            border_style="green",
        )
    )


# ---------------------------------------------------------------------- runs


@runs_app.command("list")
def runs_list(
    workflow_id: Optional[str] = typer.Option(None, help="Filter by workflow id."),
    db: str = _DB_OPTION,
) -> None:
    """List all tracked runs, newest first."""
    runs = RunLedger(db).list_runs(workflow_id)
    if not runs:
        console.print("No runs recorded.")
        return
    table = Table(title="Runs")
    for col in ("Run", "Workflow", "Status", "State", "Operator", "Updated (UTC)"):
        table.add_column(col)
    for r in runs:
        table.add_row(
            r.run_id,
            r.workflow_id,
            r.status.value,
            r.current_state,
            r.operator,
            r.updated_at.isoformat(timespec="seconds"),
        )
    console.print(table)


@runs_app.command("show")
def runs_show(
    run_id: str = typer.Argument(..., help="Run id to inspect."),
    db: str = _DB_OPTION,
) -> None:
    """Show a run's full durable state — the human-readable status summary."""
    try:
        r = RunLedger(db).load_run(run_id)
    except Exception:
        console.print(f"[red]Unknown run:[/red] {run_id}")
        raise typer.Exit(1)
    details = Table.grid(padding=(0, 2))
    details.add_column(style="bold cyan", justify="right")
    details.add_column()
    details.add_row("Workflow", f"{r.workflow_name} ({r.workflow_id})")
    details.add_row("Capsule", r.capsule_id)
    details.add_row("Operator", r.operator)
    details.add_row("Status", r.status.value)
    details.add_row("Current state", r.current_state)
    details.add_row("Task depth", r.task_depth.value)
    details.add_row("Created", r.created_at.isoformat(timespec="seconds"))
    details.add_row("Updated", r.updated_at.isoformat(timespec="seconds"))
    gate = r.human_gate
    details.add_row(
        "Review gate",
        gate.status.value + (f" — {gate.reason}" if gate.reason else ""),
    )
    if r.blocked_reason:
        details.add_row("Blocked reason", r.blocked_reason)
    if r.next_action:
        details.add_row("Next action", r.next_action)
    for art in r.inputs:
        details.add_row("Input", f"{art.path} ({art.kind})")
    for art in r.outputs:
        details.add_row("Output", f"{art.path} ({art.kind})")
    for check in r.completed_checks:
        details.add_row("Check", f"[{check.result.value}] {check.check}")
    if r.trace_path:
        details.add_row("Trace", r.trace_path)
    console.print(Panel(details, title=f"Run {r.run_id}"))


@runs_app.command("block")
def runs_block(
    run_id: str = typer.Argument(..., help="Run id to block."),
    reason: str = typer.Option(..., "--reason", help="Why the run is blocked."),
    next_action: str = typer.Option(
        ..., "--next-action", help="The single next thing whoever resumes must do."
    ),
    db: str = _DB_OPTION,
    handoff_dir: str = _HANDOFF_OPTION,
) -> None:
    """Block a run. The contract requires both a reason and a next action."""
    ledger = RunLedger(db)
    runtime = WorkflowRuntime(ledger)
    try:
        run_state = ledger.load_run(run_id)
    except Exception:
        console.print(f"[red]Unknown run:[/red] {run_id}")
        raise typer.Exit(1)
    runtime.block_run(run_state, reason, next_action)
    brief = ledger.load_workflow(run_state.workflow_id)
    capsule = ledger.load_capsule(run_state.capsule_id)
    _emit_handoff(runtime, brief, capsule, run_state, handoff_dir)
    console.print(f"[yellow]Run {run_id} blocked.[/yellow]")


@runs_app.command("complete")
def runs_complete(
    run_id: str = typer.Argument(..., help="Run id to complete."),
    check: str = typer.Option(
        ..., "--check", help="What was verified to justify completion."
    ),
    evidence: str = typer.Option(
        ..., "--evidence", help="Evidence supporting the verification check."
    ),
    db: str = _DB_OPTION,
    handoff_dir: str = _HANDOFF_OPTION,
) -> None:
    """Mark a run complete. Requires a verification check — completion is earned."""
    ledger = RunLedger(db)
    runtime = WorkflowRuntime(ledger)
    try:
        run_state = ledger.load_run(run_id)
    except Exception:
        console.print(f"[red]Unknown run:[/red] {run_id}")
        raise typer.Exit(1)
    run_state.completed_checks.append(
        CompletedCheck(check=check, result=CheckResult.PASS, evidence=evidence)
    )
    run_state.status = RunStatus.COMPLETE
    run_state.touch()
    ledger.save_run(run_state)
    brief = ledger.load_workflow(run_state.workflow_id)
    capsule = ledger.load_capsule(run_state.capsule_id)
    _emit_handoff(runtime, brief, capsule, run_state, handoff_dir)
    console.print(f"[green]Run {run_id} complete.[/green]")


# --------------------------------------------------------------------- package


@package_app.command("generate")
def package_generate(
    brief_path: str = typer.Argument(..., help="Path to an APPROVED workflow brief YAML."),
    out: str = typer.Option(
        "packages", "--out", help="Directory to generate agent packages into."
    ),
    workspace: Optional[str] = typer.Option(
        None,
        "--workspace",
        help="Target workspace root. Numbered directories trigger C-Pax path injection.",
    ),
    paths_file: Optional[str] = typer.Option(
        None,
        "--paths-file",
        help="YAML file of workspace paths for non-C-Pax targets (context, tasks_ready, ...).",
    ),
) -> None:
    """Generate one agent package per declared agent from an approved brief."""
    try:
        brief = WorkflowRuntime.load_brief(brief_path)
    except ValidationError as exc:
        _print_validation_error(exc, f"Brief '{brief_path}'")
        raise typer.Exit(1)
    explicit_paths = None
    if paths_file:
        explicit_paths = yaml.safe_load(Path(paths_file).read_text(encoding="utf-8"))
    try:
        package_dirs, report = generate_packages(
            brief, out, workspace_root=workspace, explicit_paths=explicit_paths
        )
    except BuildRefusedError as exc:
        console.print(Panel(str(exc), title="[red]Build refused[/red]", border_style="red"))
        raise typer.Exit(1)
    for pkg in package_dirs:
        console.print(f"[green]generated[/green] {pkg}")
    console.print(f"Build report: [cyan]{report}[/cyan]")
    # Validate what we just generated — the generator does not get to skip
    # its own gate. Any finding here is a generator bug, surfaced loudly.
    failed = False
    for pkg in package_dirs:
        findings = validate_package(pkg)
        if findings:
            failed = True
            console.print(f"[red]{pkg.name} failed self-validation:[/red]")
            for finding in findings:
                console.print(f"  - {finding}")
    if failed:
        raise typer.Exit(1)
    console.print("[green]All generated packages pass validation.[/green]")


@package_app.command("validate")
def package_validate(
    package_dir: str = typer.Argument(..., help="Path to an agent package directory."),
) -> None:
    """Validate an agent package directory against the Agent Foundry standard."""
    findings = validate_package(package_dir)
    if not findings:
        console.print(
            Panel(
                f"`{package_dir}` contains every required file, all schemas "
                f"validate, and depth/maturity declarations agree.",
                title="[green]Package is valid[/green]",
                border_style="green",
            )
        )
        return
    table = Table(title=f"[red]{package_dir} — {len(findings)} finding(s)[/red]")
    table.add_column("#", justify="right")
    table.add_column("Finding")
    for i, finding in enumerate(findings, 1):
        table.add_row(str(i), escape(finding))
    console.print(table)
    raise typer.Exit(1)


# ----------------------------------------------------------------------- graph


def _drive_graph(runner: GraphRunner, graph, state) -> None:
    """Advance a graph run, opening interactive review gates as they arrive."""
    from src.runtime.review_gate import open_review_gate

    while True:
        state = runner.run(graph, state)
        if state.status is not GraphRunStatus.PAUSED_HUMAN:
            break
        node = graph.node(state.current_node)
        brief = runner.ledger.load_workflow(state.workflow_id)
        capsule = runner.ledger.load_capsule(state.capsule_id)
        transition = None
        if node.produces_transition is not None:
            transition = next(
                (
                    t
                    for t in brief.transitions_from(capsule.state)
                    if t.to_state == node.produces_transition.to_state
                ),
                None,
            )
        if transition is None:
            console.print(f"[red]Gate '{node.node_id}' has no valid transition.[/red]")
            raise typer.Exit(1)
        evidence = ""
        if transition.evidence_required:
            evidence = Prompt.ask(
                f"Evidence ({transition.evidence_required})", console=console, default=""
            )
        decision = open_review_gate(brief, capsule, transition, evidence, console)
        note = ""
        if decision.value in ("REJECT", "FLAG"):
            note = Prompt.ask("Note", console=console, default=decision.value)
        state = runner.decide(graph, state, decision, evidence=evidence, note=note)

    color = {
        "complete": "green", "blocked": "yellow", "failed": "red",
    }.get(state.status.value, "cyan")
    console.print(
        f"Graph run [cyan]{state.graph_run_id}[/cyan] finished: "
        f"[{color}]{state.status.value}[/{color}] "
        f"({len(state.history)} node execution(s))"
    )
    if state.status is GraphRunStatus.BLOCKED:
        console.print(f"Resume with: fukasawa graph resume {state.graph_run_id}")


def _sidecar_signature(graph_path: str) -> Optional[str]:
    """Read the detached signature next to a graph file (<graph>.sig), if any."""
    sig = Path(graph_path + ".sig")
    return sig.read_text(encoding="utf-8").strip() if sig.exists() else None


def _model_endpoints() -> "ModelEndpointRegistry":
    """Load model endpoints from the trust-home config, falling back to defaults."""
    from src.kernel.models import ModelEndpointRegistry
    from src.security.trust import DEFAULT_TRUST_ROOT

    return ModelEndpointRegistry.from_config(
        DEFAULT_TRUST_ROOT / "model_endpoints.yaml"
    )


def _make_runner(
    db: str, handoff_dir: str, require_signed: bool, workspace: Optional[str] = None
) -> GraphRunner:
    """Build a runner with a model adapter and optional trust enforcement.

    ``--require-signed`` turns on signature enforcement; ``workspace`` jails
    the filesystem adapter for shared-graph safety.
    """
    from src.kernel.adapters import AdapterRegistry
    from src.kernel.models import ModelAdapter

    registry = AdapterRegistry(
        workspace_root=workspace,
        model_adapter=ModelAdapter(_model_endpoints()),
    )
    trust = TrustStore() if require_signed else None
    return GraphRunner(
        RunLedger(db), registry=registry, handoff_dir=handoff_dir, trust_store=trust
    )


@graph_app.command("run")
def graph_run(
    graph_path: str = typer.Argument(..., help="Path to a workflow graph YAML."),
    brief_path: str = typer.Option(..., "--brief", help="Path to the workflow brief YAML."),
    var: list[str] = typer.Option(
        [], "--var", help="Run variable as name=value; substituted into node params."
    ),
    require_signed: bool = typer.Option(
        False,
        "--require-signed",
        help="Refuse to run unless the graph is signed by a trusted key.",
    ),
    workspace: Optional[str] = typer.Option(
        None,
        "--workspace",
        help="Jail the filesystem adapter to this directory (shared-graph safety).",
    ),
    db: str = _DB_OPTION,
    handoff_dir: str = _HANDOFF_OPTION,
) -> None:
    """Start a graph run and drive it until it completes, blocks, or fails."""
    runner = _make_runner(db, handoff_dir, require_signed, workspace=workspace)
    try:
        graph = load_graph(graph_path)
        brief = runner.runtime.load_brief(brief_path)
    except ValidationError as exc:
        _print_validation_error(exc, f"'{graph_path}'")
        raise typer.Exit(1)
    variables = dict(v.split("=", 1) for v in var)
    try:
        state = runner.start(
            graph,
            brief,
            variables=variables,
            brief_path=brief_path,
            signature=_sidecar_signature(graph_path),
        )
    except UntrustedGraphError as exc:
        console.print(Panel(escape(str(exc)), title="[red]Untrusted graph[/red]", border_style="red"))
        raise typer.Exit(1)
    except GraphSpecError as exc:
        console.print(Panel(escape(str(exc)), title="[red]Graph refused[/red]", border_style="red"))
        raise typer.Exit(1)
    console.print(
        f"[bold]{graph.graph_id}[/bold] started as [cyan]{state.graph_run_id}[/cyan] "
        f"(workflow run {state.run_id})\n"
    )
    _drive_graph(runner, graph, state)


@graph_app.command("resume")
def graph_resume(
    graph_run_id: str = typer.Argument(..., help="Graph run id to resume."),
    graph_path: str = typer.Option(..., "--graph", help="Path to the graph YAML."),
    require_signed: bool = typer.Option(
        False, "--require-signed", help="Refuse to resume unless the graph is trusted-signed."
    ),
    db: str = _DB_OPTION,
    handoff_dir: str = _HANDOFF_OPTION,
) -> None:
    """Resume a blocked or paused graph run from its checkpoint."""
    runner = _make_runner(db, handoff_dir, require_signed)
    graph = load_graph(graph_path)
    try:
        state = runner.resume(
            graph, graph_run_id, signature=_sidecar_signature(graph_path)
        )
    except KeyError:
        console.print(f"[red]Unknown graph run:[/red] {graph_run_id}")
        raise typer.Exit(1)
    except (UntrustedGraphError, GraphSpecError) as exc:
        console.print(Panel(escape(str(exc)), title="[red]Resume refused[/red]", border_style="red"))
        raise typer.Exit(1)
    _drive_graph(runner, graph, state)


@graph_app.command("sign")
def graph_sign(
    graph_path: str = typer.Argument(..., help="Path to a workflow graph YAML to sign."),
) -> None:
    """Sign a graph with the local identity, writing a <graph>.sig sidecar."""
    graph = load_graph(graph_path)
    store = TrustStore()
    signature, public_pem = store.sign_with_identity(graph.model_dump(mode="json"))
    Path(graph_path + ".sig").write_text(signature, encoding="utf-8")
    from src.security.signing import public_key_id

    console.print(
        f"[green]Signed[/green] {graph.graph_id} "
        f"(hash {graph_fingerprint(graph)[:16]}…) with key "
        f"[cyan]{public_key_id(public_pem)}[/cyan]"
    )
    console.print(f"Signature written: [cyan]{graph_path}.sig[/cyan]")


@graph_app.command("show")
def graph_show(
    graph_run_id: str = typer.Argument(..., help="Graph run id to inspect."),
    db: str = _DB_OPTION,
) -> None:
    """Show a graph run's full trace — plain data, no framework UI."""
    try:
        state = RunLedger(db).load_graph_run(graph_run_id)
    except Exception:
        console.print(f"[red]Unknown graph run:[/red] {graph_run_id}")
        raise typer.Exit(1)
    console.print(
        f"[bold]{state.graph_id}[/bold] — {state.status.value}, "
        f"cursor at [yellow]{state.current_node}[/yellow], "
        f"workflow run {state.run_id}"
    )
    table = Table(title=f"Node trace — {state.graph_run_id}")
    for col in ("#", "Node", "Attempt", "OK", "Evidence", "Note"):
        table.add_column(col)
    for i, ex in enumerate(state.history, 1):
        table.add_row(
            str(i),
            ex.node_id,
            str(ex.attempt),
            "[green]yes[/green]" if ex.ok else "[red]NO[/red]",
            escape(ex.evidence[:60]) or "-",
            escape(ex.note[:60]) or "-",
        )
    console.print(table)


@graph_app.command("validate")
def graph_validate(
    graph_path: str = typer.Argument(..., help="Path to a workflow graph YAML."),
    brief_path: str = typer.Option(..., "--brief", help="Path to the workflow brief YAML."),
) -> None:
    """Validate a graph file and its fit against a brief."""
    try:
        graph = load_graph(graph_path)
        brief = WorkflowRuntime.load_brief(brief_path)
    except ValidationError as exc:
        _print_validation_error(exc, f"'{graph_path}'")
        raise typer.Exit(1)
    findings = graph.validate_against_brief(brief)
    if findings:
        for f in findings:
            console.print(f"[red]-[/red] {escape(f)}")
        raise typer.Exit(1)
    gates = sum(1 for n in graph.nodes if n.kind.value == "human_gate")
    console.print(
        Panel(
            f"[bold]{graph.graph_id}[/bold] fits brief `{brief.id}`\n"
            f"{len(graph.nodes)} node(s), {gates} human gate(s)",
            title="[green]Graph is valid[/green]",
            border_style="green",
        )
    )


# ----------------------------------------------------------------------- trust


@trust_app.command("keygen")
def trust_keygen(
    name: str = typer.Option("", "--name", help="Label for this signing identity."),
) -> None:
    """Create (or show) this operator's local signing identity."""
    from src.security.signing import public_key_id

    store = TrustStore()
    keypair = store.ensure_identity(name=name)
    console.print(
        Panel(
            f"identity key id: [cyan]{public_key_id(keypair.public_pem)}[/cyan]\n"
            f"store: {store.root}\n"
            f"Share your public key so others can trust your graphs:\n"
            f"  {store.identity_dir / 'public.pem'}",
            title="[green]Local signing identity[/green]",
            border_style="green",
        )
    )


@trust_app.command("add")
def trust_add(
    public_key_path: str = typer.Argument(..., help="Path to a public key PEM to trust."),
    name: str = typer.Option("", "--name", help="Human label for this key's owner."),
) -> None:
    """Trust an author's public key. Only do this if you vouch for them."""
    pem = Path(public_key_path).read_text(encoding="utf-8")
    key = TrustStore().trust(pem, name=name)
    console.print(
        f"[green]Trusted[/green] key [cyan]{key.key_id}[/cyan]"
        + (f" ({name})" if name else "")
        + " — graphs signed by it will now run under --require-signed."
    )


@trust_app.command("list")
def trust_list() -> None:
    """List every trusted key."""
    keys = TrustStore().trusted_keys()
    if not keys:
        console.print("No trusted keys. Run 'fukasawa trust keygen' to start.")
        return
    table = Table(title="Trusted keys")
    table.add_column("Key id")
    table.add_column("Name")
    for k in keys:
        table.add_row(k.key_id, k.name or "-")
    console.print(table)


@trust_app.command("revoke")
def trust_revoke(
    key_id: str = typer.Argument(..., help="Key id to stop trusting."),
) -> None:
    """Remove a key from the trusted set."""
    if TrustStore().revoke(key_id):
        console.print(f"[yellow]Revoked[/yellow] {key_id}.")
    else:
        console.print(f"[red]No such trusted key:[/red] {key_id}")
        raise typer.Exit(1)


# ---------------------------------------------------------------------- bundle


@bundle_app.command("export")
def bundle_export(
    brief_path: str = typer.Argument(..., help="Path to the workflow brief YAML."),
    out: str = typer.Option(..., "--out", help="Path to write the .fkz bundle to."),
    graph: list[str] = typer.Option(
        [], "--graph", help="Graph YAML to include (repeatable)."
    ),
    package: list[str] = typer.Option(
        [], "--package", help="Agent package directory to include (repeatable)."
    ),
    eval_case: list[str] = typer.Option(
        [], "--eval", help="Eval case YAML to include (repeatable)."
    ),
    description: str = typer.Option(
        "", "--description", help="Plain-language summary for the receiving operator."
    ),
) -> None:
    """Export a workflow into a signed, shareable bundle.

    Every artifact is validated before it is packed — graphs and evals must
    name the brief's workflow, and each agent package must pass its Foundry
    validation — so a written bundle is always one that will survive import.
    """
    from src.runtime.bundle import BundleError, export_bundle

    try:
        manifest = export_bundle(
            brief_path=brief_path,
            out_path=out,
            graph_paths=graph,
            package_dirs=package,
            eval_paths=eval_case,
            description=description,
        )
    except ValidationError as exc:
        _print_validation_error(exc, "Bundle artifact")
        raise typer.Exit(1)
    except BundleError as exc:
        console.print(
            Panel(escape(str(exc)), title="[red]Export refused[/red]", border_style="red")
        )
        raise typer.Exit(1)
    counts = {role: 0 for role in ("brief", "graph", "package", "eval")}
    for entry in manifest.entries:
        counts[entry.role.value] += 1
    console.print(
        Panel(
            f"[bold]{manifest.bundle_id}[/bold] — workflow `{manifest.workflow_id}`\n"
            f"{counts['graph']} graph(s), {counts['package']} package file(s), "
            f"{counts['eval']} eval(s)\n"
            f"signed by key [cyan]{manifest.signer_key_id}[/cyan]",
            title="[green]Bundle exported[/green]",
            border_style="green",
        )
    )
    console.print(f"Written: [cyan]{out}[/cyan]")


@bundle_app.command("inspect")
def bundle_inspect(
    bundle_path: str = typer.Argument(..., help="Path to a .fkz bundle."),
) -> None:
    """Verify a bundle's signature and file hashes without extracting it."""
    from src.runtime.bundle import BundleError, inspect_bundle

    try:
        result = inspect_bundle(bundle_path)
    except BundleError as exc:
        console.print(
            Panel(escape(str(exc)), title="[red]Bundle rejected[/red]", border_style="red")
        )
        raise typer.Exit(1)
    m = result.manifest
    trust_line = (
        "[green]trusted signer[/green]"
        if result.signer_trusted
        else "[yellow]signer NOT in your trust store[/yellow]"
    )
    table = Table(title=f"{m.bundle_id} — {m.description}")
    for col in ("Path", "Role", "SHA-256"):
        table.add_column(col)
    for entry in m.entries:
        table.add_row(entry.path, entry.role.value, entry.sha256[:16] + "…")
    console.print(
        Panel(
            f"workflow `{m.workflow_id}` — {len(m.entries)} file(s)\n"
            f"signer key [cyan]{m.signer_key_id}[/cyan] — {trust_line}\n"
            f"hashes: [green]all match[/green]",
            title="[green]Bundle is intact[/green]",
            border_style="green" if result.signer_trusted else "yellow",
        )
    )
    console.print(table)
    if not result.signer_trusted:
        console.print(
            "To import this bundle, trust the signer's key first: "
            "'fukasawa trust add <public.pem>'."
        )


@bundle_app.command("import")
def bundle_import(
    bundle_path: str = typer.Argument(..., help="Path to a .fkz bundle."),
    dest: str = typer.Option(..., "--dest", help="Directory to unpack the bundle into."),
    allow_untrusted: bool = typer.Option(
        False,
        "--allow-untrusted",
        help="Skip the trust gate (hash checks still run). Only for your own exports.",
    ),
) -> None:
    """Verify and unpack a bundle — refusing untrusted or tampered archives.

    Signature and hashes are checked while the bundle is still bytes in memory;
    nothing is written to --dest unless both pass.
    """
    from src.runtime.bundle import (
        BundleError,
        BundleTamperError,
        UntrustedBundleError,
        import_bundle,
    )

    try:
        result = import_bundle(
            bundle_path, dest, require_trusted=not allow_untrusted
        )
    except UntrustedBundleError as exc:
        console.print(
            Panel(escape(str(exc)), title="[red]Untrusted bundle[/red]", border_style="red")
        )
        raise typer.Exit(1)
    except BundleTamperError as exc:
        console.print(
            Panel(escape(str(exc)), title="[red]Bundle tampered[/red]", border_style="red")
        )
        raise typer.Exit(1)
    except BundleError as exc:
        console.print(
            Panel(escape(str(exc)), title="[red]Bundle rejected[/red]", border_style="red")
        )
        raise typer.Exit(1)
    trust_note = (
        "trusted signer"
        if result.signer_trusted
        else "[yellow]untrusted signer — imported under --allow-untrusted[/yellow]"
    )
    console.print(
        Panel(
            f"[bold]{result.manifest.bundle_id}[/bold] — workflow "
            f"`{result.manifest.workflow_id}`\n"
            f"{len(result.extracted)} file(s) unpacked to [cyan]{result.dest}[/cyan]\n"
            f"signer key [cyan]{result.signer_key_id}[/cyan] — {trust_note}",
            title="[green]Bundle imported[/green]",
            border_style="green",
        )
    )


# ----------------------------------------------------------------------- model


@model_app.command("list")
def model_list() -> None:
    """List configured model endpoints, and say where to add your own.

    The second half matters more than the first. This runtime is meant to be
    handed to someone who runs their own hardware, and until now the only
    statement of where endpoints are configured lived in one line of source:
    a user saw two localhost defaults and nothing telling them the file
    existed, let alone where. Printing the path — whether or not it exists yet
    — is the difference between a configurable product and one that looks
    hardcoded.
    """
    from src.security.trust import DEFAULT_TRUST_ROOT

    registry = _model_endpoints()
    table = Table(title="Model endpoints")
    table.add_column("Name")
    table.add_column("Kind")
    table.add_column("URL")
    for name in registry.names():
        ep = registry.get(name)
        table.add_row(ep.name, ep.kind, ep.url)
    console.print(table)
    console.print(
        "Reference these by name in a graph's model node: "
        "[cyan]endpoint: local-ollama[/cyan]"
    )

    # soft_wrap on every line carrying the path: rich wraps to terminal width by
    # default and will happily break a long path mid-filename, producing
    # something the operator cannot copy. A path is not prose.
    config = DEFAULT_TRUST_ROOT / "model_endpoints.yaml"
    if config.exists():
        console.print("\nConfigured in:")
        console.print(f"[cyan]{config}[/cyan]", soft_wrap=True)
    else:
        console.print(
            "\nThese are the built-in defaults. To add your own inference "
            "nodes, create:"
        )
        console.print(f"[cyan]{config}[/cyan]", soft_wrap=True)
        console.print()
        console.print(_ENDPOINT_TEMPLATE)
    console.print(
        "An endpoint is a name, a kind and a URL — it carries no capabilities, "
        "so nothing yet checks whether a node can run a given step. See "
        "'Known gaps' in the README."
    )


#: Shown by `model list` when no endpoint config exists yet. A template beats a
#: path alone: the file has never existed on this machine, so there is nothing
#: for the user to open and read the shape of.
_ENDPOINT_TEMPLATE = """[dim]endpoints:
  my-gpu-box:
    kind: ollama        # ollama | llamacpp
    url: http://192.168.1.50:11434[/dim]"""


@model_app.command("test")
def model_test(
    endpoint: str = typer.Argument(..., help="Endpoint name to probe."),
    model: str = typer.Option(..., "--model", help="Model identifier to load."),
    prompt: str = typer.Option("Say 'ready' and nothing else.", "--prompt"),
    timeout: float = typer.Option(30.0, "--timeout"),
) -> None:
    """Send one prompt to a model endpoint and print the reply (or the failure)."""
    from src.kernel.models import ModelAdapter

    adapter = ModelAdapter(_model_endpoints())
    result = adapter.execute(
        {"endpoint": endpoint, "model": model, "prompt": prompt, "timeout": timeout}
    )
    if result.ok:
        console.print(
            Panel(escape(result.evidence), title=f"[green]{endpoint} replied[/green]")
        )
    else:
        console.print(
            Panel(escape(result.note), title=f"[red]{endpoint} failed[/red]", border_style="red")
        )
        raise typer.Exit(1)


# ------------------------------------------------------------------------- node


def _discover(scope, host="", **kwargs):
    """Run a scan. Named so a test can replace it without a live network."""
    from src.nodes.discovery import discover

    return discover(scope, host, **kwargs)


def _node_store():
    """Open the store at its configured location."""
    from src.nodes.store import NodeStore

    return NodeStore()


#: Both directions of the scope vocabulary, declared once. The CLI flag values
#: are hyphenated; the enum values are not; the sentence is neither.
_SCOPE_FLAGS = {
    "none": "NONE",
    "this-machine": "THIS_MACHINE",
    "named-host": "NAMED_HOST",
    "local-network": "LOCAL_NETWORK",
}
_SCOPE_WORDS = {
    "NONE": "Not looking at anything",
    "THIS_MACHINE": "Just this computer",
    "NAMED_HOST": "One computer, named",
    "LOCAL_NETWORK": "Every computer on this network",
}


def _scope_from(text: str):
    """Turn a --scope value into a ScanScope, or exit 1 naming the choices."""
    from src.schemas.node import ScanScope

    if text not in _SCOPE_FLAGS:
        console.print(
            f"[red]'{escape(text)}' is not one of the choices.[/red] "
            f"Use one of: {', '.join(_SCOPE_FLAGS)}"
        )
        raise typer.Exit(1)
    return ScanScope(_SCOPE_FLAGS[text])


def _render_summary(nodes) -> None:
    """Print the panel: figures with units, and at most one consequence.

    ``SummaryRow`` deliberately carries no ``source`` (see
    ``src/nodes/summary.py``) — each figure on this panel is a maximum taken
    across every computer, so a per-node provenance label would beg the
    question "on which one?" Only the label and the value are printed.
    """
    from src.nodes.summary import summarise

    summary = summarise(nodes)
    console.print("\n[bold]What this means when steps run[/bold]")
    for row in summary.rows:
        # The first row is a list of the labels people chose, so it is their
        # text, not ours. escape() keeps a square bracket in a label from
        # being read as formatting and aborting the print.
        console.print(f"  {row.label:<32} {escape(row.value)}")
    if summary.consequence:
        console.print(f"\n  {summary.consequence}")


@node_app.command("scan")
def node_scan(
    scope: str = typer.Option(
        "", "--scope", help="none | this-machine | named-host | local-network"
    ),
    host: str = typer.Option("", "--host", help="Address, for --scope named-host."),
    label: str = typer.Option("", "--label", help="What to call what is found."),
    yes: bool = typer.Option(False, "--yes", help="Skip the prompts."),
    as_json: bool = typer.Option(False, "--json", help="One event per line, as JSON."),
) -> None:
    """Look for computers that can run AI, and record what is found.

    Nothing is examined until a permission is chosen. Findings are printed as
    they arrive rather than in a block at the end, because a scan takes time
    and a person watching one deserves to see it happening.
    """
    from src.schemas.node import ScanConsent, ScanScope

    store = _node_store()
    _nodes, existing = store.load()

    if scope:
        chosen = _scope_from(scope)
    elif yes:
        chosen = existing.scope
    else:
        console.print(
            "\nFukasawa can run some workflow steps automatically, using AI\n"
            "on a computer you point it at.\n"
        )
        console.print("[bold]Where should I look?[/bold]")
        console.print("  1  Just this computer            nothing leaves this machine")
        console.print("  2  A computer I'll name")
        console.print("  3  Every computer on this network  takes about a minute; some")
        console.print("                                     workplaces disallow this")
        console.print("  4  Don't look — I'll type it in")
        answer = typer.prompt("Choose", default="1")
        chosen = {
            "1": ScanScope.THIS_MACHINE,
            "2": ScanScope.NAMED_HOST,
            "3": ScanScope.LOCAL_NETWORK,
            "4": ScanScope.NONE,
        }.get(answer.strip(), ScanScope.THIS_MACHINE)

    if chosen is ScanScope.NONE:
        console.print(
            "[yellow]Refused:[/yellow] no permission to look. "
            "Choose a different option, or add a computer with "
            "[cyan]fukasawa node add[/cyan]."
        )
        raise typer.Exit(3)

    if chosen is ScanScope.NAMED_HOST and not host:
        host = typer.prompt("Address of the computer")

    store.set_consent(ScanConsent.granted(chosen, "operator"))

    console.print("")
    found = []
    for event in _discover(chosen, host):
        if as_json:
            # A plain print, not console.print: Rich wraps to the window and
            # would split a message in two. Not `_emit_json` either — that
            # helper indents across several lines, and the design (§3.7) calls
            # this a stream of one object per line. So: dumped flat, printed
            # raw. NOTE: src/cli.py imports the json module as `jsonlib`.
            print(jsonlib.dumps({
                "stage": event.stage, "message": event.message,
                "ok": event.ok, "finished": event.finished,
            }))
        else:
            mark = "  [green]OK[/green]" if event.ok else "  [yellow]--[/yellow]"
            # A finding quotes model names read off another computer, so the
            # text is not ours and is escaped before it is printed.
            console.print(f"{mark}  {escape(event.message)}")
        if event.node is not None and event.node not in found:
            found.append(event.node)

    for node in found:
        if label:
            node.label = label
        store.upsert(node)

    if found:
        _render_summary(store.load()[0])


@node_app.command("list")
def node_list(
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Show every computer Fukasawa has been told about."""
    nodes, _consent = _node_store().load()
    if as_json:
        _emit_json({"nodes": [n.model_dump(mode="json") for n in nodes]})
        return

    from src.nodes.summary import human_words, source_label

    for node in nodes:
        # Label and address are both typed by a person; escape() keeps a
        # square bracket in either from being read as formatting.
        console.print(
            f"\n[bold]{escape(node.label)}[/bold]  [dim]{escape(node.url)}[/dim]"
        )
        console.print(f"  Models it can run    {len(node.models)}")
        if node.max_context_length:
            console.print(
                f"  Longest input        {human_words(node.max_context_length)}"
                f"   [dim]{source_label(node.source_of('models'))}[/dim]"
            )
    _render_summary(nodes)


@node_app.command("show")
def node_show(node_id: str = typer.Argument(..., help="Which computer.")) -> None:
    """Show one computer and every model it can serve."""
    nodes, _ = _node_store().load()
    match = next((n for n in nodes if n.node_id == node_id), None)
    if match is None:
        console.print(f"[red]Nothing stored called '{escape(node_id)}'.[/red]")
        raise typer.Exit(1)

    from src.nodes.summary import human_bytes, human_rate, human_words

    console.print(
        f"\n[bold]{escape(match.label)}[/bold]  [dim]{escape(match.url)}[/dim]"
    )
    console.print(f"  Answering            {'yes' if match.reachable else 'no'}")
    console.print(f"  Speed                {human_rate(match.host.tokens_per_second)}")
    console.print(f"  Graphics card        {human_bytes(match.host.vram_bytes)}")
    for model in match.models:
        # A model name is read off another computer, so it is escaped. Padding
        # happens first and escaping second, so the column still lines up: the
        # backslashes escape() adds are not printed.
        console.print(
            f"    {escape(f'{model.name:<28}')} {human_words(model.context_length)}"
        )


@node_app.command("add")
def node_add(
    label: str = typer.Option(..., "--label", help="What to call it."),
    kind: str = typer.Option(..., "--kind", help="ollama | llamacpp"),
    url: str = typer.Option(..., "--url", help="Base URL it answers on."),
) -> None:
    """Add a computer by hand, without looking for it."""
    from src.schemas.node import InferenceNode, NodeKind, Provenance, slugify

    if kind not in {k.value for k in NodeKind}:
        console.print(f"[red]'{escape(kind)}' is not one of: ollama, llamacpp[/red]")
        raise typer.Exit(1)

    node = InferenceNode(
        node_id=slugify(label), label=label, kind=NodeKind(kind), url=url,
        provenance={
            "label": Provenance.DECLARED,
            "url": Provenance.DECLARED,
            "kind": Provenance.DECLARED,
        },
    )
    _node_store().upsert(node)
    console.print(f"Added [bold]{escape(label)}[/bold].")


@node_app.command("forget")
def node_forget(node_id: str = typer.Argument(..., help="Which computer.")) -> None:
    """Remove a computer."""
    if not _node_store().forget(node_id):
        console.print(f"[red]Nothing stored called '{escape(node_id)}'.[/red]")
        raise typer.Exit(1)
    console.print(f"Removed {escape(node_id)}.")


@node_app.command("consent")
def node_consent(
    set_to: str = typer.Option("", "--set", help="none | this-machine | named-host | local-network"),
) -> None:
    """Show or change how far a scan may reach."""
    from src.schemas.node import ScanConsent

    store = _node_store()
    _nodes, consent = store.load()
    if not set_to:
        console.print(f"Currently: {_SCOPE_WORDS[consent.scope.value]}")
        return
    chosen = _scope_from(set_to)
    store.set_consent(ScanConsent.granted(chosen, "operator"))
    console.print(f"Changed to: {_SCOPE_WORDS[chosen.value]}")


# ------------------------------------------------------------------------ eval


@eval_app.command("run")
def eval_run(
    case_path: str = typer.Argument(..., help="Path to an eval case YAML file."),
    run_id: str = typer.Option(..., "--run-id", help="The recorded run to evaluate."),
    package: Optional[str] = typer.Option(
        None, "--package", help="Agent package dir for depth/escalation checks."
    ),
    db: str = _DB_OPTION,
    handoff_dir: str = _HANDOFF_OPTION,
) -> None:
    """Run one eval case against a run's recorded artifacts."""
    try:
        case = load_eval_case(case_path)
    except ValidationError as exc:
        _print_validation_error(exc, f"Eval case '{case_path}'")
        raise typer.Exit(1)
    result = run_eval_case(
        case, RunLedger(db), run_id, package_dir=package, handoff_dir=handoff_dir
    )
    table = Table(title=f"{case.case_id} — {case.name}")
    table.add_column("Check")
    table.add_column("Outcome")
    table.add_column("Evidence")
    for check in result.checks:
        color = {"pass": "green", "fail": "red", "skipped": "yellow"}[check.outcome.value]
        table.add_row(
            check.category.value,
            f"[{color}]{check.outcome.value}[/{color}]",
            escape(check.evidence),
        )
    console.print(table)
    overall_color = "green" if result.overall.value == "pass" else "red"
    console.print(
        f"Overall: [{overall_color}]{result.overall.value}[/{overall_color}] "
        f"(recorded as {result.result_id})"
    )
    if result.overall.value != "pass":
        raise typer.Exit(1)


# -------------------------------------------------------------------- maturity


def _print_maturity_report(report) -> None:
    """Render a maturity report as a criteria table."""
    title = (
        f"{report.agent}: {report.current.value}"
        + (f" -> {report.target.value}?" if report.target else " (terminal)")
    )
    table = Table(title=title)
    table.add_column("Criterion")
    table.add_column("Met")
    table.add_column("Evidence")
    for c in report.criteria:
        table.add_row(
            c.name,
            "[green]yes[/green]" if c.met else "[red]NO[/red]",
            escape(c.detail),
        )
    console.print(table)
    if report.target:
        verdict = (
            "[green]criteria met — promotion available (human reviewer required)[/green]"
            if report.allowed
            else "[red]promotion blocked on the evidence above[/red]"
        )
        console.print(verdict)


@maturity_app.command("report")
def maturity_report(
    package_dir: str = typer.Argument(..., help="Agent package directory."),
    db: str = _DB_OPTION,
) -> None:
    """Show the evidence picture for the package's next maturity step."""
    _print_maturity_report(assess(package_dir, RunLedger(db)))


@maturity_app.command("promote")
def maturity_promote(
    package_dir: str = typer.Argument(..., help="Agent package directory."),
    reviewed_by: str = typer.Option(
        ..., "--reviewed-by", help="Human reviewer attesting to the promotion."
    ),
    rationale: str = typer.Option(
        "",
        "--rationale",
        help="Required for tested->validated: lower-depth consideration rationale.",
    ),
    db: str = _DB_OPTION,
) -> None:
    """Promote a package one maturity step if — and only if — evidence allows."""
    try:
        report = promote(
            package_dir, RunLedger(db), reviewed_by=reviewed_by, rationale=rationale
        )
    except PromotionRefusedError as exc:
        console.print(
            Panel(escape(str(exc)), title="[red]Promotion refused[/red]", border_style="red")
        )
        raise typer.Exit(1)
    console.print(
        f"[green]Promoted.[/green] {report.agent} is now [bold]{report.current.value}[/bold]."
    )


# ------------------------------------------------------------ nonconformance


@nonconformance_app.command("capture")
def nonconformance_capture(
    workflow_id: str = typer.Option(..., "--workflow", help="Workflow the breach belongs to."),
    capsule_id: str = typer.Option("", "--capsule", help="Capsule involved, if any."),
    kind: str = typer.Option(
        "other",
        "--kind",
        help="no_valid_path | missing_evidence | review_rejected | other",
    ),
    from_state: str = typer.Option("", "--from-state", help="State when the breach occurred."),
    note: str = typer.Option(..., "--note", help="What happened. Never empty."),
    db: str = _DB_OPTION,
) -> None:
    """Manually capture a non-conformance the runtime could not see itself."""
    import uuid as _uuid

    from src.schemas.non_conformance import NonConformanceKind, NonConformanceRecord

    record = NonConformanceRecord(
        id=f"ncr-{_uuid.uuid4().hex[:8]}",
        workflow_id=workflow_id,
        capsule_id=capsule_id,
        kind=NonConformanceKind(kind),
        from_state=from_state,
        note=note,
    )
    RunLedger(db).save_non_conformance_record(record)
    console.print(f"Captured [cyan]{record.id}[/cyan] ({record.kind.value}).")


@nonconformance_app.command("resolve")
def nonconformance_resolve(
    record_id: str = typer.Argument(..., help="Non-conformance record id."),
    note: str = typer.Option(
        ...,
        "--note",
        help=(
            "The concrete process change that closes this record (e.g. 'removed "
            "redundant review step', 'added missing transition to brief')."
        ),
    ),
    db: str = _DB_OPTION,
) -> None:
    """Resolve a non-conformance record with the process change it produced.

    Doctrine: corrective action considers removing or simplifying steps
    before adding controls — the note should say which happened.
    """
    from src.schemas.non_conformance import ResolutionStatus

    ledger = RunLedger(db)
    record = next(
        (r for r in ledger.non_conformance_records() if r.id == record_id), None
    )
    if record is None:
        console.print(f"[red]Unknown record:[/red] {record_id}")
        raise typer.Exit(1)
    record.resolution_status = ResolutionStatus.RESOLVED
    record.resolution_note = note
    ledger.save_non_conformance_record(record)
    console.print(f"[green]Resolved {record_id}.[/green] Process change: {note}")


@nonconformance_app.command("patterns")
def nonconformance_patterns(db: str = _DB_OPTION) -> None:
    """Group non-conformance records by workflow and kind — repeats are the signal.

    Repeated failures must trigger non-conformance review, and the first
    corrective question is always: can a step be removed or simplified?
    """
    records = RunLedger(db).non_conformance_records()
    if not records:
        console.print("[green]No non-conformance records.[/green]")
        return
    groups: dict[tuple, list] = {}
    for r in records:
        groups.setdefault((r.workflow_id, r.kind.value), []).append(r)
    table = Table(title="Non-conformance patterns")
    for col in ("Workflow", "Kind", "Count", "Open", "Signal"):
        table.add_column(col)
    for (workflow_id, kind), group in sorted(
        groups.items(), key=lambda kv: -len(kv[1])
    ):
        open_count = sum(1 for r in group if r.resolution_status.value == "open")
        repeated = len(group) >= 2
        signal = (
            "[red]REPEAT — review process: remove or simplify before adding controls[/red]"
            if repeated and open_count
            else "[yellow]repeat, resolved[/yellow]"
            if repeated
            else "-"
        )
        table.add_row(workflow_id, kind, str(len(group)), str(open_count), signal)
    console.print(table)


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


@nonconformance_app.command("records")
def nonconformance_records(
    open_only: bool = typer.Option(
        False, "--open", help="Show only records still awaiting resolution."
    ),
    db: str = _DB_OPTION,
) -> None:
    """Show structured non-conformance records — failure kinds, not just events."""
    records = RunLedger(db).non_conformance_records(open_only=open_only)
    if not records:
        console.print("[green]No non-conformance records.[/green]")
        return
    table = Table(title="Non-conformance records")
    for col in ("Id", "Kind", "Workflow", "From", "Attempted", "Status", "Note"):
        table.add_column(col)
    for r in records:
        table.add_row(
            r.id,
            r.kind.value,
            r.workflow_id,
            r.from_state,
            r.attempted_state or "-",
            r.resolution_status.value,
            r.note,
        )
    console.print(table)


# ===================================================== human & cooperative
#
# The lifecycle sub-app. Everything above operates on a WorkflowBrief that
# somebody already wrote; these commands are how a brief comes to exist —
# capture what actually happens, find the gaps, resolve accountability, decide
# who does each step, and only then export something runnable.
#
# Two conventions apply here and not to the commands above, which are frozen by
# the phase boundary: every command takes --json, and exit codes distinguish an
# operator's mistake from the runtime's refusal. See EXIT_* below.

#: Exit codes for the workflow sub-app. Stable: a script may branch on these.
#:
#: The distinction that matters is 1 versus 2/3. A 1 means *you* made a mistake
#: and should fix your input. A 2 or 3 means the input was understood and the
#: runtime declined — which is the product working, not failing.
EXIT_OK = 0
#: Bad path, malformed YAML, missing prerequisite, contradictory flags.
EXIT_INPUT = 1
#: Understood and refused for now: unresolved blocking findings, promotion not
#: ready. Fix the workflow and the same command will succeed.
EXIT_BLOCKED = 2
#: Understood and refused as a matter of doctrine: an override that would cross
#: a safety floor, an unapproved export, a gateless autonomous agent. Fixing the
#: input is the wrong response; reconsider the request.
EXIT_REFUSED = 3

_JSON_OPTION = typer.Option(
    False, "--json", help="Emit machine-readable JSON instead of tables."
)

#: Set per invocation by every workflow command. A CLI process handles one
#: command, so a module global is honest here — but it is written at the top of
#: each command rather than once, so a test harness reusing the process cannot
#: leak the previous invocation's mode into the next.
_json_mode = False


def _set_json(enabled: bool) -> None:
    """Select output mode for this invocation."""
    global _json_mode
    _json_mode = enabled


def _emit_json(payload: dict) -> None:
    """Print one JSON object on stdout, with no Rich markup anywhere in it.

    Uses a plain print rather than the Rich console: Rich wraps long lines to
    the terminal width, which would corrupt JSON for the caller parsing it.
    """
    print(jsonlib.dumps(payload, indent=2, sort_keys=False))


def _problems(exc: ValidationError) -> list[dict]:
    """Pydantic errors as plain data, for the --json error path."""
    return [
        {
            "field": ".".join(str(p) for p in err["loc"]) or "(root)",
            "problem": err["msg"],
        }
        for err in exc.errors()
    ]


def _fail_input(message: str) -> None:
    """Report an operator mistake and exit 1. Never raises past the boundary."""
    if _json_mode:
        _emit_json({"ok": False, "error": "input", "message": message})
    else:
        console.print(f"[red]Error:[/red] {escape(message)}")
    raise typer.Exit(EXIT_INPUT)


def _fail_refused(message: str, *, error: str) -> None:
    """Report a doctrine refusal and exit 3.

    Refusal messages are written to be read by the person who hit them, so they
    are printed whole rather than summarized.
    """
    if _json_mode:
        _emit_json({"ok": False, "error": error, "message": message})
    else:
        console.print(f"[red]Refused:[/red] {escape(message)}")
    raise typer.Exit(EXIT_REFUSED)


def _report_kept_human(step_ids: list[str]) -> None:
    """Say which steps stayed with a person, and never treat it as a shortfall.

    An operator who exports a workflow and reads only "2 packages generated"
    has learned nothing about the six steps still on their desk. That silence
    is the failure mode this product exists to prevent, so the count is always
    reported — including when it is zero.
    """
    if step_ids:
        console.print(
            f"\n[bold]{len(step_ids)} step(s) stay with a person:[/bold] "
            f"{', '.join(step_ids)}"
        )
    else:
        console.print("\n[bold]No steps stay with a person.[/bold]")


def _load_draft_file(path: str) -> HumanWorkflowDraft:
    """Read a workflow draft from YAML, exiting cleanly on a bad file.

    Never raises past the CLI boundary: a missing file and a malformed one are
    both ordinary operator mistakes, and a traceback is not an error message.
    """
    # resolve() prefers the operator's working directory and falls back to the
    # copy bundled in the PyInstaller binary, so every documented example path
    # works identically from a checkout and from the executable.
    file = resources.resolve(path)
    if not file.exists():
        _fail_input(f"No such file: {path}")
    try:
        raw = yaml.safe_load(file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        _fail_input(f"{path} is not valid YAML: {exc}")
    if not isinstance(raw, dict):
        _fail_input(f"{path} does not contain a workflow draft (expected a mapping).")
    try:
        return HumanWorkflowDraft.model_validate(raw)
    except ValidationError as exc:
        if _json_mode:
            _emit_json({"ok": False, "error": "invalid_draft", "problems": _problems(exc)})
        else:
            _print_validation_error(exc, subject=path)
        raise typer.Exit(EXIT_INPUT)


def _finding_row(finding: WorkflowFinding) -> dict:
    """One finding as plain data, for --json and for table rendering alike."""
    return {
        "finding_id": finding.finding_id,
        "rule_id": finding.rule.rule_id,
        "rule_version": finding.rule.rule_version,
        "type": finding.finding_type.value,
        "severity": finding.severity.value,
        "blocking": finding.blocking,
        "message": finding.message,
        "step_id": finding.location.step_id or "",
        "gate_id": finding.location.gate_id or "",
        "field": finding.location.field or "",
        "remediation": finding.remediation,
        "accepted": finding.acceptance is not None,
    }


def _print_findings(report: ValidationReport) -> None:
    """Render a validation report as a table, blocking findings first."""
    if not report.findings:
        console.print(f"[green]No findings[/green] for '{report.workflow_id}'.")
        return
    table = Table(
        title=f"{report.workflow_id} — {len(report.findings)} finding(s), "
        f"rule set v{report.rule_set_version}"
    )
    for col in ("Rule", "Policy", "Where", "Problem", "Remediation"):
        table.add_column(col)
    ordered = sorted(report.findings, key=lambda f: (not f.blocking, f.rule.rule_id))
    for f in ordered:
        if f.acceptance is not None:
            policy = "[dim]accepted[/dim]"
        elif f.blocking:
            policy = "[red]blocking[/red]"
        else:
            policy = "[yellow]advisory[/yellow]"
        where = f.location.step_id or f.location.gate_id or "(workflow)"
        if f.location.field:
            where += f".{f.location.field}"
        table.add_row(
            f.rule.rule_id, policy, escape(where), escape(f.message), escape(f.remediation)
        )
    console.print(table)


@workflow_app.command("init")
def workflow_init(
    workflow_id: str = typer.Argument(..., help="Slug for the new workflow, e.g. weekly-report."),
    out: str = typer.Option("", "--out", help="Where to write it. Defaults to <workflow_id>.yaml."),
    name: str = typer.Option("", "--name", help="Human-readable name. Defaults to the slug."),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing file."),
    json_out: bool = _JSON_OPTION,
) -> None:
    """Write a workflow draft skeleton to fill in by hand.

    The skeleton is a valid but deliberately incomplete draft: it saves and
    reloads, and `workflow validate` will tell you exactly what is missing.
    That order is the point — capture what happens first, discover the gaps
    second. A tool that refused to record an incomplete process would make
    honest capture impossible.
    """
    _set_json(json_out)
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", workflow_id):
        _fail_input(
            f"'{workflow_id}' is not a valid workflow id. Use lowercase words "
            f"separated by hyphens, e.g. weekly-report."
        )
    target = Path(out) if out else Path(f"{workflow_id}.yaml")
    if target.exists() and not force:
        _fail_input(f"{target} already exists. Pass --force to overwrite it.")

    skeleton = DRAFT_SKELETON.format(
        workflow_id=workflow_id, name=name or workflow_id.replace("-", " ").title()
    )
    try:
        target.write_text(skeleton, encoding="utf-8")
    except OSError as exc:
        _fail_input(f"Could not write {target}: {exc}")

    if _json_mode:
        _emit_json({"ok": True, "workflow_id": workflow_id, "path": str(target)})
        return
    console.print(f"Wrote draft skeleton: [cyan]{target}[/cyan]")
    console.print(
        "\nFill in the [bold]trigger[/bold], [bold]claimed_outcome[/bold], and each "
        "step's [bold]actor[/bold] and [bold]outputs[/bold] — those are what the "
        "blocking rules check first. Record what actually happens, gaps "
        "included.\n"
        f"Then run: [cyan]fukasawa workflow validate {target}[/cyan]"
    )


@workflow_app.command("validate")
def workflow_validate(
    path: str = typer.Argument(..., help="Path to a workflow draft YAML file."),
    db: str = _DB_OPTION,
    save: bool = typer.Option(
        False, "--save", help="Store the draft and its report in the ledger."
    ),
    json_out: bool = _JSON_OPTION,
) -> None:
    """Check a draft against the 16 deterministic rules.

    Exits 2 when an unresolved blocking finding remains — that blocks promotion
    to ACCOUNTABLE, and nothing else. It never blocks saving: `--save` stores
    the draft either way, because a workflow is allowed to be a mess while you
    are still writing down what it is.
    """
    _set_json(json_out)
    draft = _load_draft_file(path)
    ledger = RunLedger(db)
    report = validate_workflow(draft)
    # Validation is stateless, so a finding a human already accepted comes back
    # looking unaccepted. Re-attach before reporting, or the operator is shown a
    # decision they made as though they had not made it.
    reattach_acceptances(report, ledger)

    if save:
        ledger.save_workflow_draft(draft)
        ledger.save_validation_report(report)

    blocking = [f for f in report.unresolved_blocking]
    if _json_mode:
        _emit_json(
            {
                "ok": report.promotion_ready,
                "workflow_id": report.workflow_id,
                "rule_set_version": report.rule_set_version,
                "promotion_ready": report.promotion_ready,
                "findings": [_finding_row(f) for f in report.findings],
                "unresolved_blocking": [f.finding_id for f in blocking],
                "saved": save,
            }
        )
    else:
        _print_findings(report)
        if save:
            console.print(f"Draft and report saved to [cyan]{db}[/cyan].")
        if report.promotion_ready:
            console.print(
                f"\n[green]Promotion ready.[/green] Next: "
                f"[cyan]fukasawa workflow promote {path} --by <your name>[/cyan]"
            )
        else:
            console.print(
                f"\n[red]{len(blocking)} unresolved blocking finding(s).[/red] "
                f"Fix them in {path}, then validate again."
            )
    if not report.promotion_ready:
        raise typer.Exit(EXIT_BLOCKED)


@workflow_app.command("findings")
def workflow_findings(
    path: str = typer.Argument(..., help="Path to a workflow draft YAML file."),
    rule: str = typer.Option("", "--rule", help="Show only this rule id, e.g. HW-004."),
    blocking_only: bool = typer.Option(
        False, "--blocking-only", help="Hide advisory findings."
    ),
    json_out: bool = _JSON_OPTION,
) -> None:
    """List a draft's findings without judging whether it may be promoted.

    Always exits 0 when the draft loads. `validate` is the gate; this is the
    lens. Separating them means a script can read findings without having to
    treat their existence as a failure.
    """
    _set_json(json_out)
    draft = _load_draft_file(path)
    report = validate_workflow(draft, rule_ids=[rule] if rule else None)
    findings = [f for f in report.findings if not blocking_only or f.blocking]

    if _json_mode:
        _emit_json(
            {
                "ok": True,
                "workflow_id": report.workflow_id,
                "count": len(findings),
                "findings": [_finding_row(f) for f in findings],
            }
        )
        return
    if rule and not findings:
        console.print(f"No findings for rule [bold]{rule}[/bold] in '{report.workflow_id}'.")
        return
    filtered = report.model_copy(update={"findings": findings})
    _print_findings(filtered)


@workflow_app.command("accept-risk")
def workflow_accept_risk(
    path: str = typer.Argument(..., help="Path to a workflow draft YAML file."),
    finding: str = typer.Option(
        ..., "--finding", help="Finding id to accept, e.g. 'HW-013:workflow'."
    ),
    by: str = typer.Option(..., "--by", help="Who is accepting it (self-attested)."),
    why: str = typer.Option(..., "--why", help="Why this risk is acceptable."),
    db: str = _DB_OPTION,
) -> None:
    """Consciously accept an advisory finding as residual risk.

    Accepting records a decision; it does not unlock anything. Advisory findings
    never gated promotion, so this changes no outcome — what it changes is
    whether the reason is on the record. HW-013 and HW-014 are the heuristic
    pair, and "we know about this and it is fine" is a different statement from
    silence.

    A **blocking** finding cannot be accepted and exits 3. Waiving one would
    turn the promotion gate into a formality.
    """
    _set_json(False)
    draft = _load_draft_file(path)
    ledger = RunLedger(db)
    report = validate_workflow(draft)
    reattach_acceptances(report, ledger)

    try:
        acceptance = accept_risk(
            ledger,
            draft.workflow_id,
            report,
            finding_id=finding,
            accepted_by=by,
            rationale=why,
        )
    except RiskAcceptanceRefusedError as exc:
        # An unknown finding id is the operator mistyping; a blocking finding is
        # doctrine refusing. Different codes, because the fixes differ.
        known = {f.finding_id for f in report.findings}
        if finding not in known:
            _fail_input(
                f"{exc}. Findings in this draft: "
                f"{', '.join(sorted(known)) or '(none)'}"
            )
        _fail_refused(str(exc), error="acceptance_refused")

    ledger.save_workflow_draft(draft)
    ledger.save_validation_report(report)
    console.print(
        f"[green]Accepted[/green] {acceptance.rule.rule_id} "
        f"([cyan]{acceptance.finding_id}[/cyan]) as residual risk."
    )
    console.print(f"Recorded by {acceptance.accepted_by}: {escape(acceptance.rationale)}")
    console.print(
        "\n[dim]This records a decision. It does not change whether the "
        "workflow may be promoted — advisory findings never blocked it.[/dim]"
    )


@workflow_app.command("promote")
def workflow_promote(
    path: str = typer.Argument(..., help="Path to a workflow draft YAML file."),
    by: str = typer.Option(..., "--by", help="Who is promoting this (self-attested)."),
    db: str = _DB_OPTION,
    exception_policy: str = typer.Option(
        "", "--exception-policy", help="What happens when no path matches."
    ),
    json_out: bool = _JSON_OPTION,
) -> None:
    """Advance a draft one step up the maturity ladder.

    Exits 2 when findings block the step and 3 when the transition itself is
    refused. Both are the runtime working; neither is a crash.
    """
    _set_json(json_out)
    draft = _load_draft_file(path)
    ledger = RunLedger(db)
    draft, lifted_note = at_recorded_maturity(draft, ledger)
    if lifted_note and not _json_mode:
        console.print(f"[dim]{escape(lifted_note)}[/dim]")
    report = validate_workflow(draft)
    # Without this the promoted artifact's accepted_risks is always empty: the
    # acceptances are in the ledger, and validation has no memory of them.
    reattach_acceptances(report, ledger)
    assessments = ledger.load_cooperation_assessments(draft.workflow_id)

    if report.unresolved_blocking:
        if _json_mode:
            _emit_json(
                {
                    "ok": False,
                    "error": "blocking_findings",
                    "workflow_id": draft.workflow_id,
                    "unresolved_blocking": [
                        _finding_row(f) for f in report.unresolved_blocking
                    ],
                }
            )
        else:
            console.print(
                f"[red]Cannot promote:[/red] "
                f"{len(report.unresolved_blocking)} unresolved blocking finding(s)."
            )
            _print_findings(report)
        raise typer.Exit(EXIT_BLOCKED)

    try:
        outcome = promote_workflow(
            ledger,
            draft,
            report,
            promoted_by=by,
            exception_policy=exception_policy,
            assessments=assessments,
        )
    except WorkflowPromotionRefused as exc:
        _fail_refused(str(exc), error="promotion_refused")

    if _json_mode:
        _emit_json(
            {
                "ok": True,
                "workflow_id": outcome.workflow_id,
                "from_maturity": outcome.from_maturity.value,
                "to_maturity": outcome.to_maturity.value,
                "promotion_id": outcome.promotion_id,
                "artifact_stored": outcome.artifact is not None,
            }
        )
        return
    console.print(
        f"[green]Promoted[/green] '{outcome.workflow_id}': "
        f"{outcome.from_maturity.value} → [bold]{outcome.to_maturity.value}[/bold]"
    )
    console.print(f"Recorded as promotion [cyan]{outcome.promotion_id}[/cyan] in {db}.")
    if outcome.to_maturity is WorkflowMaturity.ACCOUNTABLE:
        console.print(
            f"\nNext: [cyan]fukasawa workflow assess-cooperation "
            f"{outcome.workflow_id}[/cyan]"
        )


@workflow_app.command("assess-cooperation")
def workflow_assess_cooperation(
    workflow_id: str = typer.Argument(..., help="A workflow already promoted to ACCOUNTABLE."),
    db: str = _DB_OPTION,
    override: list[str] = typer.Option(
        [],
        "--override",
        help="Override one step: STEP_ID=EXECUTOR_CLASS. Repeatable. Requires --by and --why.",
    ),
    by: str = typer.Option("", "--by", help="Who is overriding (required with --override)."),
    why: str = typer.Option("", "--why", help="Why the recommendation is wrong for this step."),
    json_out: bool = _JSON_OPTION,
) -> None:
    """Recommend an executor for every step, and record any human override.

    No model is involved. The same workflow always yields the same
    recommendations, so you can predict the output before running it.

    An override is refused (exit 3) when it would move a step that hit a safety
    floor toward greater autonomy. A human may always move work toward human
    control; the reverse is doctrine, not preference.
    """
    _set_json(json_out)
    ledger = RunLedger(db)
    try:
        workflow = ledger.load_accountable_workflow(workflow_id)
    except KeyError:
        _fail_input(
            f"No accountable workflow stored for '{workflow_id}'. "
            f"Promote a draft to ACCOUNTABLE first."
        )

    systems: list[str] = []
    try:
        systems = ledger.load_workflow_draft(workflow_id).systems
    except KeyError:
        # No stored draft: report no tools rather than inventing them.
        pass

    assessments = assess_workflow(workflow, systems=systems)
    by_step = {a.step_id: a for a in assessments}

    # Re-assessing must not quietly discard a decision a person already made.
    # The recommendation is recomputed from the table every time, but a stored
    # override is carried forward unless this invocation replaces it: the
    # override is the human's judgment, and losing it while it still sits in
    # the history would mean it stopped governing without anyone being told.
    replacing = {spec.partition("=")[0] for spec in override}
    carried: list[str] = []
    for stored in ledger.load_cooperation_assessments(workflow_id):
        if stored.override is None or stored.step_id in replacing:
            continue
        if stored.step_id not in by_step:
            continue  # the step is gone from the workflow; nothing to carry.
        try:
            by_step[stored.step_id] = apply_override(
                by_step[stored.step_id],
                stored.override.overridden_to,
                actor=stored.override.actor,
                rationale=stored.override.rationale,
            )
            carried.append(stored.step_id)
        except OverrideRefusedError as exc:
            # The step's characteristics changed and the old override would now
            # cross a floor. Refusing is correct — and saying so is the point.
            _fail_refused(
                f"'{stored.step_id}' has a recorded override to "
                f"{stored.override.overridden_to.value} that is no longer "
                f"permitted: {exc} Re-run with an explicit --override for this "
                f"step to replace that decision.",
                error="stored_override_now_refused",
            )

    if override and not (by.strip() and why.strip()):
        _fail_input(
            "--override requires both --by and --why. An override without a "
            "named actor and a reason is indistinguishable from a mis-click, "
            "and this decision governs who may act unsupervised."
        )
    for spec in override:
        step_id, _, target = spec.partition("=")
        if not target:
            _fail_input(f"--override expects STEP_ID=EXECUTOR_CLASS, got '{spec}'.")
        if step_id not in by_step:
            _fail_input(
                f"'{step_id}' is not a step in '{workflow_id}'. "
                f"Steps are: {', '.join(sorted(by_step))}"
            )
        try:
            target_class = ExecutorClass(target)
        except ValueError:
            _fail_input(
                f"'{target}' is not an executor class. Valid values: "
                f"{', '.join(e.value for e in ExecutorClass)}"
            )
        try:
            by_step[step_id] = apply_override(
                by_step[step_id], target_class, actor=by, rationale=why
            )
        except OverrideRefusedError as exc:
            _fail_refused(str(exc), error="override_refused")

    ordered = [by_step[s.step_id] for s in workflow.steps]
    ledger.save_cooperation_assessments(ordered)

    rows = [
        {
            "step_id": a.step_id,
            "recommended_executor": a.recommended_executor.value,
            "effective_executor": a.effective_executor.value,
            "safety_floor": a.safety_floor.value,
            "supervision_mode": a.supervision_mode.value,
            "automation_readiness": a.automation_readiness.value,
            "overridden": a.override is not None,
            "rationale": a.rationale,
        }
        for a in ordered
    ]
    if _json_mode:
        _emit_json({"ok": True, "workflow_id": workflow_id, "assessments": rows})
        return

    table = Table(title=f"Cooperation assessment — {workflow_id}")
    for col in ("Step", "Executor", "Floor", "Supervision", "Readiness"):
        table.add_column(col)
    for a in ordered:
        executor = a.effective_executor.value
        if a.override is not None:
            executor = f"[cyan]{executor}[/cyan] (overridden)"
        table.add_row(
            a.step_id,
            executor,
            "-" if a.safety_floor is SafetyFloor.NONE else f"[yellow]{a.safety_floor.value}[/yellow]",
            a.supervision_mode.value,
            a.automation_readiness.value,
        )
    console.print(table)
    console.print(f"Saved {len(ordered)} assessment(s) to [cyan]{db}[/cyan].")
    if carried:
        console.print(
            f"[dim]Carried forward {len(carried)} existing override(s): "
            f"{', '.join(carried)}.[/dim]"
        )
    not_ready = [a.step_id for a in steps_not_ready(ordered)]
    if not_ready:
        console.print(
            f"\n[yellow]{len(not_ready)} step(s) are NOT_READY_FOR_AUTOMATION:[/yellow] "
            f"{', '.join(not_ready)}\n"
            f"That is a legitimate answer, not a failure — but promotion to "
            f"COOPERATION_READY will refuse while it stands."
        )
    console.print(
        f"\nNext: [cyan]fukasawa workflow build-cooperative {workflow_id} "
        f"--approve-by <your name>[/cyan]"
    )


@workflow_app.command("build-cooperative")
def workflow_build_cooperative(
    workflow_id: str = typer.Argument(..., help="A workflow with stored assessments."),
    db: str = _DB_OPTION,
    approve_by: str = typer.Option(
        "", "--approve-by", help="Approve the assignments as this person. Omit to build unapproved."
    ),
    json_out: bool = _JSON_OPTION,
) -> None:
    """Assign every step to an executor, from the stored assessments.

    Reads each assessment's *effective* executor, so a recorded override
    governs and the decision table's recommendation does not.

    Approval is a separate human act. Building without `--approve-by` is
    useful — you can read the assignments before signing them — but export
    refuses an unapproved workflow.
    """
    _set_json(json_out)
    ledger = RunLedger(db)
    try:
        workflow = ledger.load_accountable_workflow(workflow_id)
    except KeyError:
        _fail_input(f"No accountable workflow stored for '{workflow_id}'.")

    assessments = ledger.load_cooperation_assessments(workflow_id)
    if not assessments:
        _fail_input(
            f"No cooperation assessments stored for '{workflow_id}'. "
            f"Run: fukasawa workflow assess-cooperation {workflow_id}"
        )

    try:
        cooperative = build_cooperative_workflow(
            workflow, assessments, approved_by=approve_by
        )
    except ExportRefusedError as exc:
        _fail_refused(str(exc), error="build_refused")

    ledger.save_cooperative_workflow(cooperative)
    kept_human = steps_kept_human(cooperative)
    rows = [
        {
            "step_id": a.step_id,
            "executor_class": a.executor_class.value,
            "executor_identity": a.executor_identity,
            "human_owner": a.human_owner,
            "escalation_target": a.escalation_target,
            "approval_gate": a.approval_gate,
            "fallback_executor": a.fallback_executor.value,
        }
        for a in cooperative.assignments
    ]
    if _json_mode:
        _emit_json(
            {
                "ok": True,
                "workflow_id": workflow_id,
                "approved": cooperative.approved,
                "approved_by": cooperative.approved_by,
                "assignments": rows,
                "required_agent_packages": cooperative.required_agent_packages,
                "steps_kept_human": kept_human,
            }
        )
        return

    table = Table(title=f"Cooperative workflow — {workflow_id}")
    for col in ("Step", "Executor class", "Performed by", "Accountable human", "Escalates to"):
        table.add_column(col)
    for a in cooperative.assignments:
        table.add_row(
            a.step_id,
            a.executor_class.value,
            a.executor_identity or "[dim](unassigned)[/dim]",
            a.human_owner,
            a.escalation_target,
        )
    console.print(table)
    console.print(
        f"\nAgent packages required: "
        f"{', '.join(cooperative.required_agent_packages) or '[dim]none[/dim]'}"
    )
    _report_kept_human(kept_human)
    if cooperative.approved:
        console.print(
            f"\n[green]Approved[/green] by {cooperative.approved_by}. Next: "
            f"[cyan]fukasawa workflow export-agent-brief {workflow_id}[/cyan]"
        )
    else:
        console.print(
            "\n[yellow]Not approved.[/yellow] Export refuses an unapproved "
            "workflow — rerun with --approve-by <your name> when the "
            "assignments above are right."
        )


@workflow_app.command("export-agent-brief")
def workflow_export_agent_brief(
    workflow_id: str = typer.Argument(..., help="A workflow with an approved cooperative build."),
    db: str = _DB_OPTION,
    out: str = typer.Option("", "--out", help="Write the brief here as YAML."),
    packages: str = typer.Option(
        "", "--packages", help="Also generate agent packages into this directory."
    ),
    workspace: Optional[str] = typer.Option(
        None,
        "--workspace",
        help="Target workspace root. Numbered directories trigger C-Pax path injection.",
    ),
    paths_file: Optional[str] = typer.Option(
        None,
        "--paths-file",
        help="YAML file of workspace paths for non-C-Pax targets (context, tasks_ready, ...).",
    ),
    json_out: bool = _JSON_OPTION,
) -> None:
    """Flatten the approved workflow into a runnable WorkflowBrief.

    Each step becomes a state; each declared edge becomes a transition owned by
    that step's executor. Steps needing a human to authorize each execution are
    split in two, with a real waiting state between the agent's work and the
    person's decision.

    Exits 3 when doctrine refuses the export — an unapproved workflow, or a
    BOUNDED_AUTONOMOUS_AGENT step with no approval gate.
    """
    _set_json(json_out)
    ledger = RunLedger(db)
    try:
        workflow = ledger.load_accountable_workflow(workflow_id)
    except KeyError:
        _fail_input(f"No accountable workflow stored for '{workflow_id}'.")
    try:
        cooperative = ledger.load_cooperative_workflow(workflow_id)
    except KeyError:
        _fail_input(
            f"No cooperative workflow stored for '{workflow_id}'. "
            f"Run: fukasawa workflow build-cooperative {workflow_id} --approve-by <name>"
        )

    try:
        brief = export_workflow(cooperative, workflow)
    except ExportRefusedError as exc:
        _fail_refused(str(exc), error="export_refused")

    ledger.save_workflow(brief)
    written = ""
    if out:
        try:
            Path(out).write_text(
                yaml.safe_dump(brief.model_dump(mode="json"), sort_keys=False, width=100),
                encoding="utf-8",
            )
        except OSError as exc:
            _fail_input(f"Could not write {out}: {exc}")
        written = out

    built: list[str] = []
    if packages:
        explicit_paths = None
        if paths_file:
            try:
                explicit_paths = yaml.safe_load(
                    Path(paths_file).read_text(encoding="utf-8")
                )
            except (OSError, yaml.YAMLError) as exc:
                _fail_input(f"Could not read {paths_file}: {exc}")
        try:
            dirs, _report = generate_packages(
                brief, packages, workspace_root=workspace, explicit_paths=explicit_paths
            )
        except BuildRefusedError as exc:
            _fail_refused(str(exc), error="build_refused")
        built = [d.name for d in dirs]

    kept_human = steps_kept_human(cooperative)
    if _json_mode:
        _emit_json(
            {
                "ok": True,
                "workflow_id": brief.id,
                "states": brief.states,
                "transitions": len(brief.transitions),
                "agents": [
                    {"agent_name": a.agent_name, "depth_level": a.depth_level}
                    for a in brief.agents
                ],
                "task_depth": brief.task_depth.value,
                "status": brief.status.value,
                "written": written,
                "packages_built": built,
                "steps_kept_human": kept_human,
            }
        )
        return

    console.print(
        f"[green]Exported[/green] '{brief.id}': {len(brief.states)} states, "
        f"{len(brief.transitions)} transitions, {len(brief.agents)} agent(s)."
    )
    if brief.agents:
        table = Table(title="Declared agents")
        for col in ("Agent", "Depth level", "Escalates to"):
            table.add_column(col)
        for a in brief.agents:
            table.add_row(a.agent_name, str(a.depth_level), a.escalation_target)
        console.print(table)
    _report_kept_human(kept_human)
    console.print(f"\nBrief saved to the ledger at [cyan]{db}[/cyan].")
    if written:
        console.print(f"Brief written to [cyan]{written}[/cyan].")
    if built:
        console.print(f"Agent packages generated: {', '.join(built)}")
    console.print(
        f"\nNext: [cyan]fukasawa run[/cyan] the exported brief, or "
        f"[cyan]fukasawa workflow status {brief.id}[/cyan]"
    )


@workflow_app.command("status")
def workflow_status(
    workflow_id: str = typer.Argument(..., help="Workflow id to report on."),
    db: str = _DB_OPTION,
    json_out: bool = _JSON_OPTION,
) -> None:
    """Show where a workflow sits in the lifecycle, and what is missing.

    The one command safe to run when you have lost track. It never refuses:
    an absent stage is reported as absent, because "nothing here yet" is the
    answer to the question rather than an error.
    """
    _set_json(json_out)
    ledger = RunLedger(db)
    stages: list[dict] = []

    try:
        draft = ledger.load_workflow_draft(workflow_id)
    except KeyError:
        draft = None
    stages.append(
        {
            "stage": "draft",
            "present": draft is not None,
            "detail": f"version {draft.version}, {draft.maturity.value}" if draft else "",
        }
    )

    accountable = None
    try:
        accountable = ledger.load_accountable_workflow(workflow_id)
    except KeyError:
        pass
    stages.append(
        {
            "stage": "accountable",
            "present": accountable is not None,
            "detail": (
                f"version {accountable.version}, {accountable.maturity.value}, "
                f"{len(accountable.steps)} steps"
                if accountable
                else ""
            ),
        }
    )

    assessments = ledger.load_cooperation_assessments(workflow_id)
    not_ready = [a.step_id for a in steps_not_ready(assessments)]
    overridden = [a.step_id for a in assessments if a.override is not None]
    stages.append(
        {
            "stage": "assessed",
            "present": bool(assessments),
            "detail": (
                f"{len(assessments)} step(s); {len(overridden)} overridden; "
                f"{len(not_ready)} not ready"
                if assessments
                else ""
            ),
        }
    )

    cooperative = None
    try:
        cooperative = ledger.load_cooperative_workflow(workflow_id)
    except KeyError:
        pass
    stages.append(
        {
            "stage": "cooperative",
            "present": cooperative is not None,
            "detail": (
                (
                    f"approved by {cooperative.approved_by}"
                    if cooperative.approved
                    else "built, NOT approved"
                )
                if cooperative
                else ""
            ),
        }
    )

    exported = None
    try:
        exported = ledger.load_workflow(workflow_id)
    except Exception:
        pass
    stages.append(
        {
            "stage": "exported",
            "present": exported is not None,
            "detail": (
                f"{len(exported.states)} states, {len(exported.agents)} agent(s), "
                f"status {exported.status.value}"
                if exported
                else ""
            ),
        }
    )

    runs = ledger.list_runs(workflow_id) if exported is not None else []
    stages.append(
        {
            "stage": "runs",
            "present": bool(runs),
            "detail": f"{len(runs)} run(s)" if runs else "",
        }
    )

    if _json_mode:
        _emit_json(
            {
                "ok": True,
                "workflow_id": workflow_id,
                "stages": stages,
                "steps_not_ready": not_ready,
                "steps_overridden": overridden,
            }
        )
        return

    table = Table(title=f"Lifecycle — {workflow_id}")
    for col in ("Stage", "Present", "Detail"):
        table.add_column(col)
    for s in stages:
        table.add_row(
            s["stage"],
            "[green]yes[/green]" if s["present"] else "[dim]no[/dim]",
            s["detail"] or "[dim]—[/dim]",
        )
    console.print(table)
    if not any(s["present"] for s in stages):
        console.print(
            f"\nNothing stored for '{workflow_id}'. Start with: "
            f"[cyan]fukasawa workflow init {workflow_id}[/cyan]"
        )
    if not_ready:
        console.print(f"\n[yellow]Not ready for automation:[/yellow] {', '.join(not_ready)}")


if __name__ == "__main__":
    app()
