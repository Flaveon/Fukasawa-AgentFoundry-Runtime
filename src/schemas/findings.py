# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Validation finding contracts — what is wrong, where, and what to do.

A ``WorkflowFinding`` is one specific defect in one specific place. The rules
that produce findings live in ``src/governance/workflow_rules.py``; this
module defines only the shape of the answer, so that findings are typed data
rather than a list of sentences nobody can act on programmatically.

Four properties make a finding useful, and all four are required by the
schema rather than left to a rule author's discretion:

* **location** — which workflow, which step, which field. "Something is
  missing somewhere" is not a finding.
* **rule reference with version** — findings and risk acceptances outlive the
  rules that produced them, so the rule version is recorded permanently.
* **remediation** — what to actually do about it.
* **blocking status** — whether this stops promotion.

The most important definition in this module: **"blocking" means blocking
promotion to ACCOUNTABLE. It never means blocking capture, save, or reload.**
An observed workflow is allowed to be a mess — recording it honestly is the
first stage of the lifecycle, and a validator that refused to save an
incomplete draft would defeat the product's premise. Findings gate the
promotion, not the truth.

One defect per finding. A rule that bundles several unrelated problems into a
single message makes the report unactionable and is a defect in the rule.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

#: Shared model config: reject unknown fields so typos surface loudly.
STRICT = ConfigDict(extra="forbid")

#: Current schema version for the contracts in this module (ADR-002).
SCHEMA_VERSION = "1"

#: Version of the rule set shipped with this release. Persisted on findings
#: and acceptances so an audit can tell which logic produced them.
RULE_SET_VERSION = "1"


class Severity(str, Enum):
    """How serious a finding is.

    Severity is a description; ``blocking`` is a policy. They are separate
    fields because a rule author may want a loud warning that nonetheless
    does not stop promotion (the heuristic rules are exactly this case).

    ERROR   — an accountability or structural defect.
    WARNING — a risk or clarity problem worth a human's attention.
    INFO    — an observation recorded for context, never a defect.
    """

    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


class FindingType(str, Enum):
    """Which dimension of workflow quality a finding belongs to.

    These are the five dimensions the release validates (mission §1):
    structure, accountability, information requirements, reasoning load, and
    resilience. Grouping findings this way lets a report tell an operator
    *what kind* of trouble they are in, not just how much.
    """

    STRUCTURE = "STRUCTURE"
    ACCOUNTABILITY = "ACCOUNTABILITY"
    INFORMATION = "INFORMATION"
    REASONING_LOAD = "REASONING_LOAD"
    RESILIENCE = "RESILIENCE"


class RuleRef(BaseModel):
    """Which rule produced a finding, at which version."""

    model_config = STRICT

    rule_id: str = Field(
        pattern=r"^HW-\d{3}$",
        description=(
            "Stable rule identifier, e.g. 'HW-004'. Rule ids are persisted "
            "on findings forever and are never renumbered."
        ),
    )
    rule_version: str = Field(
        default=RULE_SET_VERSION,
        description="Version of the rule's detection logic when it fired.",
    )


class FindingLocation(BaseModel):
    """Exactly where in the workflow the problem is.

    A finding without a location cannot be fixed by anyone but its author,
    which is why every field a rule can populate is offered here.
    """

    model_config = STRICT

    workflow_id: str = Field(description="Workflow the finding belongs to.")
    step_id: str = Field(
        default="",
        description="Step involved, when the finding is step-specific. Empty for workflow-level findings.",
    )
    gate_id: str = Field(
        default="", description="Gate involved, when the finding concerns an approval gate."
    )
    field: str = Field(
        default="",
        description="Field or attribute at fault, e.g. 'decision_authority'.",
    )
    detail: str = Field(
        default="",
        description=(
            "The offending value or reference, quoted for context — e.g. the "
            "dangling step id, or the ambiguous phrase that was matched."
        ),
    )


