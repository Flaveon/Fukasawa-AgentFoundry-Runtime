# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Agent package generator — Agent Foundry consuming a validated brief.

Reads an APPROVED workflow brief and produces one bounded agent package
directory per declared agent. The generator enforces doctrine at build time:

* Only approved briefs build. A draft brief is an opinion, not a contract.
* Level 5 agents never build — Level 5 is redesign-only doctrine work,
  not executable capability.
* C-Pax workspaces (numbered directories) get the path profile injected and
  must have a doctrine.md for SOUL inheritance; other workspaces must supply
  explicit paths, because an agent with undefined paths is incomplete.
* Every package is born at maturity 'draft'. The generator cannot claim
  testing that has not happened; promotion needs human review and evidence.

The output of a build is the package directories plus a build report with a
human review checklist — the review gate before anything is promoted.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src.schemas.agent_package import (
    AgentCapsuleContract,
    AgentPackageManifest,
    CapsuleInput,
    CapsuleOutputSchema,
    CapsuleStep,
    EscalationRule,
    KnownFailure,
    Maturity,
)
from src.schemas.agent_spec import AgentSpec
from src.schemas.workflow_brief import BriefStatus, TaskDepth, WorkflowBrief

#: The seven C-Pax workspace paths from the Agent Foundry directory profile.
C_PAX_PATHS: dict[str, str] = {
    "context": "02_context/",
    "tasks_ready": "05_tasks/ready/",
    "tasks_blocked": "05_tasks/blocked/",
    "outputs": "11_outputs/",
    "logs": "12_logs/",
    "agent_config": "07_agents/{agent_name}/",
    "archive": "13_archive/",
}

#: Directory names whose presence marks a workspace as C-Pax numbered layout.
_C_PAX_MARKERS = ("05_tasks", "11_outputs", "12_logs", "07_agents")

#: Files every generated package must contain (relative to the package root).
PACKAGE_FILES = [
    "SKILL.md",
    "SOUL.md",
    "CONTRACT.md",
    "process_capsule.yaml",
    "evals.yaml",
    "simulations.yaml",
    "learning_log.md",
    "permissions.json",
    "README.md",
    "manifest.json",
]


class BuildRefusedError(Exception):
    """Raised when doctrine forbids the requested build. The message says why."""


def detect_workspace_profile(workspace_root: Path | None) -> str:
    """Return 'c-pax' if the workspace uses the numbered directory layout, else 'generic'.

    Detection is deliberately simple: any two of the marker directories
    present means the layout is C-Pax. One alone could be coincidence.
    """
    if workspace_root is None:
        return "generic"
    hits = sum(1 for marker in _C_PAX_MARKERS if (workspace_root / marker).is_dir())
    return "c-pax" if hits >= 2 else "generic"


def _paths_for(profile: str, agent: AgentSpec, explicit_paths: dict | None) -> dict:
    """Resolve the workspace paths an agent may touch.

    C-Pax profile injects the doctrine paths automatically. A generic
    workspace must supply paths explicitly — the doctrine is blunt about
    this: agents with undefined paths are incomplete.
    """
    if profile == "c-pax":
        return {
            key: value.format(agent_name=agent.agent_name)
            for key, value in C_PAX_PATHS.items()
        }
    if explicit_paths:
        return dict(explicit_paths)
    raise BuildRefusedError(
        f"workspace is not C-Pax and no explicit paths were provided for "
        f"agent '{agent.agent_name}'. Define workspace paths (context, "
        f"tasks_ready, tasks_blocked, outputs, logs, agent_config, archive) "
        f"before building — agents with undefined paths are incomplete."
    )


