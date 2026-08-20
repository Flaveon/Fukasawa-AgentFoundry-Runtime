# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Brief services — validating a workflow brief and building its packages.

The desktop's two original tasks. Unchanged by the workflow-lifecycle work;
moved into the services package when it grew past one file (ADR-007's
consequence note), which is why this reads as a self-contained pair.

This module is deliberately Tk-free. It wraps the existing runtime
(validator, generator) into plain, structured results the view can render,
and — just as importantly — that a test can assert on without a display.

Keeping the logic here honors the Phase 5 exit criterion: the core runtime
stays fully usable without the UI. The CustomTkinter layer in app.py is only
a view over these functions; every decision and error message lives here.
"""

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

from src.foundry.generator import BuildRefusedError, generate_packages
from src.foundry.validator import validate_package
from src.schemas.workflow_brief import BriefStatus, TaskDepth, WorkflowBrief


@dataclass
class BriefValidation:
    """The outcome of validating a brief file, ready for display."""

    ok: bool
    #: Human-readable summary line (valid case) or the top-level error.
    summary: str
    #: One "field: problem" string per validation error (invalid case).
    problems: list[str] = field(default_factory=list)
    #: Populated on success — the facts a reviewer wants at a glance.
    title: str = ""
    brief_id: str = ""
    owner: str = ""
    status: str = ""
    state_count: int = 0
    transition_count: int = 0
    agent_count: int = 0
    review_gates: int = 0
    approved: bool = False


def validate_brief_file(path: str | Path) -> BriefValidation:
    """Validate a workflow brief file and return a display-ready result.

    Never raises for the expected failure modes (missing file, bad YAML,
    schema violations) — the GUI shows them as findings, not crashes.
    """
    file = Path(path)
    if not file.is_file():
        return BriefValidation(ok=False, summary=f"No such file: {path}")
    try:
        raw = yaml.safe_load(file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return BriefValidation(ok=False, summary=f"Not valid YAML: {exc}")
    try:
        brief = WorkflowBrief.model_validate(raw)
    except ValidationError as exc:
        problems = [
            f"{'.'.join(str(p) for p in e['loc']) or '(root)'}: {e['msg']}"
            for e in exc.errors()
        ]
        return BriefValidation(
            ok=False,
            summary=f"{len(problems)} problem(s) found",
            problems=problems,
        )
    gates = sum(1 for t in brief.transitions if brief.depth_of(t) is TaskDepth.CONSCIOUS)
    return BriefValidation(
        ok=True,
        summary=f"{brief.title} is valid",
        title=brief.title,
        brief_id=brief.id,
        owner=brief.owner,
        status=brief.status.value,
        state_count=len(brief.states),
        transition_count=len(brief.transitions),
        agent_count=len(brief.agents),
        review_gates=gates,
        approved=brief.status is BriefStatus.APPROVED,
    )


@dataclass
class PackageResult:
    """One generated package and whether it passed validation."""

    name: str
    path: str
    findings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when the package validated with no findings."""
        return not self.findings


@dataclass
class BuildOutcome:
    """The outcome of building a workflow's agent packages."""

    ok: bool
    summary: str
    packages: list[PackageResult] = field(default_factory=list)
    report_path: str = ""
    #: Set when the build was refused by doctrine (draft brief, no agents, ...).
    refusal: str = ""


def build_workflow(
    brief_path: str | Path,
    out_dir: str | Path,
    workspace_root: str | Path | None = None,
) -> BuildOutcome:
    """Validate a brief, then generate and self-validate its agent packages.

    Returns a structured outcome the GUI can render as a checklist. Build
    refusals (unapproved brief, missing doctrine, Level 5 agent) come back as
    a stated ``refusal``, not an exception — the same doctrine gates as the
    CLI, surfaced for a non-developer.
    """
    validation = validate_brief_file(brief_path)
    if not validation.ok:
        return BuildOutcome(
            ok=False,
            summary="Brief must be valid before a workflow can be built.",
            refusal=validation.summary
            + ("; " + "; ".join(validation.problems) if validation.problems else ""),
        )
    brief = WorkflowBrief.model_validate(
        yaml.safe_load(Path(brief_path).read_text(encoding="utf-8"))
    )
    try:
        package_dirs, report = generate_packages(
            brief, out_dir, workspace_root=workspace_root
        )
    except BuildRefusedError as exc:
        return BuildOutcome(
            ok=False,
            summary="Build refused by doctrine.",
            refusal=str(exc),
        )
    packages = [
        PackageResult(name=p.name, path=str(p), findings=validate_package(p))
        for p in package_dirs
    ]
    all_ok = all(p.ok for p in packages)
    return BuildOutcome(
        ok=all_ok,
        summary=(
            f"Built {len(packages)} package(s), all valid."
            if all_ok
            else f"Built {len(packages)} package(s), some failed validation."
        ),
        packages=packages,
        report_path=str(report),
    )
