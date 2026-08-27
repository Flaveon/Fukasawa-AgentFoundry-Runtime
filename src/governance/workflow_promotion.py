# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Workflow maturity promotion — earning the right to move up the ladder.

A workflow climbs from `OBSERVED` to `VALIDATED` one step at a time, and each
step has to be earned with evidence. This module owns the transition table and
the gates; it borrows its shape from `src/governance/maturity.py`, which does
the same job for agent packages — assess what is met, refuse with a reason when
it is not, and record the decision either way.

Four rules govern everything here:

* **One step at a time.** There is no path from `OBSERVED` to `RUNTIME_READY`.
  A workflow that skipped mapping and accountability has not become accountable
  by being declared so.
* **Blocking findings prevent promotion, and cannot be accepted away.** A
  blocking finding is fixed or the workflow does not advance. Only non-blocking
  findings may be consciously accepted, and only with an actor, a timestamp,
  and a rationale.
* **Promotion produces an artifact, never a mutation.** The source draft is
  left exactly as it was. What was approved, and on what evidence, stays
  readable afterwards.
* **Refusals are recorded too.** A declined promotion and its reason are part
  of a workflow's history; keeping only the successes would make the record a
  advertisement rather than an audit.

This release enforces gates through `RUNTIME_READY`. `DEPLOYED` and `VALIDATED`
are recorded states whose criteria delegate to evidence the existing runtime
already produces — real runs and evaluation results — plus a named human. No
new deployment machinery is built here, which would breach the release's
non-goals.
"""

from dataclasses import dataclass, field
from typing import Optional, Sequence

from src.runtime.ledger import RunLedger
from src.schemas.cooperation import CooperationAssessment
from src.schemas.eval_case import CheckOutcome
from src.schemas.findings import RULE_SET_VERSION, RiskAcceptance, ValidationReport
from src.schemas.human_workflow import (
    SCHEMA_VERSION,
    AccountableWorkflow,
    HumanWorkflowDraft,
    PromotionLineage,
    WorkflowMaturity,
)

#: The ladder, in order. Promotion moves exactly one step along it.
PROMOTION_PATH: list[WorkflowMaturity] = [
    WorkflowMaturity.OBSERVED,
    WorkflowMaturity.MAPPED,
    WorkflowMaturity.ACCOUNTABLE,
    WorkflowMaturity.COOPERATION_READY,
    WorkflowMaturity.COOPERATIVE_DESIGN_APPROVED,
    WorkflowMaturity.RUNTIME_READY,
    WorkflowMaturity.DEPLOYED,
    WorkflowMaturity.VALIDATED,
]

#: The last maturity this release gates with its own logic. Beyond it, criteria
#: delegate to the existing run ledger and evaluation machinery.
LAST_ENFORCED = WorkflowMaturity.RUNTIME_READY

#: Findings in these dimensions must be clear before a workflow is even
#: structurally sound. Used by the OBSERVED -> MAPPED gate.
_STRUCTURAL_RULES = frozenset({"HW-001", "HW-002", "HW-005", "HW-006", "HW-007"})


class PromotionRefusedError(Exception):
    """Raised when a promotion is attempted without the evidence to justify it."""


class RiskAcceptanceRefusedError(Exception):
    """Raised when someone tries to accept a finding that must be fixed instead."""


def next_maturity(current: WorkflowMaturity) -> Optional[WorkflowMaturity]:
    """The one step available from here, or None at the top of the ladder."""
    index = PROMOTION_PATH.index(current)
    if index + 1 >= len(PROMOTION_PATH):
        return None
    return PROMOTION_PATH[index + 1]


def is_valid_transition(
    current: WorkflowMaturity, target: WorkflowMaturity
) -> bool:
    """Whether target is exactly one step forward from current.

    Everything else is invalid — backwards, sideways, or skipping. A workflow
    does not become accountable by asserting it.
    """
    return next_maturity(current) is target


@dataclass
class Criterion:
    """One thing that must be true for a promotion, and whether it is."""

    name: str
    met: bool
    detail: str


@dataclass
class PromotionAssessment:
    """The evidence picture for one workflow's next step."""

    workflow_id: str
    current: WorkflowMaturity
    target: Optional[WorkflowMaturity]
    criteria: list[Criterion] = field(default_factory=list)
    enforced: bool = True

    @property
    def allowed(self) -> bool:
        """Whether every criterion for the next step is met."""
        return bool(self.target) and all(c.met for c in self.criteria)

    @property
    def unmet(self) -> list[Criterion]:
        """The criteria standing in the way, for a refusal message."""
        return [c for c in self.criteria if not c.met]