def _build_capsule(brief: WorkflowBrief, agent: AgentSpec) -> AgentCapsuleContract:
    """Derive the agent's transfer contract from the transitions it owns."""
    owned = [t for t in brief.transitions if t.owner == agent.agent_name]
    if not owned:
        raise BuildRefusedError(
            f"agent '{agent.agent_name}' is declared in the brief but owns no "
            f"transitions — there is nothing to package. Remove the agent or "
            f"assign it a transition."
        )

    steps = []
    for t in owned:
        depth = brief.depth_of(t)
        deterministic = depth is TaskDepth.ROUTINE
        steps.append(
            CapsuleStep(
                name=(
                    f"advance {t.from_state} -> {t.to_state}"
                    + (f", producing: {t.evidence_required}" if t.evidence_required else "")
                ),
                # ROUTINE transitions are rule work; anything needing judgment
                # runs at the agent's declared level, never above it.
                depth_level=0 if deterministic else agent.depth_level,
                deterministic=deterministic,
                reasoning_justification=(
                    ""
                    if deterministic
                    else (
                        f"{depth.value} transition: needs a consistent frame, "
                        f"not a rigid rule; output is confirmed downstream."
                    )
                ),
            )
        )

    inputs = [
        CapsuleInput(
            name=f"work in state {t.from_state}",
            type="process_capsule",
            required=True,
            source=f"workflow {brief.id}",
        )
        for t in owned
    ]

    return AgentCapsuleContract(
        task_name=f"{brief.id}: {agent.responsibilities}",
        owner_agent=agent.agent_name,
        workflow_id=brief.id,
        maturity=Maturity.DRAFT,
        depth_level=agent.depth_level,
        inputs=inputs,
        steps=steps,
        known_failures=[
            KnownFailure(
                failure="required evidence missing at transition",
                signal="runtime refuses the move with NonConformanceError",
                response="gather the evidence and retry; do not improvise a path",
            ),
            KnownFailure(
                failure="no valid transition for the intended move",
                signal="capsule frozen in NON_CONFORMANCE",
                response=brief.exception_path.strip(),
            ),
        ],
        escalation_rules=[
            EscalationRule(
                condition="input is ambiguous, out of scope, or above declared depth",
                target=agent.escalation_target,
                requested_checks="confirm intended transition and required evidence",
            )
        ],
        output_schema=CapsuleOutputSchema(
            status="done | blocked | escalated",
            evidence=(
                "; ".join(t.evidence_required for t in owned if t.evidence_required)
                or "statement of what was produced"
            ),
            confidence="low | medium | high, with reason",
            recommended_next_step="the next workflow state, or the escalation target",
        ),
    )


# ------------------------------------------------------------- file templates


def _skill_md(brief: WorkflowBrief, agent: AgentSpec, profile: str, paths: dict) -> str:
    """Render SKILL.md: role, responsibilities, workflow position, guidance."""
    owned = [t for t in brief.transitions if t.owner == agent.agent_name]
    lines = [
        "---",
        f"agent: {agent.agent_name}",
        f"maturity: {Maturity.DRAFT.value}",
        f"depth_level: {agent.depth_level}",
        f"workspace_profile: {profile}",
        "---",
        "",
        f"# SKILL — {agent.agent_name}",
        "",
        "## Role",
        "",
        agent.responsibilities.strip(),
        "",
        f"This agent operates at Fukasawa depth level {agent.depth_level} and must",
        "not reach above it. It does not redesign the workflow, does not own",
        "CONSCIOUS decisions, and does not perform tasks assigned to other owners.",
        "",
        "## Workflow Position",
        "",
        f"Workflow: {brief.title} (`{brief.id}`)",
        "",
    ]
    for t in owned:
        lines.append(
            f"- owns transition `{t.from_state}` -> `{t.to_state}`"
            + (f" (evidence: {t.evidence_required})" if t.evidence_required else "")
        )
    lines += [
        "",
        "## Operational Guidance",
        "",
        "- Every transition needs its declared evidence before it is attempted.",
        "- When no valid transition matches, stop: " + brief.exception_path.strip(),
        f"- Escalate anything ambiguous to: {agent.escalation_target}",
        "",
        "## Workspace",
        "",
        "```yaml",
        f"workspace_profile: {profile}",
        "paths:",
    ]
    lines += [f"  {key}: {value}" for key, value in paths.items()]
    lines += ["```", ""]
    return "\n".join(lines)


