# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Maturity engine — evidence-based promotion, human-gated.

Implements the promotion criteria from docs/evaluation-strategy.md:

draft -> tested requires:
  * at least three distinct passing, human-reviewed eval cases,
  * passing coverage of handoff completeness, depth compliance, and
    escalation correctness (output schema stable + escalation documented),
  * the package itself validating cleanly,
  * a named human reviewer attesting they reviewed real output.

tested -> validated requires:
  * repeated real-world successful runs (3+ COMPLETE runs in the ledger),
  * non-conformance low or resolved (no OPEN records for the workflow),
  * a lower-depth implementation considered, with written rationale,
  * a passing handoff-completeness eval (another agent can consume the
    handoff without extra prompting).

The engine can BLOCK on its own, but it can never PROMOTE on its own:
``promote()`` refuses to run without a human reviewer's name. That is the
Phase 3 review gate — no automated promotion, ever.
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src.foundry.validator import validate_package
from src.runtime.ledger import RunLedger
from src.schemas.agent_package import Maturity
from src.schemas.eval_case import CheckCategory, CheckOutcome
from src.schemas.runtime_state import RunStatus

#: Categories that must each have at least one passing result for tested.
_TESTED_COVERAGE = (
    CheckCategory.HANDOFF_COMPLETENESS,
    CheckCategory.DEPTH_COMPLIANCE,
    CheckCategory.ESCALATION_CORRECTNESS,
)

#: Mapping from package evals.yaml mandatory checks to runner categories.
_MANDATORY_CHECK_SOURCES = {
    "output_schema_conformance": CheckCategory.HANDOFF_COMPLETENESS,
    "escalation_correctness": CheckCategory.ESCALATION_CORRECTNESS,
    "scope_compliance": CheckCategory.DEPTH_COMPLIANCE,
}


class PromotionRefusedError(Exception):
    """Raised when a promotion is attempted without meeting the criteria."""


@dataclass
class Criterion:
    """One promotion requirement and whether the evidence meets it."""

    name: str
    met: bool
    detail: str


@dataclass
class MaturityReport:
    """The full decision picture for one agent's next promotion step."""

    agent: str
    workflow_id: str
    current: Maturity
    target: Maturity | None
    criteria: list[Criterion]

    @property
    def allowed(self) -> bool:
        """True when every criterion is met (human attestation still required)."""
        return self.target is not None and all(c.met for c in self.criteria)


def _read_manifest(package_dir: Path) -> dict:
    """Read the package manifest as plain data."""
    return json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))


def _passing_by_category(ledger: RunLedger, agent: str) -> dict[CheckCategory, str]:
    """Latest passing eval result id per category for an agent."""
    coverage: dict[CheckCategory, str] = {}
    for result in ledger.eval_results_for(agent=agent):
        for check in result.checks:
            if (
                check.outcome is CheckOutcome.PASS
                and check.category not in coverage
            ):
                coverage[check.category] = result.result_id
    return coverage


def assess(package_dir: str | Path, ledger: RunLedger) -> MaturityReport:
    """Evaluate the evidence for the package's next maturity step.

    Pure inspection: assessing never changes anything. The report says what
    the target step is, which criteria are met, and what evidence is missing.
    """
    pkg = Path(package_dir)
    manifest = _read_manifest(pkg)
    agent = manifest["agent_name"]
    workflow_id = manifest["workflow_id"]
    current = Maturity(manifest["maturity"])
    criteria: list[Criterion] = []

    if current is Maturity.VALIDATED:
        return MaturityReport(agent, workflow_id, current, None, [
            Criterion("already validated", False, "no further maturity step exists")
        ])

    findings = validate_package(pkg)
    criteria.append(
        Criterion(
            "package validates cleanly",
            not findings,
            "no findings" if not findings else f"{len(findings)} finding(s): {findings[0]}",
        )
    )

    if current is Maturity.DRAFT:
        target = Maturity.TESTED
        results = ledger.eval_results_for(agent=agent)
        passing_cases = {
            r.case_id for r in results if r.overall is CheckOutcome.PASS
        }
        criteria.append(
            Criterion(
                "at least three distinct passing eval cases",
                len(passing_cases) >= 3,
                f"passing cases: {sorted(passing_cases) or 'none'}",
            )
        )
        coverage = _passing_by_category(ledger, agent)
        missing = [c.value for c in _TESTED_COVERAGE if c not in coverage]
        criteria.append(
            Criterion(
                "handoff, depth, and escalation each covered by a passing check",
                not missing,
                "all covered" if not missing else f"no passing result for: {missing}",
            )
        )
    else:  # TESTED -> VALIDATED
        target = Maturity.VALIDATED
        complete_runs = [
            r
            for r in ledger.list_runs(workflow_id)
            if r.status is RunStatus.COMPLETE
        ]
        criteria.append(
            Criterion(
                "repeated real-world successful runs (3+)",
                len(complete_runs) >= 3,
                f"{len(complete_runs)} complete run(s) in ledger",
            )
        )
        open_records = [
            r
            for r in ledger.non_conformance_records(open_only=True)
            if r.workflow_id == workflow_id
        ]
        criteria.append(
            Criterion(
                "non-conformance low or resolved",
                not open_records,
                "no open records"
                if not open_records
                else f"{len(open_records)} open record(s): {[r.id for r in open_records]}",
            )
        )
        coverage = _passing_by_category(ledger, agent)
        criteria.append(
            Criterion(
                "handoff consumable by another agent (passing completeness eval)",
                CheckCategory.HANDOFF_COMPLETENESS in coverage,
                coverage.get(
                    CheckCategory.HANDOFF_COMPLETENESS, "no passing completeness result"
                ),
            )
        )

    return MaturityReport(agent, workflow_id, current, target, criteria)


