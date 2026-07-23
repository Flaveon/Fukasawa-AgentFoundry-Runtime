# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Eval runner — executes an eval case against a run's real artifacts.

The runner gathers what the run actually produced (handoff file, observation
packets, non-conformance history, the agent's package) and puts each
declared check to it. Results are persisted to the ledger; nothing here
mutates a package or promotes anything — that is the maturity engine's job,
and it acts only on recorded results.
"""

import uuid
from pathlib import Path

import yaml

from src.governance import checks as C
from src.runtime.handoff import DEFAULT_HANDOFF_DIR
from src.runtime.ledger import RunLedger
from src.schemas.eval_case import (
    CheckCategory,
    CheckOutcome,
    EvalCase,
    EvalCheckResult,
    EvalResult,
)


def load_eval_case(path: str | Path) -> EvalCase:
    """Load and validate an eval case YAML file."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return EvalCase.model_validate(raw)


def run_eval_case(
    case: EvalCase,
    ledger: RunLedger,
    run_id: str,
    package_dir: str | Path | None = None,
    handoff_dir: str | Path = DEFAULT_HANDOFF_DIR,
) -> EvalResult:
    """Run every check the case declares and persist the result.

    Checks that need artifacts the caller did not provide (e.g. depth
    compliance without a package) come back SKIPPED, not silently passed —
    an eval that quietly ignores what it cannot see would be an unsupported
    claim about quality.
    """
    handoff_path = Path(handoff_dir) / f"{run_id}.md"
    handoff_text = (
        handoff_path.read_text(encoding="utf-8") if handoff_path.exists() else ""
    )
    package = Path(package_dir) if package_dir else None
    results: list[EvalCheckResult] = []

    for category, enabled in case.scoring.items():
        if not enabled:
            results.append(
                EvalCheckResult(
                    category=category,
                    outcome=CheckOutcome.SKIPPED,
                    evidence="not scored by this case",
                )
            )
            continue

        if category is CheckCategory.HANDOFF_COMPLETENESS:
            if not handoff_text:
                result = EvalCheckResult(
                    category=category,
                    outcome=CheckOutcome.FAIL,
                    evidence=f"no handoff file at {handoff_path}",
                )
            else:
                result = C.check_handoff_completeness(handoff_text)
                # Layer the case's own required fields on the doctrine ones.
                missing = C.check_required_fields(
                    handoff_text, case.expected_outputs.required_fields
                )
                if missing and result.outcome is CheckOutcome.PASS:
                    result = EvalCheckResult(
                        category=category,
                        outcome=CheckOutcome.FAIL,
                        evidence=f"required fields missing from handoff: {missing}",
                    )
        elif category is CheckCategory.OBSERVATION_DISCIPLINE:
            result = C.check_observation_discipline(
                ledger, run_id, case.expected_outputs.forbidden_claims, handoff_text
            )
        elif category is CheckCategory.DEPTH_COMPLIANCE:
            result = (
                C.check_depth_compliance(package, case.expected_outputs.expected_depth)
                if package
                else EvalCheckResult(
                    category=category,
                    outcome=CheckOutcome.SKIPPED,
                    evidence="no package directory provided",
                )
            )
        elif category is CheckCategory.ESCALATION_CORRECTNESS:
            result = (
                C.check_escalation_correctness(
                    package, case.expected_outputs.expected_escalation
                )
                if package
                else EvalCheckResult(
                    category=category,
                    outcome=CheckOutcome.SKIPPED,
                    evidence="no package directory provided",
                )
            )
        elif category is CheckCategory.COMPLEXITY_REDUCTION:
            result = C.check_complexity_reduction(ledger, case.workflow)
        else:  # pragma: no cover — enum is exhaustive
            raise ValueError(f"unknown check category: {category}")
        results.append(result)

    outcome = EvalResult.overall_from(results)
    eval_result = EvalResult(
        result_id=f"eval-{uuid.uuid4().hex[:8]}",
        case_id=case.case_id,
        workflow_id=case.workflow,
        agent=case.agent,
        run_id=run_id,
        checks=results,
        overall=outcome,
        notes=case.notes,
    )
    ledger.save_eval_result(eval_result)
    return eval_result