# ------------------------------------------------------------- risk acceptance


def accept_risk(
    ledger: RunLedger,
    workflow_id: str,
    report: ValidationReport,
    finding_id: str,
    accepted_by: str,
    rationale: str,
) -> RiskAcceptance:
    """Consciously accept a non-blocking finding as residual risk.

    Refuses two things outright: accepting a finding that does not exist, and
    accepting a **blocking** one. A blocking finding names a gap that makes the
    workflow unaccountable — permitting it to be waived would turn the whole
    gate into a formality.

    The contract already requires a non-empty rationale and actor, so an
    acceptance that reaches the ledger is always a decision on the record.
    """
    finding = next((f for f in report.findings if f.finding_id == finding_id), None)
    if finding is None:
        raise RiskAcceptanceRefusedError(
            f"no finding '{finding_id}' in this report; nothing to accept"
        )
    if finding.blocking:
        raise RiskAcceptanceRefusedError(
            f"finding '{finding_id}' ({finding.rule.rule_id}) is blocking and "
            f"cannot be accepted as residual risk — it has to be fixed. "
            f"Remediation: {finding.remediation}"
        )
    acceptance = RiskAcceptance(
        finding_id=finding_id,
        rule=finding.rule,
        accepted_by=accepted_by,
        rationale=rationale,
    )
    finding.acceptance = acceptance
    ledger.save_risk_acceptance(workflow_id, acceptance)
    return acceptance


# ------------------------------------------------- reconciling file and ledger
#
# Two functions every caller that loads a draft from disk must go through. They
# exist because of one recurring mistake: a draft *file* carries the workflow's
# content, but decisions made about it — how far it has been promoted, which
# findings a human accepted — live in the ledger. A caller that reads only the
# file silently discards those decisions, and the decisions are the part this
# product exists to preserve.
#
# Both are here rather than in a CLI or a view so the CLI, the desktop, and any
# future service surface share one implementation. Reimplementing either is how
# the bug comes back.


def at_recorded_maturity(
    draft: HumanWorkflowDraft, ledger: RunLedger
) -> tuple[HumanWorkflowDraft, str]:
    """Lift a draft read from disk to the maturity the ledger has recorded.

    ``promote`` stores an advanced copy of the draft; it never rewrites the
    operator's YAML. So a file that has already been promoted still says
    ``OBSERVED`` on disk, and a caller trusting the file would let the same step
    be promoted forever.

    Content comes from the file and progress from the ledger, which keeps both
    honest: edits to the file are never ignored, and progress already recorded is
    never repeated. Returns the draft plus a note to show the operator, or an
    empty note when nothing was lifted.
    """
    try:
        stored = ledger.load_workflow_draft(draft.workflow_id, draft.version)
    except KeyError:
        return draft, ""
    if PROMOTION_PATH.index(stored.maturity) <= PROMOTION_PATH.index(draft.maturity):
        return draft, ""
    lifted = draft.model_copy(deep=True)
    lifted.maturity = stored.maturity
    return lifted, (
        f"{draft.workflow_id} is recorded at {stored.maturity.value}; "
        f"using the file's content at that maturity rather than "
        f"{draft.maturity.value}."
    )


