# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Workflow lifecycle services — the desktop's half of the §16 capabilities.

Tk-free by rule (ADR-007 §1): dataclasses in, dataclasses out, no widget
imports, no printing. The view renders what these return and decides nothing.

**Parity is by construction, not by discipline.** Every function here calls the
same governance and foundry entry points the CLI's ``workflow`` sub-app calls —
``validate_workflow``, ``promote``, ``assess_workflow``, ``apply_override``,
``build_cooperative_workflow``, ``export_workflow``. Neither surface owns a rule.
If the desktop and the CLI ever disagree about a workflow, one of them stopped
calling these.

Two shared reconciliations are mandatory on any path that loads a draft from
disk, and phase 6's completion note is explicit that skipping them reproduces
its bugs in the desktop:

* ``at_recorded_maturity`` — content comes from the file, progress from the
  ledger, so a promoted draft does not get promoted again forever.
* ``reattach_acceptances`` — validation is stateless, so an accepted finding
  comes back looking unaccepted unless the ledger's record is re-applied.

**Refusals come back as data.** A doctrine refusal is a normal outcome the
operator needs to read, not an exception the view has to catch. Every result
type carries ``ok`` and a ``refusal`` string; only genuine programming errors
raise.
"""

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

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
from src.governance.workflow_promotion import (
    PromotionRefusedError,
    RiskAcceptanceRefusedError,
    accept_risk,
    at_recorded_maturity,
    promote,
    reattach_acceptances,
)
from src.governance.workflow_rules import validate_workflow
from src.runtime.ledger import DEFAULT_DB_PATH, RunLedger
from src.schemas.cooperation import ExecutorClass, SafetyFloor
from src.schemas.findings import ValidationReport
from src.schemas.human_workflow import HumanWorkflowDraft
from src.schemas.templates import DRAFT_SKELETON

#: Lifecycle stages, in the order the operator moves through them. The view
#: renders this list; `lifecycle_status` reports one entry per stage.
STAGES = ("draft", "accountable", "assessed", "cooperative", "exported", "runs")


# ------------------------------------------------------------------- results


@dataclass
class Outcome:
    """Base shape every service returns: did it work, and what should I read.

    ``refusal`` is set when doctrine declined — a distinct thing from a
    mistake, and the view renders it differently.
    """

    ok: bool
    summary: str
    refusal: str = ""


@dataclass
class FindingView:
    """One finding, flattened for display."""

    finding_id: str
    rule_id: str
    blocking: bool
    accepted: bool
    where: str
    message: str
    remediation: str


@dataclass
class ValidationResult(Outcome):
    """A validation report, ready to render."""

    workflow_id: str = ""
    promotion_ready: bool = False
    findings: list[FindingView] = field(default_factory=list)
    unresolved_blocking: int = 0


@dataclass
class StageView:
    """One lifecycle stage and whether the workflow has reached it."""

    stage: str
    present: bool
    detail: str = ""


@dataclass
class LifecycleResult(Outcome):
    """Where a workflow sits, stage by stage."""

    workflow_id: str = ""
    stages: list[StageView] = field(default_factory=list)
    steps_not_ready: list[str] = field(default_factory=list)
    steps_overridden: list[str] = field(default_factory=list)


@dataclass
class WorkflowListing:
    """One workflow the ledger knows about."""

    workflow_id: str
    name: str
    version: str
    maturity: str


@dataclass
class ListResult(Outcome):
    """Every workflow in the ledger."""

    workflows: list[WorkflowListing] = field(default_factory=list)


@dataclass
class PromotionResult(Outcome):
    """The outcome of one maturity step."""

    workflow_id: str = ""
    from_maturity: str = ""
    to_maturity: str = ""
    promotion_id: str = ""
    blocking: list[FindingView] = field(default_factory=list)


@dataclass
class AssessmentView:
    """One step's cooperation assessment, flattened for display."""

    step_id: str
    recommended_executor: str
    effective_executor: str
    safety_floor: str
    supervision_mode: str
    automation_readiness: str
    overridden: bool
    rationale: str

    @property
    def floored(self) -> bool:
        """Whether a safety floor constrains what this step may become."""
        return self.safety_floor != SafetyFloor.NONE.value


@dataclass
class AssessmentResult(Outcome):
    """Every step's assessment, plus what stayed with a person."""

    workflow_id: str = ""
    assessments: list[AssessmentView] = field(default_factory=list)
    not_ready: list[str] = field(default_factory=list)
    carried_overrides: list[str] = field(default_factory=list)