def promote(
    package_dir: str | Path,
    ledger: RunLedger,
    reviewed_by: str,
    rationale: str = "",
) -> MaturityReport:
    """Promote a package one maturity step, if the evidence allows it.

    Requires a human reviewer's name — the review gate doctrine forbids
    automated promotion. tested -> validated additionally requires a
    rationale for why a lower-depth implementation was or wasn't adopted.

    On success, rewrites maturity across SKILL.md, manifest.json, and
    process_capsule.yaml, fills the package's mandatory eval checks from
    recorded eval evidence, appends the promotion to learning_log.md, and
    records it in the append-only promotions ledger.
    """
    if not reviewed_by.strip():
        raise PromotionRefusedError(
            "promotion requires a human reviewer (--reviewed-by). Automated "
            "promotion is forbidden by the Phase 3 review gate."
        )
    pkg = Path(package_dir)
    report = assess(pkg, ledger)
    if report.target is None:
        raise PromotionRefusedError(
            f"'{report.agent}' is already {report.current.value}; no further step."
        )
    if report.target is Maturity.VALIDATED and not rationale.strip():
        raise PromotionRefusedError(
            "tested -> validated requires --rationale documenting that a "
            "lower-depth implementation was considered and adopted or "
            "rejected with reasons."
        )
    unmet = [c for c in report.criteria if not c.met]
    if unmet:
        raise PromotionRefusedError(
            "promotion blocked — unmet criteria: "
            + "; ".join(f"{c.name} ({c.detail})" for c in unmet)
        )

    # --- rewrite maturity declarations (all three must stay in agreement) --
    old, new = report.current.value, report.target.value
    for name in ("SKILL.md", "process_capsule.yaml"):
        path = pkg / name
        path.write_text(
            re.sub(
                rf"^maturity: {old}$",
                f"maturity: {new}",
                path.read_text(encoding="utf-8"),
                count=1,
                flags=re.MULTILINE,
            ),
            encoding="utf-8",
        )
    manifest = _read_manifest(pkg)
    manifest["maturity"] = new
    (pkg / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # --- fill the mandatory eval checks from recorded evidence -------------
    coverage = _passing_by_category(ledger, report.agent)
    evals_path = pkg / "evals.yaml"
    evals = yaml.safe_load(evals_path.read_text(encoding="utf-8"))
    for check_name, category in _MANDATORY_CHECK_SOURCES.items():
        if check_name in evals.get("checks", {}) and category in coverage:
            evals["checks"][check_name]["result"] = "pass"
            evals["checks"][check_name]["evidence"] = (
                f"eval result {coverage[category]} ({category.value})"
            )
    evals["overall"] = "pass"
    evals_path.write_text(yaml.safe_dump(evals, sort_keys=False), encoding="utf-8")

    # --- audit trail -------------------------------------------------------
    evidence = ", ".join(
        f"{category.value}={rid}" for category, rid in sorted(
            coverage.items(), key=lambda kv: kv[0].value
        )
    )
    today = datetime.now(timezone.utc).date().isoformat()
    log = pkg / "learning_log.md"
    log.write_text(
        log.read_text(encoding="utf-8")
        + "\n".join(
            [
                "",
                f"## {today} — correction",
                "",
                f"**What happened:** Promoted {old} -> {new}, reviewed by "
                f"{reviewed_by}.",
                "",
                f"**Evidence:** {evidence or 'see promotions ledger'}",
                ""
                + (f"\n**Lower-depth rationale:** {rationale}\n" if rationale else ""),
                "**Status:** resolved",
                "",
            ]
        ),
        encoding="utf-8",
    )
    ledger.record_promotion(
        agent=report.agent,
        workflow_id=report.workflow_id,
        from_maturity=old,
        to_maturity=new,
        reviewed_by=reviewed_by,
        rationale=rationale,
        evidence=evidence,
    )
    return assess(pkg, ledger)