def _soul_md(brief: WorkflowBrief, agent: AgentSpec, profile: str) -> str:
    """Render SOUL.md: behavioral identity, inheriting doctrine on C-Pax."""
    lines = []
    if profile == "c-pax":
        lines += [
            "```yaml",
            "inherits: ../../doctrine.md",
            "```",
            "",
            f"# SOUL — {agent.agent_name}",
            "",
            "Base behavioral identity comes from the inherited project doctrine.",
            "This file defines only what is genuinely unique to this agent.",
        ]
    else:
        lines += [
            f"# SOUL — {agent.agent_name}",
            "",
            "No project doctrine is inherited (generic workspace).",
        ]
    lines += [
        "",
        "## Identity",
        "",
        f"A depth-{agent.depth_level} worker inside '{brief.title}'. Direct and",
        "builder-minded: states what it did, what evidence it produced, and what",
        "it could not verify. No hype, no filler, no unsupported claims.",
        "",
        "## Communication Principles",
        "",
        "- Separate observation from inference; state confidence explicitly.",
        "- Name missing evidence instead of talking around it.",
        "- A blocked handoff names its blocker and the next action.",
        "",
    ]
    return "\n".join(lines)


def _contract_md(brief: WorkflowBrief, agent: AgentSpec, paths: dict) -> str:
    """Render CONTRACT.md: boundaries, permissions, escalation, failure handling."""
    lines = [
        f"# CONTRACT — {agent.agent_name}",
        "",
        "## Boundaries",
        "",
        f"- Operates only within workflow `{brief.id}` on its owned transitions.",
        f"- Maximum reasoning depth: level {agent.depth_level}. Reaching above is a scope violation.",
        "- CONSCIOUS decisions belong to humans. This agent never approves its own work.",
        "- May not modify the workflow brief, the ledger, or any agent package (including its own).",
        "",
        "## Permissions",
        "",
        "May read and write only these paths (see permissions.json):",
        "",
    ]
    lines += [f"- `{value}` ({key})" for key, value in paths.items()]
    if agent.allowed_tools:
        lines += ["", "Allowed tools:", ""]
        lines += [f"- {tool}" for tool in agent.allowed_tools]
    lines += [
        "",
        "## Forbidden",
        "",
    ]
    forbidden = agent.forbidden or [
        "acting without required evidence",
        "inventing transitions not declared in the brief",
        "claiming completion without verification",
    ]
    lines += [f"- {item}" for item in forbidden]
    lines += [
        "",
        "## Escalation",
        "",
        f"- Escalation target: **{agent.escalation_target}**",
        f"- Escalation channel: write the blocked item to `{paths.get('tasks_blocked', '(declared blocked path)')}`",
        "- Escalate on: ambiguity, missing inputs, out-of-scope requests, repeated failure.",
        "",
        "## Failure Handling",
        "",
        "- A refused transition is retried only after its evidence exists.",
        "- A frozen (NON_CONFORMANCE) capsule is never worked around: "
        + brief.exception_path.strip(),
        "- Every failure lands in learning_log.md in the Non-Conformance",
        "  Improvement Opportunity format.",
        "",
    ]
    return "\n".join(lines)


