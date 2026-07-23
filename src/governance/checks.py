# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""The five default governance checks (docs/evaluation-strategy.md).

Each check is a pure function: it inspects artifacts (handoff text, ledger
rows, package files) and returns an EvalCheckResult with evidence. Checks
never mutate anything — they answer questions; the eval runner records the
answers and the maturity engine acts on them.

Every failure message names what was missing, because a failed check whose
reason must be reconstructed is itself an incomplete handoff.
"""

import json
from pathlib import Path

import yaml

from src.runtime.ledger import RunLedger
from src.schemas.eval_case import (
    CheckCategory,
    CheckOutcome,
    EvalCase,
    EvalCheckResult,
)
from src.schemas.non_conformance import ResolutionStatus


def _result(
    category: CheckCategory, passed: bool, evidence: str
) -> EvalCheckResult:
    """Build a pass/fail result with its evidence."""
    return EvalCheckResult(
        category=category,
        outcome=CheckOutcome.PASS if passed else CheckOutcome.FAIL,
        evidence=evidence,
    )


def check_handoff_completeness(handoff_text: str) -> EvalCheckResult:
    """Can someone continue this work from the handoff file alone?

    Pass conditions: objective present, artifact paths present, current
    state present, next action executable, blocker status explicit,
    verification evidence linked or summarized.
    """
    problems = []
    if "## Completion Criteria" not in handoff_text:
        problems.append("objective (Completion Criteria section) missing")
    if "## Artifact Paths" not in handoff_text:
        problems.append("Artifact Paths section missing")
    elif "(none recorded)" in handoff_text.split("## Artifact Paths")[1].split("##")[0]:
        problems.append("no artifact paths recorded")
    if "**Current state**" not in handoff_text:
        problems.append("current state missing")
    if "## Next Action" not in handoff_text:
        problems.append("Next Action section missing")
    else:
        next_action = (
            handoff_text.split("## Next Action")[1].split("##")[0].strip()
        )
        if not next_action:
            problems.append("next action is empty")
    if "**Run status**" not in handoff_text:
        problems.append("run/blocker status not explicit")
    has_evidence = (
        "## Completed Checks" in handoff_text
        or "evidence:" in handoff_text.lower()
    )
    if not has_evidence:
        problems.append("no verification evidence linked or summarized")
    return _result(
        CheckCategory.HANDOFF_COMPLETENESS,
        not problems,
        "; ".join(problems) if problems else
        "handoff carries objective, artifacts, state, next action, status, and evidence",
    )


def check_observation_discipline(
    ledger: RunLedger, run_id: str, forbidden_claims: list[str], handoff_text: str
) -> EvalCheckResult:
    """Are observations separated from inferences, with stated confidence —
    and are unsupported claims absent from everything the run produced?"""
    packets = ledger.observations_for(run_id)
    problems = []
    if not packets:
        problems.append(f"no observation packets recorded for run {run_id}")
    # Schema already forces confidence and missing_evidence per packet; the
    # check's job is the claims scan across all produced text.
    searchable = handoff_text.lower() + "".join(
        (p.observation + " " + p.inference).lower() for p in packets
    )
    for claim in forbidden_claims:
        if claim.lower() in searchable:
            problems.append(f"unsupported claim present: '{claim}'")
    return _result(
        CheckCategory.OBSERVATION_DISCIPLINE,
        not problems,
        "; ".join(problems) if problems else
        f"{len(packets)} disciplined packet(s); no forbidden claims found",
    )


def check_depth_compliance(
    package_dir: Path, expected_depth: int | None
) -> EvalCheckResult:
    """Does the agent's package hold the depth line everywhere it is declared?"""
    problems = []
    try:
        manifest = json.loads((package_dir / "manifest.json").read_text())
        capsule = yaml.safe_load((package_dir / "process_capsule.yaml").read_text())
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        return _result(
            CheckCategory.DEPTH_COMPLIANCE, False, f"package unreadable: {exc}"
        )
    declared = manifest.get("depth_level")
    if expected_depth is not None and declared != expected_depth:
        problems.append(
            f"declared depth {declared} != expected depth {expected_depth}"
        )
    if capsule.get("depth_level") != declared:
        problems.append(
            f"capsule depth {capsule.get('depth_level')} != manifest depth {declared}"
        )
    over = [
        s["name"]
        for s in capsule.get("steps", [])
        if s.get("depth_level", 0) > declared
    ]
    if over:
        problems.append(f"steps above declared depth: {over}")
    if declared == 5:
        problems.append("depth 5 (strategist) must never be an executing agent")
    return _result(
        CheckCategory.DEPTH_COMPLIANCE,
        not problems,
        "; ".join(problems) if problems else
        f"depth {declared} consistent across manifest, capsule, and all steps",
    )


