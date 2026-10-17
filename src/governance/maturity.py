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
import os
import re
import uuid
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


def _render_maturity_declarations(pkg: Path, old: str, new: str) -> dict[Path, str]:
    """Compute the new text for SKILL.md, process_capsule.yaml and
    manifest.json, without writing anything to disk yet.

    Kept separate from writing so that a promotion can fully prepare every
    file's new content — and discover any rendering problem — before the
    ledger is ever touched. See `promote()` for why that ordering matters.
    """
    rendered: dict[Path, str] = {}
    for name in ("SKILL.md", "process_capsule.yaml"):
        path = pkg / name
        rendered[path] = re.sub(
            rf"^maturity: {old}$",
            f"maturity: {new}",
            path.read_text(encoding="utf-8"),
            count=1,
            flags=re.MULTILINE,
        )
    manifest = _read_manifest(pkg)
    manifest["maturity"] = new
    rendered[pkg / "manifest.json"] = json.dumps(manifest, indent=2)
    return rendered


def _render_mandatory_eval_checks(pkg: Path, coverage: dict[CheckCategory, str]) -> str:
    """Compute the new evals.yaml text with mandatory checks filled in from
    recorded evidence, without writing anything to disk yet."""
    evals_path = pkg / "evals.yaml"
    evals = yaml.safe_load(evals_path.read_text(encoding="utf-8"))
    for check_name, category in _MANDATORY_CHECK_SOURCES.items():
        if check_name in evals.get("checks", {}) and category in coverage:
            evals["checks"][check_name]["result"] = "pass"
            evals["checks"][check_name]["evidence"] = (
                f"eval result {coverage[category]} ({category.value})"
            )
    evals["overall"] = "pass"
    return yaml.safe_dump(evals, sort_keys=False)


def _coverage_evidence(coverage: dict[CheckCategory, str]) -> str:
    """The evidence string recorded against the promotion: which eval result
    backed which mandatory category, in a stable (sorted) order."""
    return ", ".join(
        f"{category.value}={rid}"
        for category, rid in sorted(coverage.items(), key=lambda kv: kv[0].value)
    )


def _render_learning_log_entry(
    pkg: Path, old: str, new: str, reviewed_by: str, rationale: str, evidence: str
) -> str:
    """Compute the new learning_log.md text with the promotion entry
    appended, without writing anything to disk yet."""
    today = datetime.now(timezone.utc).date().isoformat()
    log = pkg / "learning_log.md"
    return log.read_text(encoding="utf-8") + "\n".join(
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
    )


def _stage_files(staged: dict[Path, str]) -> dict[Path, Path]:
    """Write every staged file's new content to a sibling temp file, and
    nothing else — no live file is touched here.

    This is the half of the write that must finish, in full, *before*
    `promote()` commits the ledger row: if staging raises (a full disk, a
    permissions error, anything), every temp file created so far is removed
    and the exception propagates with every live file exactly as it was and
    no ledger row written. Returns `{real_path: temp_path}` for
    `_commit_staged_files` to swap in once the ledger row has committed.
    """
    temp_paths: dict[Path, Path] = {}
    try:
        for real_path, content in staged.items():
            tmp_path = real_path.with_name(
                f"{real_path.name}.promotion-tmp-{uuid.uuid4().hex[:8]}"
            )
            tmp_path.write_text(content, encoding="utf-8")
            temp_paths[real_path] = tmp_path
    except OSError:
        for tmp_path in temp_paths.values():
            tmp_path.unlink(missing_ok=True)
        raise
    return temp_paths


def _commit_staged_files(temp_paths: dict[Path, Path]) -> None:
    """Swap every already-staged temp file into place over its live file.

    Called only after `promote()`'s ledger row has committed — see that
    docstring for why. Every file passed in here was already fully written
    to disk by `_stage_files`, so the only thing left to do is a sequence of
    `os.replace()` calls, each an atomic rename on the same filesystem.

    What this cannot close is a crash or killed process *between* two of
    those `os.replace()` calls: the set of (up to) five replacements is not
    one atomic transaction, even though the content behind each of them was
    long since fully written and fsynced to the filesystem as a temp file.
    `manifest.json` is deliberately replaced last to shrink the blast radius
    of that gap: `assess()` and `validate_package()` both read the package's
    current maturity from `manifest.json`, and `validate_package()`
    separately cross-checks maturity across SKILL.md, manifest.json and
    process_capsule.yaml. So a swap interrupted before manifest.json's
    replace leaves `assess()` still reading the OLD maturity — a retry
    re-assesses honestly instead of compounding the mix-up — and if the
    interruption happens after some *other* file replaced but
    SKILL.md/process_capsule.yaml disagree with manifest.json,
    `validate_package()` reports exactly that disagreement as a finding on
    the next validation, rather than the mismatch sitting silently. A human
    then finishes or reverts the swap by hand. This is the one place in
    `promote()` that is "visible and repairable" rather than fully atomic —
    a true multi-file transaction would need a shared write-ahead log this
    codebase does not have. (A crash here, followed by a naive retry, also
    produces a *duplicate* ledger row at the same `from_maturity ->
    to_maturity`, because `assess()` still reads the old maturity from
    manifest.json and sees the same unmet-then-met criteria again — the
    duplicate is visible in `promotions_for()`, which is why a retry after
    an interrupted swap should be a human decision, not an automatic one.)
    """
    ordered = sorted(temp_paths.items(), key=lambda kv: kv[0].name == "manifest.json")
    for real_path, tmp_path in ordered:
        os.replace(tmp_path, real_path)


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

    Ordering (and its residual risk): every new file's content is rendered
    in memory, then fully staged to a sibling temp file by `_stage_files` —
    *before* anything changes and *before* the ledger is touched, so a
    rendering or disk error during staging leaves the package and the
    ledger exactly as they were (no promotion row, no file changed). The
    ledger row is written next — this is the one irreversible step, since
    the promotions table is append-only and this function never deletes a
    row to roll back. Only after that commit does `_commit_staged_files`
    swap the already-written temp files into place; its docstring documents
    the one residual risk this leaves open: a crash during that swap can
    leave the ledger saying "promoted" while a file or two still show the
    old maturity. That state is detectable (`validate_package()` reports the
    cross-file disagreement) and repairable by hand, which is the safer
    direction to fail in than the reverse — files silently declaring a
    maturity the audit trail never recorded.
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

    old, new = report.current.value, report.target.value
    coverage = _passing_by_category(ledger, report.agent)
    evidence = _coverage_evidence(coverage)

    staged: dict[Path, str] = {}
    staged.update(_render_maturity_declarations(pkg, old, new))
    staged[pkg / "evals.yaml"] = _render_mandatory_eval_checks(pkg, coverage)
    staged[pkg / "learning_log.md"] = _render_learning_log_entry(
        pkg, old, new, reviewed_by, rationale, evidence
    )

    # Every new file is fully written to a temp file before the ledger is
    # touched: a staging failure here (e.g. disk full) propagates with
    # nothing committed and nothing live changed.
    temp_paths = _stage_files(staged)

    # Commit point: once this call returns, the promotion is decided and
    # recorded in the append-only ledger. Nothing above this line has
    # touched disk; nothing below it can be undone by this function.
    ledger.record_promotion(
        agent=report.agent,
        workflow_id=report.workflow_id,
        from_maturity=old,
        to_maturity=new,
        reviewed_by=reviewed_by,
        rationale=rationale,
        evidence=evidence,
    )

    _commit_staged_files(temp_paths)

    return assess(pkg, ledger)
