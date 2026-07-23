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
app.add_typer(nonconformance_app, name="nonconformance")
app.add_typer(validate_app, name="validate")
app.add_typer(runs_app, name="runs")
app.add_typer(package_app, name="package")

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
            capsule = _attempt_transition(
                runtime, brief, capsule, transition, evidence, run
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


# ------------------------------------------------------------ nonconformance


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
