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

All state lives in a local SQLite file (default: ./fukasawa.db). Run handoff
files are written to ./run_handoffs/. No network calls happen anywhere in
this program.
"""

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

from src.foundry.generator import BuildRefusedError, generate_packages
from src.foundry.validator import validate_package
from src.governance.evals import load_eval_case, run_eval_case
from src.governance.maturity import PromotionRefusedError, assess, promote
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
app.add_typer(nonconformance_app, name="nonconformance")
app.add_typer(validate_app, name="validate")
app.add_typer(runs_app, name="runs")
app.add_typer(package_app, name="package")
app.add_typer(eval_app, name="eval")
app.add_typer(maturity_app, name="maturity")
app.add_typer(graph_app, name="graph")
app.add_typer(trust_app, name="trust")
app.add_typer(model_app, name="model")

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
    file = Path(path)
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


# ----------------------------------------------------------------------- model


@model_app.command("list")
def model_list() -> None:
    """List configured model endpoints (defaults + config file)."""
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
        "[cyan]endpoint: pink[/cyan]"
    )


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


if __name__ == "__main__":
    app()