@dataclass
class AssignmentView:
    """One approved step assignment, flattened for display."""

    step_id: str
    executor_class: str
    executor_identity: str
    human_owner: str
    escalation_target: str
    approval_gate: str


@dataclass
class CooperativeResult(Outcome):
    """The built assignments, and whether a human approved them."""

    workflow_id: str = ""
    approved: bool = False
    approved_by: str = ""
    assignments: list[AssignmentView] = field(default_factory=list)
    required_agent_packages: list[str] = field(default_factory=list)
    steps_kept_human: list[str] = field(default_factory=list)


@dataclass
class AgentView:
    """One agent declared on an exported brief."""

    agent_name: str
    depth_level: int
    escalation_target: str


@dataclass
class ExportResult(Outcome):
    """The exported brief, ready for the runtime."""

    workflow_id: str = ""
    states: list[str] = field(default_factory=list)
    transition_count: int = 0
    task_depth: str = ""
    status: str = ""
    agents: list[AgentView] = field(default_factory=list)
    steps_kept_human: list[str] = field(default_factory=list)
    written_path: str = ""


# ------------------------------------------------------------------- helpers


def _ledger(db: str | Path = DEFAULT_DB_PATH) -> RunLedger:
    """Open the ledger. Separated so tests and views name one path."""
    return RunLedger(str(db))


def _load_draft(path: str | Path) -> tuple[HumanWorkflowDraft | None, str]:
    """Read a draft from YAML, returning (draft, problem).

    Never raises for the expected failure modes. The GUI shows a bad file as a
    message, exactly as the CLI does — a traceback is not an error message.
    """
    file = Path(path)
    if not file.is_file():
        return None, f"No such file: {path}"
    try:
        raw = yaml.safe_load(file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return None, f"Not valid YAML: {exc}"
    if not isinstance(raw, dict):
        return None, f"{path} does not contain a workflow draft (expected a mapping)."
    try:
        return HumanWorkflowDraft.model_validate(raw), ""
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or '(root)'}: {e['msg']}"
            for e in exc.errors()
        )
        return None, f"Draft does not match the contract — {problems}"


def _finding_views(report: ValidationReport) -> list[FindingView]:
    """Flatten findings for display, blocking first then by rule id."""
    ordered = sorted(report.findings, key=lambda f: (not f.blocking, f.rule.rule_id))
    views = []
    for f in ordered:
        where = f.location.step_id or f.location.gate_id or "(workflow)"
        if f.location.field:
            where += f".{f.location.field}"
        views.append(
            FindingView(
                finding_id=f.finding_id,
                rule_id=f.rule.rule_id,
                blocking=f.blocking,
                accepted=f.acceptance is not None,
                where=where,
                message=f.message,
                remediation=f.remediation,
            )
        )
    return views


# ------------------------------------------------------ capture and inventory