def _evals_yaml(brief: WorkflowBrief, agent: AgentSpec, paths: dict) -> str:
    """Render evals.yaml with the three mandatory C-Pax checks, results pending."""
    data = {
        "eval_name": f"{agent.agent_name}-baseline",
        "agent": agent.agent_name,
        "depth_level": agent.depth_level,
        "checks": {
            "output_schema_conformance": {
                "expected_schema": "process_capsule.yaml#output_schema",
                "result": "pending",
                "evidence": "",
            },
            "escalation_correctness": {
                "triggered": None,
                "escalated_to_blocked": None,
                "blocked_path": paths.get("tasks_blocked", ""),
                "result": "pending",
                "evidence": "",
            },
            "scope_compliance": {
                "declared_depth_level": agent.depth_level,
                "reasoning_observed": "",
                "result": "pending",
                "evidence": "",
            },
        },
        "overall": "pending",
        "notes": (
            "The three checks above are mandatory and must not be replaced. "
            "Additional checks may be appended."
        ),
    }
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def _simulations_yaml(brief: WorkflowBrief, agent: AgentSpec) -> str:
    """Render simulations.yaml: one dry-run per owned transition.

    Every simulation must produce an Observation Packet — an undefined
    output format makes a simulation incomplete by doctrine.
    """
    owned = [t for t in brief.transitions if t.owner == agent.agent_name]
    sims = []
    for t in owned:
        sims.append(
            {
                "simulation_name": f"dry-run-{t.from_state.lower()}-to-{t.to_state.lower()}",
                "agent": agent.agent_name,
                "scenario": (
                    f"work sits in {t.from_state}; agent must reach {t.to_state}"
                    + (
                        f" with evidence: {t.evidence_required}"
                        if t.evidence_required
                        else ""
                    )
                ),
                "depth_level": agent.depth_level,
                "run": {
                    "observation": ["(what was directly seen or simulated)"],
                    "inference": ["(what the agent concluded)"],
                    "confidence": {"level": "pending", "reason": ""},
                    "missing_evidence": ["(what was not available)"],
                    "escalation": {
                        "next_layer": agent.escalation_target,
                        "requested_checks": "",
                    },
                },
                "result": "pending",
                "notes": "",
            }
        )
    return yaml.safe_dump(sims, sort_keys=False, allow_unicode=True)


def _learning_log_md(agent: AgentSpec) -> str:
    """Render learning_log.md with the NC Improvement Opportunity template."""
    today = datetime.now(timezone.utc).date().isoformat()
    return "\n".join(
        [
            f"# Learning Log — {agent.agent_name}",
            "",
            "All failures, corrections, discoveries, and near-misses belong here,",
            "in the Non-Conformance Improvement Opportunity format below. Promotion",
            "history is also recorded here.",
            "",
            "## Entry Template",
            "",
            "```markdown",
            "## [Date] — [Event Type: failure | correction | discovery | near-miss]",
            "",
            "**What happened:**",
            "",
            "**Root cause hypothesis:**",
            "",
            "**Complexity signal?**",
            "(too many handoffs / too much context required / unclear ownership /",
            "undefined output / scope exceeded / etc.)",
            "",
            "**Corrective action taken:**",
            "",
            "**Preventive improvement:**",
            "- [ ] Remove a step",
            "- [ ] Clarify ownership",
            "- [ ] Improve input contract",
            "- [ ] Improve output schema",
            "- [ ] Convert a decision to a rule",
            "- [ ] Move to lower reasoning layer",
            "- [ ] Other:",
            "",
            "**Status:** open | resolved | escalated",
            "```",
            "",
            f"## {today} — discovery",
            "",
            "**What happened:** Package generated at maturity `draft` by the",
            "Fukasawa-AgentFoundry runtime. No runs, evals, or simulations have",
            "been executed yet.",
            "",
            "**Status:** open — promotion to `tested` requires passing evals and",
            "human review.",
            "",
        ]
    )


def _permissions_json(agent: AgentSpec, paths: dict) -> str:
    """Render permissions.json: paths, tools, and hard denials."""
    return json.dumps(
        {
            "agent": agent.agent_name,
            "paths": paths,
            "allowed_tools": agent.allowed_tools,
            "forbidden": agent.forbidden,
            "network_access": False,
            "note": (
                "Paths are relative to the sub-project root. Reading or writing "
                "outside these paths requires an explicit CONTRACT.md amendment."
            ),
        },
        indent=2,
    )