class RiskAcceptance(BaseModel):
    """A human consciously accepting a non-blocking finding.

    Three fields are mandatory by design — actor, timestamp, rationale — so
    that an accepted risk is a decision on the record rather than a silently
    dismissed warning.

    **Attribution is self-attested.** This runtime has no authentication, so
    ``accepted_by`` is a name someone typed. That is adequate for a single
    trusted local operator and insufficient as multi-party non-repudiation;
    the limitation is documented rather than hidden. The upgrade path is to
    sign acceptances with the operator's existing Ed25519 identity
    (``src/security/signing.py``), which is backlogged, not shipped here.
    """

    model_config = STRICT

    finding_id: str = Field(description="The finding being accepted.")
    rule: RuleRef = Field(
        description="Rule and version that produced the accepted finding."
    )
    accepted_by: str = Field(
        min_length=1,
        description="Who accepted the risk (self-attested — see the class docstring).",
    )
    accepted_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the risk was accepted (UTC).",
    )
    rationale: str = Field(
        min_length=1,
        description=(
            "Why this risk is acceptable. Required and non-empty — an "
            "acceptance without a reason is not a decision, it is a shrug."
        ),
    )


class WorkflowFinding(BaseModel):
    """One specific defect, in one specific place, with one remediation."""

    model_config = STRICT

    schema_version: str = Field(
        default=SCHEMA_VERSION,
        description="Contract version this finding was written against (ADR-002).",
    )
    finding_id: str = Field(
        description="Unique id for this finding within its report."
    )
    rule: RuleRef = Field(description="Which rule fired, at which version.")
    finding_type: FindingType = Field(
        description="Which dimension of workflow quality this concerns."
    )
    severity: Severity = Field(description="How serious the finding is.")
    blocking: bool = Field(
        description=(
            "Whether this finding blocks promotion to ACCOUNTABLE. It never "
            "blocks capture, save, or reload — see the module docstring."
        )
    )
    message: str = Field(
        min_length=1,
        description=(
            "Deterministic description of the defect. The same workflow must "
            "always produce the same message — no timestamps, no random ids, "
            "no model output."
        ),
    )
    location: FindingLocation = Field(description="Exactly where the problem is.")
    remediation: str = Field(
        min_length=1,
        description="What to do about it, concretely enough to act on.",
    )
    acceptance: Optional[RiskAcceptance] = Field(
        default=None,
        description=(
            "Set when a human has accepted this finding as a residual risk. "
            "Only non-blocking findings may be accepted; the promotion "
            "service enforces that."
        ),
    )

    @property
    def accepted(self) -> bool:
        """Whether a human has consciously accepted this finding."""
        return self.acceptance is not None

    @property
    def blocks_promotion(self) -> bool:
        """Whether this finding currently stands in the way of promotion.

        A blocking finding blocks until it is fixed. Accepting a blocking
        finding is not permitted, so acceptance only clears non-blocking ones
        — which is why this is ``blocking and not accepted`` rather than just
        ``blocking``.
        """
        return self.blocking and not self.accepted


class ValidationReport(BaseModel):
    """The complete result of validating one workflow at one point in time.

    Persisted and exported (``validation-report.json``) so a promotion
    decision can cite the exact evidence it was made on, including which rule
    set version produced it.
    """

    model_config = STRICT

    schema_version: str = Field(
        default=SCHEMA_VERSION,
        description="Contract version this report was written against (ADR-002).",
    )
    workflow_id: str = Field(description="Workflow that was validated.")
    workflow_version: str = Field(
        default="", description="Version of the workflow artifact validated."
    )
    rule_set_version: str = Field(
        default=RULE_SET_VERSION,
        description="Version of the rule set that produced these findings.",
    )
    evaluated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When validation ran (UTC).",
    )
    findings: list[WorkflowFinding] = Field(
        default_factory=list,
        description=(
            "Every finding, in deterministic order: rule id, then step id, "
            "then finding id. A clean workflow reports an empty list."
        ),
    )

    @property
    def blocking_findings(self) -> list[WorkflowFinding]:
        """Every finding whose policy is blocking, accepted or not."""
        return [f for f in self.findings if f.blocking]

    @property
    def unresolved_blocking(self) -> list[WorkflowFinding]:
        """Blocking findings still standing in the way of promotion."""
        return [f for f in self.findings if f.blocks_promotion]

    @property
    def promotion_ready(self) -> bool:
        """Whether promotion is permitted on the evidence in this report.

        True when no blocking finding remains unresolved. Non-blocking
        findings never prevent promotion, whether accepted or not — accepting
        them records a decision, it does not unlock anything.
        """
        return not self.unresolved_blocking

    def by_severity(self, severity: Severity) -> list[WorkflowFinding]:
        """Every finding at the given severity, in report order."""
        return [f for f in self.findings if f.severity is severity]

    def for_step(self, step_id: str) -> list[WorkflowFinding]:
        """Every finding anchored to the given step, in report order."""
        return [f for f in self.findings if f.location.step_id == step_id]