def create_draft(
    workflow_id: str, out_path: str | Path, *, overwrite: bool = False
) -> Outcome:
    """Write a draft skeleton for the operator to fill in.

    The skeleton is deliberately incomplete: it loads and saves, and validation
    then names what is missing. Refusing to record an unfinished process would
    make honest capture impossible, and honest capture is the first stage.

    Uses the same template as the CLI (``src/schemas/templates``), so the two
    surfaces cannot teach different rules.
    """
    import re

    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", workflow_id):
        return Outcome(
            ok=False,
            summary="Invalid workflow id",
            refusal=(
                f"'{workflow_id}' is not a valid workflow id. Use lowercase "
                f"words separated by hyphens, e.g. weekly-report."
            ),
        )
    target = Path(out_path)
    if target.exists() and not overwrite:
        return Outcome(
            ok=False,
            summary="File already exists",
            refusal=f"{target} already exists. Choose another name or allow overwrite.",
        )
    try:
        target.write_text(
            DRAFT_SKELETON.format(
                workflow_id=workflow_id,
                name=workflow_id.replace("-", " ").title(),
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        return Outcome(ok=False, summary="Could not write the file", refusal=str(exc))
    return Outcome(ok=True, summary=f"Wrote draft skeleton: {target}")


def import_draft(path: str | Path, db: str | Path = DEFAULT_DB_PATH) -> Outcome:
    """Load a draft file into the ledger — the desktop's *save*.

    Saving never depends on the draft being complete. Blocking findings block
    promotion and nothing else; a tool that refused to store a messy workflow
    would prevent the capture it exists to encourage.
    """
    draft, problem = _load_draft(path)
    if draft is None:
        return Outcome(ok=False, summary="Could not read the draft", refusal=problem)
    _ledger(db).save_workflow_draft(draft)
    return Outcome(
        ok=True,
        summary=f"Saved '{draft.workflow_id}' version {draft.version} to the ledger.",
    )


def reload_draft(workflow_id: str, db: str | Path = DEFAULT_DB_PATH) -> Outcome:
    """Confirm a stored draft can be read back, and say what it is.

    The other half of save: a stage the operator can leave and come back to.
    """
    try:
        draft = _ledger(db).load_workflow_draft(workflow_id)
    except KeyError as exc:
        return Outcome(ok=False, summary="No stored draft", refusal=str(exc))
    return Outcome(
        ok=True,
        summary=(
            f"{draft.name} — version {draft.version}, {draft.maturity.value}, "
            f"{len(draft.steps)} step(s)."
        ),
    )


def list_workflows(db: str | Path = DEFAULT_DB_PATH) -> ListResult:
    """Every workflow the ledger knows about, most recently updated first."""
    drafts = _ledger(db).list_workflow_drafts()
    listings = [
        WorkflowListing(
            workflow_id=d.workflow_id,
            name=d.name,
            version=d.version,
            maturity=d.maturity.value,
        )
        for d in drafts
    ]
    return ListResult(
        ok=True,
        summary=(
            f"{len(listings)} workflow(s) stored."
            if listings
            else "No workflows stored yet."
        ),
        workflows=listings,
    )


# ---------------------------------------------------------- validate and gate


def validate_draft(
    path: str | Path, db: str | Path = DEFAULT_DB_PATH, *, save: bool = False
) -> ValidationResult:
    """Check a draft against the 16 rules and report every finding.

    Not promotion-ready is a normal, expected result — ``ok`` stays true when
    the draft was readable, and ``promotion_ready`` carries the gate. Conflating
    them would make an honest first capture look like a failure.
    """
    draft, problem = _load_draft(path)
    if draft is None:
        return ValidationResult(ok=False, summary="Could not read the draft", refusal=problem)

    ledger = _ledger(db)
    report = validate_workflow(draft)
    reattach_acceptances(report, ledger)
    if save:
        ledger.save_workflow_draft(draft)
        ledger.save_validation_report(report)

    unresolved = len(report.unresolved_blocking)
    return ValidationResult(
        ok=True,
        summary=(
            f"{draft.workflow_id}: {len(report.findings)} finding(s); "
            + ("ready to promote." if report.promotion_ready else f"{unresolved} blocking.")
        ),
        workflow_id=report.workflow_id,
        promotion_ready=report.promotion_ready,
        findings=_finding_views(report),
        unresolved_blocking=unresolved,
    )


def accept_finding(
    path: str | Path,
    finding_id: str,
    accepted_by: str,
    rationale: str,
    db: str | Path = DEFAULT_DB_PATH,
) -> Outcome:
    """Record a conscious decision to accept an advisory finding.

    Accepting unlocks nothing — advisory findings never gated promotion. What it
    changes is whether the reason is on the record, which is the difference
    between a considered risk and an unexamined one.

    A blocking finding cannot be accepted; that refusal keeps the gate real.
    """
    if not accepted_by.strip() or not rationale.strip():
        return Outcome(
            ok=False,
            summary="Missing actor or reason",
            refusal=(
                "An acceptance needs a name and a reason. Without them it is "
                "indistinguishable from dismissing a warning."
            ),
        )
    draft, problem = _load_draft(path)
    if draft is None:
        return Outcome(ok=False, summary="Could not read the draft", refusal=problem)

    ledger = _ledger(db)
    report = validate_workflow(draft)
    reattach_acceptances(report, ledger)
    try:
        acceptance = accept_risk(
            ledger,
            draft.workflow_id,
            report,
            finding_id=finding_id,
            accepted_by=accepted_by,
            rationale=rationale,
        )
    except RiskAcceptanceRefusedError as exc:
        return Outcome(ok=False, summary="Acceptance refused", refusal=str(exc))

    ledger.save_workflow_draft(draft)
    ledger.save_validation_report(report)
    return Outcome(
        ok=True,
        summary=(
            f"Accepted {acceptance.rule.rule_id} as residual risk. "
            f"This records a decision; it does not change whether the workflow "
            f"may be promoted."
        ),
    )


def promote_draft(
    path: str | Path, promoted_by: str, db: str | Path = DEFAULT_DB_PATH
) -> PromotionResult:
    """Advance a draft one step up the maturity ladder.

    Progress comes from the ledger and content from the file, so a draft already
    promoted is not promoted again — see ``at_recorded_maturity``.
    """
    if not promoted_by.strip():
        return PromotionResult(
            ok=False,
            summary="Missing actor",
            refusal="A promotion must name who made it.",
        )
    draft, problem = _load_draft(path)
    if draft is None:
        return PromotionResult(ok=False, summary="Could not read the draft", refusal=problem)

    ledger = _ledger(db)
    draft, _note = at_recorded_maturity(draft, ledger)
    report = validate_workflow(draft)
    reattach_acceptances(report, ledger)

    if report.unresolved_blocking:
        return PromotionResult(
            ok=False,
            summary=f"{len(report.unresolved_blocking)} blocking finding(s) must be fixed.",
            refusal="Promotion is blocked until the blocking findings are resolved.",
            workflow_id=draft.workflow_id,
            blocking=_finding_views(report),
        )

    assessments = ledger.load_cooperation_assessments(draft.workflow_id)
    try:
        outcome = promote(
            ledger, draft, report, promoted_by=promoted_by, assessments=assessments
        )
    except PromotionRefusedError as exc:
        return PromotionResult(
            ok=False, summary="Promotion refused", refusal=str(exc),
            workflow_id=draft.workflow_id,
        )
    return PromotionResult(
        ok=True,
        summary=(
            f"{outcome.workflow_id}: {outcome.from_maturity.value} → "
            f"{outcome.to_maturity.value}"
        ),
        workflow_id=outcome.workflow_id,
        from_maturity=outcome.from_maturity.value,
        to_maturity=outcome.to_maturity.value,
        promotion_id=outcome.promotion_id,
    )


# ------------------------------------------------------------- cooperation


def assess_cooperation(
    workflow_id: str, db: str | Path = DEFAULT_DB_PATH
) -> AssessmentResult:
    """Recommend an executor for every step, carrying recorded overrides forward.

    No model is involved: the same workflow always yields the same
    recommendations, which is what makes them arguable before they are run.

    Re-assessing preserves a human's recorded override rather than recomputing
    over it. Reads take the newest row per step, so dropping the override here
    would stop it governing while leaving it visible in the history.
    """
    ledger = _ledger(db)
    try:
        workflow = ledger.load_accountable_workflow(workflow_id)
    except KeyError:
        return AssessmentResult(
            ok=False,
            summary="Not promoted yet",
            refusal=(
                f"No accountable workflow stored for '{workflow_id}'. "
                f"Promote a draft to ACCOUNTABLE first."
            ),
        )

    systems: list[str] = []
    try:
        systems = ledger.load_workflow_draft(workflow_id).systems
    except KeyError:
        pass  # No stored draft: report no tools rather than inventing them.

    fresh = {a.step_id: a for a in assess_workflow(workflow, systems=systems)}
    carried: list[str] = []
    for stored in ledger.load_cooperation_assessments(workflow_id):
        if stored.override is None or stored.step_id not in fresh:
            continue
        try:
            fresh[stored.step_id] = apply_override(
                fresh[stored.step_id],
                stored.override.overridden_to,
                actor=stored.override.actor,
                rationale=stored.override.rationale,
            )
            carried.append(stored.step_id)
        except OverrideRefusedError as exc:
            return AssessmentResult(
                ok=False,
                summary="A recorded override is no longer permitted",
                refusal=(
                    f"'{stored.step_id}' has a recorded override to "
                    f"{stored.override.overridden_to.value} that would now cross "
                    f"a safety floor: {exc}"
                ),
                workflow_id=workflow_id,
            )

    ordered = [fresh[s.step_id] for s in workflow.steps]
    ledger.save_cooperation_assessments(ordered)
    return AssessmentResult(
        ok=True,
        summary=f"Assessed {len(ordered)} step(s).",
        workflow_id=workflow_id,
        assessments=[
            AssessmentView(
                step_id=a.step_id,
                recommended_executor=a.recommended_executor.value,
                effective_executor=a.effective_executor.value,
                safety_floor=a.safety_floor.value,
                supervision_mode=a.supervision_mode.value,
                automation_readiness=a.automation_readiness.value,
                overridden=a.override is not None,
                rationale=a.rationale,
            )
            for a in ordered
        ],
        not_ready=[a.step_id for a in steps_not_ready(ordered)],
        carried_overrides=carried,
    )


def override_executor(
    workflow_id: str,
    step_id: str,
    executor_class: str,
    actor: str,
    rationale: str,
    db: str | Path = DEFAULT_DB_PATH,
) -> AssessmentResult:
    """Replace one step's recommended executor with a human's judgment.

    **One-directional.** Moving work toward human control is always allowed;
    moving a step that hit a safety floor toward greater autonomy is refused.
    The floor exists because of a fact about the work, and that fact does not
    change because someone would prefer it did.
    """
    if not actor.strip() or not rationale.strip():
        return AssessmentResult(
            ok=False,
            summary="Missing actor or reason",
            refusal=(
                "An override needs a name and a reason. Without them it is "
                "indistinguishable from a mis-click, and this decision governs "
                "who may act unsupervised."
            ),
            workflow_id=workflow_id,
        )
    try:
        target = ExecutorClass(executor_class)
    except ValueError:
        return AssessmentResult(
            ok=False,
            summary="Unknown executor class",
            refusal=(
                f"'{executor_class}' is not an executor class. Valid values: "
                f"{', '.join(e.value for e in ExecutorClass)}"
            ),
            workflow_id=workflow_id,
        )

    ledger = _ledger(db)
    stored = {a.step_id: a for a in ledger.load_cooperation_assessments(workflow_id)}
    if step_id not in stored:
        return AssessmentResult(
            ok=False,
            summary="Unknown step",
            refusal=(
                f"'{step_id}' has no assessment in '{workflow_id}'. "
                f"Assess the workflow first."
            ),
            workflow_id=workflow_id,
        )
    try:
        updated = apply_override(stored[step_id], target, actor=actor, rationale=rationale)
    except OverrideRefusedError as exc:
        return AssessmentResult(
            ok=False, summary="Override refused", refusal=str(exc), workflow_id=workflow_id
        )
    ledger.save_cooperation_assessments([updated])
    return assess_cooperation(workflow_id, db)


def build_cooperative(
    workflow_id: str, approved_by: str = "", db: str | Path = DEFAULT_DB_PATH
) -> CooperativeResult:
    """Assign every step from the stored assessments.

    Reads each assessment's *effective* executor, so a recorded override governs
    and the decision table's recommendation does not.

    Approval is a separate human act: building without ``approved_by`` lets the
    operator read the assignments before signing them, and export refuses an
    unapproved workflow.
    """
    ledger = _ledger(db)
    try:
        workflow = ledger.load_accountable_workflow(workflow_id)
    except KeyError:
        return CooperativeResult(
            ok=False,
            summary="Not promoted yet",
            refusal=f"No accountable workflow stored for '{workflow_id}'.",
        )
    assessments = ledger.load_cooperation_assessments(workflow_id)
    if not assessments:
        return CooperativeResult(
            ok=False,
            summary="Not assessed yet",
            refusal=(
                f"No cooperation assessments stored for '{workflow_id}'. "
                f"Assess the workflow before building assignments."
            ),
        )
    try:
        cooperative = build_cooperative_workflow(
            workflow, assessments, approved_by=approved_by
        )
    except ExportRefusedError as exc:
        return CooperativeResult(ok=False, summary="Build refused", refusal=str(exc))

    ledger.save_cooperative_workflow(cooperative)
    kept = steps_kept_human(cooperative)
    return CooperativeResult(
        ok=True,
        summary=(
            f"Assigned {len(cooperative.assignments)} step(s); "
            f"{len(kept)} stay with a person."
        ),
        workflow_id=workflow_id,
        approved=cooperative.approved,
        approved_by=cooperative.approved_by,
        assignments=[
            AssignmentView(
                step_id=a.step_id,
                executor_class=a.executor_class.value,
                executor_identity=a.executor_identity,
                human_owner=a.human_owner,
                escalation_target=a.escalation_target,
                approval_gate=a.approval_gate,
            )
            for a in cooperative.assignments
        ],
        required_agent_packages=list(cooperative.required_agent_packages),
        steps_kept_human=kept,
    )


def export_brief(
    workflow_id: str, out_path: str | Path = "", db: str | Path = DEFAULT_DB_PATH
) -> ExportResult:
    """Flatten the approved workflow into a brief the existing runtime executes.

    Steps become states; a step needing a human to authorize each execution is
    split into the agent's work, a waiting state, and the person's decision — so
    the approval is a place the work sits and an event the ledger records.
    """
    ledger = _ledger(db)
    try:
        workflow = ledger.load_accountable_workflow(workflow_id)
    except KeyError:
        return ExportResult(
            ok=False,
            summary="Not promoted yet",
            refusal=f"No accountable workflow stored for '{workflow_id}'.",
        )
    try:
        cooperative = ledger.load_cooperative_workflow(workflow_id)
    except KeyError:
        return ExportResult(
            ok=False,
            summary="No assignments yet",
            refusal=(
                f"No cooperative workflow stored for '{workflow_id}'. "
                f"Build and approve the assignments first."
            ),
        )
    try:
        brief = export_workflow(cooperative, workflow)
    except ExportRefusedError as exc:
        return ExportResult(ok=False, summary="Export refused", refusal=str(exc))

    ledger.save_workflow(brief)
    written = ""
    if out_path:
        try:
            Path(out_path).write_text(
                yaml.safe_dump(brief.model_dump(mode="json"), sort_keys=False, width=100),
                encoding="utf-8",
            )
            written = str(out_path)
        except OSError as exc:
            return ExportResult(
                ok=False, summary="Could not write the brief", refusal=str(exc)
            )
    kept = steps_kept_human(cooperative)
    return ExportResult(
        ok=True,
        summary=(
            f"Exported {len(brief.states)} states, {len(brief.transitions)} "
            f"transitions, {len(brief.agents)} agent(s)."
        ),
        workflow_id=brief.id,
        states=list(brief.states),
        transition_count=len(brief.transitions),
        task_depth=brief.task_depth.value,
        status=brief.status.value,
        agents=[
            AgentView(
                agent_name=a.agent_name,
                depth_level=a.depth_level,
                escalation_target=a.escalation_target,
            )
            for a in brief.agents
        ],
        steps_kept_human=kept,
        written_path=written,
    )


# --------------------------------------------------------------- the overview


def lifecycle_status(
    workflow_id: str, db: str | Path = DEFAULT_DB_PATH
) -> LifecycleResult:
    """Where a workflow sits, stage by stage. Never refuses.

    The view's left-hand column. An absent stage is reported as absent, because
    "nothing here yet" answers the question rather than failing it — this is the
    screen someone opens when they have lost track.
    """
    ledger = _ledger(db)
    stages: list[StageView] = []

    try:
        draft = ledger.load_workflow_draft(workflow_id)
    except KeyError:
        draft = None
    stages.append(
        StageView(
            "draft",
            draft is not None,
            f"version {draft.version}, {draft.maturity.value}" if draft else "",
        )
    )

    try:
        accountable = ledger.load_accountable_workflow(workflow_id)
    except KeyError:
        accountable = None
    stages.append(
        StageView(
            "accountable",
            accountable is not None,
            (
                f"version {accountable.version}, {accountable.maturity.value}, "
                f"{len(accountable.steps)} steps"
                if accountable
                else ""
            ),
        )
    )

    assessments = ledger.load_cooperation_assessments(workflow_id)
    not_ready = [a.step_id for a in steps_not_ready(assessments)]
    overridden = [a.step_id for a in assessments if a.override is not None]
    stages.append(
        StageView(
            "assessed",
            bool(assessments),
            (
                f"{len(assessments)} step(s); {len(overridden)} overridden; "
                f"{len(not_ready)} not ready"
                if assessments
                else ""
            ),
        )
    )

    try:
        cooperative = ledger.load_cooperative_workflow(workflow_id)
    except KeyError:
        cooperative = None
    stages.append(
        StageView(
            "cooperative",
            cooperative is not None,
            (
                (
                    f"approved by {cooperative.approved_by}"
                    if cooperative.approved
                    else "built, NOT approved"
                )
                if cooperative
                else ""
            ),
        )
    )

    try:
        exported = ledger.load_workflow(workflow_id)
    except Exception:
        exported = None
    stages.append(
        StageView(
            "exported",
            exported is not None,
            (
                f"{len(exported.states)} states, {len(exported.agents)} agent(s), "
                f"status {exported.status.value}"
                if exported
                else ""
            ),
        )
    )

    runs = ledger.list_runs(workflow_id) if exported is not None else []
    stages.append(StageView("runs", bool(runs), f"{len(runs)} run(s)" if runs else ""))

    reached = sum(1 for s in stages if s.present)
    return LifecycleResult(
        ok=True,
        summary=(
            f"{workflow_id}: {reached} of {len(stages)} stage(s) reached."
            if reached
            else f"Nothing stored for '{workflow_id}' yet."
        ),
        workflow_id=workflow_id,
        stages=stages,
        steps_not_ready=not_ready,
        steps_overridden=overridden,
    )