def _readme_md(
    brief: WorkflowBrief, agent: AgentSpec, profile: str
) -> str:
    """Render README.md — everything a human or agent needs, no hidden context."""
    return "\n".join(
        [
            f"# Agent Package — {agent.agent_name}",
            "",
            f"Generated from approved workflow brief `{brief.id}` "
            f"({brief.title}) by the Fukasawa-AgentFoundry runtime.",
            "",
            "This package is self-contained: every behavior, boundary, and",
            "expectation is declared in the files below. If something is not",
            "written here, the agent does not do it.",
            "",
            "| File | Purpose |",
            "|---|---|",
            "| SKILL.md | Role, responsibilities, workflow position, depth level |",
            "| SOUL.md | Behavioral identity and communication principles |",
            "| CONTRACT.md | Boundaries, permissions, escalation, failure handling |",
            "| process_capsule.yaml | Transfer contract — inputs, steps, output schema |",
            "| evals.yaml | The three mandatory checks (schema, escalation, scope) |",
            "| simulations.yaml | Dry-run scenarios producing Observation Packets |",
            "| learning_log.md | Failures and improvements, NC Opportunity format |",
            "| permissions.json | Machine-readable path and tool grants |",
            "| manifest.json | Package metadata for `fukasawa package validate` |",
            "",
            "## Status",
            "",
            f"- maturity: **draft** — promotion to `tested` requires passing",
            "  evals and human review; `candidate_skill.md` is created on the",
            "  first proposed improvement.",
            f"- depth level: **{agent.depth_level}**",
            f"- deployment method: **{agent.deployment_method.value}**",
            f"- workspace profile: **{profile}**",
            f"- escalation target: **{agent.escalation_target}**",
            "",
            "## Deployment",
            "",
            "Definition layer is this file package. Inject SKILL.md + SOUL.md +",
            "CONTRACT.md as the system prompt; process_capsule.yaml declares the",
            "I/O contract. Upgrade path per doctrine: manual run (draft) ->",
            "CLI wrapper (tested) -> cron/file-watcher (validated) -> orchestrated.",
            "",
            "## Validation",
            "",
            "```bash",
            f"fukasawa package validate <path-to>/{agent.agent_name}",
            "```",
            "",
        ]
    )


# ------------------------------------------------------------------ generator