def reattach_acceptances(report: ValidationReport, ledger: RunLedger) -> list[str]:
    """Re-attach previously recorded risk acceptances to a fresh report.

    Validation is deterministic and stateless: it re-derives findings from the
    draft every time, with no memory of what a human already accepted. The
    acceptances live in the ledger, so without this the record of a conscious
    decision never reaches the artifact that cites it —
    ``AccountableWorkflow.accepted_risks`` would always be empty.

    Matching is by ``finding_id``, which is content-addressed (rule id plus
    location), so this is stable across re-validation. If the operator edits the
    step a finding was about, its id changes and the stale acceptance simply does
    not re-attach — which is correct: accepting a finding about an older version
    of a step should not silently carry forward.

    Mutates ``report`` in place and returns the finding ids re-attached.
    """
    stored = {
        row["finding_id"]: row
        for row in ledger.risk_acceptances_for(report.workflow_id)
    }
    reattached: list[str] = []
    for finding in report.findings:
        row = stored.get(finding.finding_id)
        if row is None or finding.acceptance is not None:
            continue
        # A blocking finding can never be accepted, so a stored acceptance for
        # one means the rule's policy changed since. Refusing to re-attach it
        # keeps the gate real; the row stays in the ledger as history.
        if finding.blocking:
            continue
        finding.acceptance = RiskAcceptance(
            finding_id=finding.finding_id,
            rule=finding.rule,
            accepted_by=row["accepted_by"],
            accepted_at=row["accepted_at"],
            rationale=row["rationale"],
        )
        reattached.append(finding.finding_id)
    return reattached


# ------------------------------------------------------------------- assessing


def _criteria_for(
    target: WorkflowMaturity,
    draft: HumanWorkflowDraft,
    report: Optional[ValidationReport],
    assessments: Sequence["CooperationAssessment"] = (),
) -> list[Criterion]:
    """What the next step requires, and whether the evidence supports it."""
    if target is WorkflowMaturity.MAPPED:
        if report is None:
            return [Criterion("validation report", False, "no report supplied")]
        structural = [
            f for f in report.unresolved_blocking
            if f.rule.rule_id in _STRUCTURAL_RULES
        ]
        return [
            Criterion(
                "structurally sound",
                not structural,
                "no unresolved structural findings"
                if not structural
                else "; ".join(
                    f"{f.rule.rule_id} at {f.location.step_id or 'workflow'}"
                    for f in structural
                ),
            ),
            Criterion(
                "has steps", bool(draft.steps), f"{len(draft.steps)} step(s) declared"
            ),
        ]

    if target is WorkflowMaturity.ACCOUNTABLE:
        if report is None:
            return [Criterion("validation report", False, "no report supplied")]
        open_blocking = report.unresolved_blocking
        return [
            Criterion(
                "no unresolved blocking findings",
                not open_blocking,
                "clear"
                if not open_blocking
                else f"{len(open_blocking)} unresolved: "
                + ", ".join(sorted({f.rule.rule_id for f in open_blocking})),
            ),
            Criterion(
                "trigger stated", bool(draft.trigger.strip()), draft.trigger.strip()[:60]
            ),
            Criterion(
                "completion defined",
                bool(draft.claimed_outcome.strip()),
                draft.claimed_outcome.strip()[:60],
            ),
            Criterion(
                "every step owned",
                all(s.actor.strip() for s in draft.steps),
                "all steps name an actor"
                if all(s.actor.strip() for s in draft.steps)
                else "unowned: "
                + ", ".join(s.step_id for s in draft.steps if not s.actor.strip()),
            ),
        ]

    # Later gates need artifacts later phases produce. They are declared here so
    # the ladder is complete and a premature promotion is refused with a reason
    # rather than silently allowed.
    if target is WorkflowMaturity.COOPERATION_READY:
        if not assessments:
            return [
                Criterion(
                    "cooperation assessment for every step",
                    False,
                    "no assessments supplied; run assess_workflow() first",
                )
            ]
        assessed = {a.step_id for a in assessments}
        missing = [s.step_id for s in draft.steps if s.step_id not in assessed]
        # A step left NOT_READY_FOR_AUTOMATION is not a failure — a workflow may
        # legitimately keep work with people. But it must be a seen decision,
        # so it is surfaced here rather than discovered at export.
        not_ready = [
            a.step_id
            for a in assessments
            if a.effective_executor.value == "NOT_READY_FOR_AUTOMATION"
        ]
        return [
            Criterion(
                "every step assessed",
                not missing,
                "all steps have an assessment"
                if not missing
                else "unassessed: " + ", ".join(missing),
            ),
            Criterion(
                "no step left unclassifiable",
                not not_ready,
                "every step has a workable executor"
                if not not_ready
                else "still NOT_READY_FOR_AUTOMATION: " + ", ".join(not_ready),
            ),
        ]
    if target is WorkflowMaturity.COOPERATIVE_DESIGN_APPROVED:
        return [
            Criterion(
                "executor assignments approved by a human",
                False,
                "cooperative workflow builder is not implemented yet (phase 4/5)",
            )
        ]
    if target is WorkflowMaturity.RUNTIME_READY:
        return [
            Criterion(
                "exported to a runnable workflow brief",
                False,
                "export is not implemented yet (phase 5)",
            )
        ]

    # Beyond RUNTIME_READY this release does not gate: the evidence comes from
    # real runs and evaluation results the existing runtime already records.
    return [
        Criterion(
            "evidence from the existing runtime",
            False,
            "delegated to run and evaluation evidence plus a named reviewer; "
            "not gated by this release",
        )
    ]