def check_escalation_correctness(
    package_dir: Path, expected_escalation: str
) -> EvalCheckResult:
    """When this agent hits its limits, does the work land somewhere durable,
    with a named target and concrete requested checks?"""
    problems = []
    try:
        capsule = yaml.safe_load((package_dir / "process_capsule.yaml").read_text())
        contract = (package_dir / "CONTRACT.md").read_text()
    except (OSError, yaml.YAMLError) as exc:
        return _result(
            CheckCategory.ESCALATION_CORRECTNESS, False, f"package unreadable: {exc}"
        )
    rules = capsule.get("escalation_rules", [])
    if not rules:
        problems.append("no escalation rules declared")
    for rule in rules:
        if not rule.get("target"):
            problems.append(f"escalation rule '{rule.get('condition')}' names no target")
        if not rule.get("requested_checks"):
            problems.append(
                f"escalation rule '{rule.get('condition')}' requests no concrete checks"
            )
    if expected_escalation:
        targets = {rule.get("target") for rule in rules}
        if expected_escalation not in targets:
            problems.append(
                f"expected escalation target '{expected_escalation}' not among {sorted(targets)}"
            )
    if "ambiguity" not in contract.lower():
        problems.append("CONTRACT.md does not name ambiguity as an escalation trigger")
    return _result(
        CheckCategory.ESCALATION_CORRECTNESS,
        not problems,
        "; ".join(problems) if problems else
        "named target, concrete requested checks, ambiguity trigger documented",
    )


def check_complexity_reduction(
    ledger: RunLedger, workflow_id: str
) -> EvalCheckResult:
    """Are repeated failures being reviewed, and do resolutions actually
    change the process instead of adding controls on top?"""
    records = [
        r
        for r in ledger.non_conformance_records()
        if r.workflow_id == workflow_id
    ]
    by_kind: dict[str, list] = {}
    for r in records:
        by_kind.setdefault(r.kind.value, []).append(r)
    problems = []
    for kind, group in by_kind.items():
        if len(group) >= 2:
            unresolved = [
                r for r in group if r.resolution_status is ResolutionStatus.OPEN
            ]
            if unresolved:
                problems.append(
                    f"failure kind '{kind}' repeated {len(group)}x with "
                    f"{len(unresolved)} unresolved — repeated failures must "
                    f"trigger non-conformance review"
                )
    resolved = [r for r in records if r.resolution_status is ResolutionStatus.RESOLVED]
    for r in resolved:
        if not r.resolution_note.strip():
            problems.append(f"record {r.id} resolved without a process-change note")
    return _result(
        CheckCategory.COMPLEXITY_REDUCTION,
        not problems,
        "; ".join(problems) if problems else (
            f"{len(records)} record(s), no unreviewed repeats; "
            f"{len(resolved)} resolved with process changes"
        ),
    )


def check_required_fields(handoff_text: str, required: list[str]) -> list[str]:
    """Helper: return the case's required fields missing from the handoff."""
    return [field for field in required if field.lower() not in handoff_text.lower()]