def generate_packages(
    brief: WorkflowBrief,
    out_dir: str | Path,
    workspace_root: str | Path | None = None,
    explicit_paths: dict | None = None,
) -> tuple[list[Path], Path]:
    """Generate one agent package per declared agent from an approved brief.

    Returns (package directories, build report path). Raises
    BuildRefusedError when doctrine forbids the build — the message always
    says exactly what to fix.
    """
    if brief.status is not BriefStatus.APPROVED:
        raise BuildRefusedError(
            f"brief '{brief.id}' has status '{brief.status.value}' — only an "
            f"approved brief can generate agent packages. Review the brief and "
            f"set status: approved."
        )
    if not brief.agents:
        raise BuildRefusedError(
            f"brief '{brief.id}' declares no agents — add an agents section "
            f"naming each agent, its depth_level, and its escalation_target."
        )
    for agent in brief.agents:
        if agent.depth_level == 5:
            raise BuildRefusedError(
                f"agent '{agent.agent_name}' is declared Level 5. Level 5 is "
                f"redesign-only strategy work and is never built as an "
                f"executable agent. Decompose the work or lower the level."
            )

    workspace = Path(workspace_root) if workspace_root else None
    profile = detect_workspace_profile(workspace)
    if profile == "c-pax":
        # SOUL.md inherits ../../doctrine.md; generating without it would
        # produce agents whose base identity points at nothing.
        assert workspace is not None
        if not (workspace / "doctrine.md").exists():
            raise BuildRefusedError(
                f"workspace '{workspace}' uses the C-Pax layout but has no "
                f"doctrine.md at its root. Define the project doctrine before "
                f"agent SOUL files can inherit it."
            )

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    package_dirs: list[Path] = []

    for agent in brief.agents:
        paths = _paths_for(profile, agent, explicit_paths)
        capsule = _build_capsule(brief, agent)
        pkg = out / agent.agent_name
        pkg.mkdir(parents=True, exist_ok=True)

        manifest = AgentPackageManifest(
            agent_name=agent.agent_name,
            workflow_id=brief.id,
            depth_level=agent.depth_level,
            maturity=Maturity.DRAFT,
            owner=brief.owner,
            escalation_target=agent.escalation_target,
            deployment_method=agent.deployment_method,
            workspace_profile=profile,
            files=PACKAGE_FILES,
        )

        (pkg / "SKILL.md").write_text(
            _skill_md(brief, agent, profile, paths), encoding="utf-8"
        )
        (pkg / "SOUL.md").write_text(_soul_md(brief, agent, profile), encoding="utf-8")
        (pkg / "CONTRACT.md").write_text(
            _contract_md(brief, agent, paths), encoding="utf-8"
        )
        (pkg / "process_capsule.yaml").write_text(
            yaml.safe_dump(capsule.model_dump(mode="json"), sort_keys=False),
            encoding="utf-8",
        )
        (pkg / "evals.yaml").write_text(
            _evals_yaml(brief, agent, paths), encoding="utf-8"
        )
        (pkg / "simulations.yaml").write_text(
            _simulations_yaml(brief, agent), encoding="utf-8"
        )
        (pkg / "learning_log.md").write_text(_learning_log_md(agent), encoding="utf-8")
        (pkg / "permissions.json").write_text(
            _permissions_json(agent, paths), encoding="utf-8"
        )
        (pkg / "README.md").write_text(
            _readme_md(brief, agent, profile), encoding="utf-8"
        )
        (pkg / "manifest.json").write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8"
        )
        package_dirs.append(pkg)

    report_path = _write_build_report(brief, package_dirs, profile, out)
    return package_dirs, report_path


def _write_build_report(
    brief: WorkflowBrief, package_dirs: list[Path], profile: str, out: Path
) -> Path:
    """Emit the build report and human review checklist for this generation."""
    lines = [
        f"# Build Report — {brief.title}",
        "",
        f"- brief: `{brief.id}` (status: {brief.status.value})",
        f"- generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"- workspace profile: {profile}",
        f"- packages: {len(package_dirs)}",
        "",
        "## Packages",
        "",
    ]
    for pkg, agent in zip(package_dirs, brief.agents):
        lines.append(
            f"- `{pkg}` — depth {agent.depth_level}, "
            f"deploys as {agent.deployment_method.value}, "
            f"escalates to {agent.escalation_target}, maturity draft"
        )
        if agent.depth_level == 4:
            # The Complexity Gate's standing question for coordinators.
            lines.append(
                "  - REVIEW: Level 4 coordinator — can this be decomposed "
                "into lower-level shards before building the coordinator?"
            )
    lines += [
        "",
        "## Review Checklist (human, before any promotion)",
        "",
        "- [ ] SKILL.md responsibilities match what the workflow actually needs",
        "- [ ] Depth levels are the lowest that work — not the most impressive",
        "- [ ] Escalation targets are correct and reachable",
        "- [ ] CONTRACT.md forbidden list covers the failure modes you fear",
        "- [ ] permissions.json paths are the only paths each agent touches",
        "- [ ] evals.yaml three mandatory checks are intact",
        "- [ ] No agent owns a CONSCIOUS decision",
        "",
        "Promotion from draft to tested requires passing evals AND this",
        "checklist signed off by a human. The generator cannot promote.",
        "",
    ]
    report = out / "build_report.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    return report