def assess(
    draft: HumanWorkflowDraft,
    report: Optional[ValidationReport] = None,
    assessments: Sequence["CooperationAssessment"] = (),
) -> PromotionAssessment:
    """Show the evidence picture for this workflow's next step.

    Never raises and never promotes: it answers "could this move up, and if
    not, what is missing" so an operator sees the whole picture before trying.
    """
    target = next_maturity(draft.maturity)
    if target is None:
        return PromotionAssessment(
            workflow_id=draft.workflow_id, current=draft.maturity, target=None
        )
    enforced = PROMOTION_PATH.index(target) <= PROMOTION_PATH.index(LAST_ENFORCED)
    return PromotionAssessment(
        workflow_id=draft.workflow_id,
        current=draft.maturity,
        target=target,
        criteria=_criteria_for(target, draft, report, assessments),
        enforced=enforced,
    )


# ------------------------------------------------------------------ promoting


@dataclass
class PromotionOutcome:
    """What a granted promotion produced.

    Two steps on the ladder produce different things, which is why this exists
    rather than a single return type: reaching `MAPPED` advances the draft
    itself, while reaching `ACCOUNTABLE` produces a separate, immutable
    artifact and leaves the draft alone.
    """

    promotion_id: str
    workflow_id: str
    from_maturity: WorkflowMaturity
    to_maturity: WorkflowMaturity
    #: Set when the promotion produced an accountable artifact.
    artifact: Optional[AccountableWorkflow] = None
    #: Set when the promotion advanced the draft in place.
    draft: Optional[HumanWorkflowDraft] = None


