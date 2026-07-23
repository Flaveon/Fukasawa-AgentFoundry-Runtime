# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Handoff file emitter.

A handoff file is what the next session — human or agent — reads to pick up
a run without any chat history. Phase 1 exit criteria require every handoff
to include artifact paths, the next action, and review gate status; this
module is the single place that guarantees those sections exist.

Handoffs are Markdown on purpose: the audience includes humans who are not
developers, and the file must be readable in any editor with no tooling.
"""

from pathlib import Path

from src.schemas.process_capsule import ProcessCapsule
from src.schemas.runtime_state import RunStatus, RuntimeState
from src.schemas.workflow_brief import WorkflowBrief

#: Default directory for emitted run handoffs, relative to the working directory.
DEFAULT_HANDOFF_DIR = "run_handoffs"


def _artifact_lines(run: RuntimeState) -> list[str]:
    """Render the artifact paths section. Always present, even when empty."""
    lines = ["## Artifact Paths", ""]
    if not run.inputs and not run.outputs:
        lines.append("- (none recorded)")
    for art in run.inputs:
        required = " (required)" if art.required else ""
        lines.append(f"- input: `{art.path}` — {art.kind or 'unspecified'}{required}")
    for art in run.outputs:
        by = f", produced by {art.produced_by}" if art.produced_by else ""
        lines.append(f"- output: `{art.path}` — {art.kind or 'unspecified'}{by}")
    return lines


def _next_action_line(run: RuntimeState) -> str:
    """Derive the single next action for the reader of this handoff."""
    if run.next_action.strip():
        return run.next_action.strip()
    if run.status is RunStatus.COMPLETE:
        return "None — run is complete."
    if run.status is RunStatus.FAILED:
        return "Investigate the non-conformance record, then correct the brief or the work."
    if run.status is RunStatus.HUMAN_REVIEW:
        return f"Review and decide at the gate: fukasawa review {run.capsule_id}"
    return f"Resume the run: fukasawa resume {run.run_id}"


def write_handoff(
    run: RuntimeState,
    brief: WorkflowBrief,
    capsule: ProcessCapsule,
    directory: str | Path = DEFAULT_HANDOFF_DIR,
) -> Path:
    """Write the handoff file for a run and return its path.

    Called whenever a run pauses, blocks, completes, or fails — any moment
    the work might change hands. Overwrites the previous handoff for the
    same run: the ledger holds history, the handoff holds *now*.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{run.run_id}.md"

    gate = run.human_gate
    gate_line = gate.status.value
    if gate.reviewer:
        gate_line += f" (reviewer: {gate.reviewer})"
    if gate.reviewed_at:
        gate_line += f" at {gate.reviewed_at.isoformat(timespec='seconds')}"
    if gate.reason:
        gate_line += f" — reason: {gate.reason}"

    lines = [
        f"# Run Handoff — {run.run_id}",
        "",
        f"- **Workflow**: {brief.title} (`{run.workflow_id}`)",
        f"- **Capsule**: `{run.capsule_id}` assigned to {capsule.assigned_to}",
        f"- **Operator**: {run.operator}",
        f"- **Run status**: {run.status.value}",
        f"- **Current state**: {run.current_state}",
        f"- **Updated**: {run.updated_at.isoformat(timespec='seconds')}",
        f"- **Trace**: `{run.trace_path}` (fukasawa history {run.workflow_id})",
        "",
        "## Next Action",
        "",
        _next_action_line(run),
        "",
    ]
    if run.blocked_reason:
        lines += ["## Blocked Reason", "", run.blocked_reason, ""]
    lines += _artifact_lines(run)
    lines += [
        "",
        "## Review Gate Status",
        "",
        gate_line,
        "",
        "## Completion Criteria",
        "",
        brief.completion_criteria.strip(),
        "",
    ]
    if run.completed_checks:
        lines += ["## Completed Checks", ""]
        for check in run.completed_checks:
            lines.append(
                f"- [{check.result.value}] {check.check}"
                + (f" — evidence: {check.evidence}" if check.evidence else "")
            )
        lines.append("")
    if capsule.non_conformance_note:
        lines += ["## Non-Conformance", "", capsule.non_conformance_note, ""]

    path.write_text("\n".join(lines), encoding="utf-8")
    return path