def promote(
    ledger: RunLedger,
    draft: HumanWorkflowDraft,
    report: ValidationReport,
    promoted_by: str,
    *,
    owners: Optional[list[str]] = None,
    exception_policy: str = "",
    assessments: Sequence["CooperationAssessment"] = (),
) -> PromotionOutcome:
    """Promote a workflow one step, if — and only if — the evidence allows.

    Records the decision either way: a refusal is appended to the audit trail
    before the exception is raised, so the history shows what was attempted and
    why it was declined.

    Reaching `ACCOUNTABLE` produces an `AccountableWorkflow` artifact and leaves
    the source draft untouched. Steps are carried across unchanged — promotion
    resolves accountability, it does not reshape the work. Reaching `MAPPED`
    advances the draft's own maturity; that change is visible in the append-only
    promotion trail, together with the report it was based on, so nothing moves
    invisibly.

    Raises PromotionRefusedError when criteria are unmet, when the step is not
    the next one on the ladder, or when the target is beyond what this release
    gates.
    """
    if not promoted_by.strip():
        raise PromotionRefusedError(
            "promotion requires a named person; attribution is self-attested "
            "here, but it is never optional"
        )

    assessment = assess(draft, report, assessments)
    target = assessment.target
    report_id = ledger.save_validation_report(report)

    def refuse(reason: str) -> PromotionRefusedError:
        ledger.record_workflow_promotion(
            workflow_id=draft.workflow_id,
            from_maturity=draft.maturity.value,
            to_maturity=target.value if target else "",
            granted=False,
            promoted_by=promoted_by,
            rule_set_version=report.rule_set_version,
            schema_version=SCHEMA_VERSION,
            report_id=report_id,
            detail=reason,
        )
        return PromotionRefusedError(reason)

    if target is None:
        raise refuse(
            f"'{draft.workflow_id}' is already at {draft.maturity.value}, the "
            f"top of the ladder"
        )
    if not assessment.enforced:
        raise refuse(
            f"promotion to {target.value} is not gated by this release: its "
            f"criteria delegate to run and evaluation evidence plus a named "
            f"reviewer"
        )
    if not assessment.allowed:
        raise refuse(
            f"promotion {draft.maturity.value} -> {target.value} refused: "
            + "; ".join(f"{c.name} ({c.detail})" for c in assessment.unmet)
        )

    lineage = PromotionLineage(
        source_workflow_id=draft.workflow_id,
        source_version=draft.version,
        from_maturity=draft.maturity,
        to_maturity=target,
        promoted_by=promoted_by,
        rule_set_version=report.rule_set_version or RULE_SET_VERSION,
        schema_version=SCHEMA_VERSION,
    )

    # Reaching MAPPED advances the draft itself: it is the same working
    # document, now known to be structurally sound. No separate artifact is
    # invented for it — the append-only promotion row, citing the report, is
    # the traceable record of the move.
    if target is WorkflowMaturity.MAPPED:
        advanced = draft.model_copy(deep=True)
        advanced.maturity = target
        ledger.save_workflow_draft(advanced)
        promotion_id = ledger.record_workflow_promotion(
            workflow_id=draft.workflow_id,
            from_maturity=draft.maturity.value,
            to_maturity=target.value,
            granted=True,
            promoted_by=promoted_by,
            rule_set_version=lineage.rule_set_version,
            schema_version=SCHEMA_VERSION,
            report_id=report_id,
            detail="draft advanced to MAPPED; structure verified",
        )
        return PromotionOutcome(
            promotion_id=promotion_id,
            workflow_id=draft.workflow_id,
            from_maturity=draft.maturity,
            to_maturity=target,
            draft=advanced,
        )

    # Promoting the same version twice would collide with the artifact already
    # stored for it. That is a normal mistake, not an exceptional one, so it
    # refuses with instructions instead of surfacing a database error — and
    # refusing protects the first artifact, which an audit may already cite.
    if ledger.has_accountable_artifact(
        draft.workflow_id, draft.version, target.value
    ):
        raise refuse(
            f"version '{draft.version}' of '{draft.workflow_id}' has already "
            f"been promoted to {target.value}. Promotion never overwrites an "
            f"existing artifact — bump the draft version to promote revised work."
        )

    artifact = AccountableWorkflow(
        workflow_id=draft.workflow_id,
        name=draft.name,
        version=draft.version,
        maturity=target,
        purpose=draft.purpose,
        trigger=draft.trigger,
        owners=owners or _owners_from(draft),
        # Steps travel unchanged: promotion resolves accountability without
        # reshaping the work, and cooperation assessment reads these next.
        steps=list(draft.steps),
        gates=list(draft.gates),
        completion_contract=draft.claimed_outcome,
        exception_policy=exception_policy,
        accepted_risks=[
            f.acceptance for f in report.findings if f.acceptance is not None
        ],
        lineage=lineage,
    )

    # Artifact first, then the audit row: if anything fails between them the
    # trail shows no promotion, which is the safe direction to be wrong in.
    ledger.save_accountable_workflow(artifact)
    promotion_id = ledger.record_workflow_promotion(
        workflow_id=draft.workflow_id,
        from_maturity=draft.maturity.value,
        to_maturity=target.value,
        granted=True,
        promoted_by=promoted_by,
        rule_set_version=lineage.rule_set_version,
        schema_version=SCHEMA_VERSION,
        report_id=report_id,
        detail=f"produced accountable workflow version {artifact.version}",
    )
    return PromotionOutcome(
        promotion_id=promotion_id,
        workflow_id=draft.workflow_id,
        from_maturity=draft.maturity,
        to_maturity=target,
        artifact=artifact,
    )


def _owners_from(draft: HumanWorkflowDraft) -> list[str]:
    """Derive the owner list from who actually performs the work.

    Every step names an actor by the time a workflow is accountable — HW-003
    blocks otherwise — so the actors are the owners unless a caller states
    otherwise.
    """
    owners = sorted({s.actor.strip() for s in draft.steps if s.actor.strip()})
    return owners or [draft.name]
