# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Deterministic validator for observed human workflows.

Sixteen rules, ``HW-001`` through ``HW-016``, each answering one question about
one place in a workflow. A rule is a plain Python function in a registry — no
DSL, no plugin loader, no model call. The same workflow always produces the
same findings, in the same order, with the same messages (ADR-003).

**What "blocking" means here.** A blocking finding blocks *promotion to
ACCOUNTABLE*. It never blocks capture, save, or reload. An observed workflow is
allowed to be a mess — recording it honestly is the first stage of the
lifecycle, and a validator that refused to save an incomplete draft would
defeat the product's premise. Fourteen rules block promotion; two
(``HW-013``, ``HW-014``) are the heuristic pair and deliberately do not,
because they carry real false-positive risk.

**One defect per finding.** A rule may emit several findings — a workflow with
four unowned steps gets four ``HW-003`` findings, each locating its own step —
but a single finding never bundles unrelated problems into one message.

Two things every rule author must preserve:

* **Locate the defect.** Every finding carries workflow, step or gate, and the
  field at fault. "Something is missing somewhere" is not actionable.
* **Avoid the obvious false positive.** Several rules are deliberately narrower
  than their title suggests — ``HW-004`` only demands decision authority where
  a decision is actually made, for instance. Where a rule is narrowed, the
  reason is stated in its docstring, because a rule nobody can predict is a
  rule operators learn to ignore.
"""

import re
from dataclasses import dataclass, field as dataclass_field
from typing import Callable, Optional

from src.schemas.findings import (
    FindingLocation,
    FindingType,
    RULE_SET_VERSION,
    RuleRef,
    Severity,
    ValidationReport,
    WorkflowFinding,
)
from src.schemas.human_workflow import (
    ApprovalGate,
    HumanWorkflowDraft,
    RiskLevel,
    Reversibility,
    WorkflowStep,
)

# --------------------------------------------------------------- text helpers
#
# These make "undefined" and "ambiguous" mean something precise and
# predictable. They are deliberately small and literal: an operator should be
# able to read this list and know exactly what the validator will say.

#: Values that are technically filled in but say nothing.
PLACEHOLDERS = frozenset(
    {"tbd", "tba", "todo", "unknown", "unclear", "n/a", "na", "none", "?", "??", "???", "-", "--"}
)

#: Owner strings that name no one in particular.
AMBIGUOUS_OWNERS = frozenset(
    {
        "someone", "somebody", "anyone", "whoever", "whoever is available",
        "the team", "team", "everyone", "it depends", "depends", "varies",
        "as needed", "tbd", "shared",
    }
)

#: Words describing a *perception* rather than a state. These are never
#: criteria: "done when it looks fine" states no more than "done when it feels
#: done", so an accompanying "when" does not rescue them.
PERCEPTION_TERMS = frozenset(
    {
        "feels", "seems", "looks", "reads as", "good", "fine", "ok", "okay",
        "appropriate", "acceptable", "polished", "clean", "high quality",
        "quality", "as needed", "when appropriate",
    }
)

#: Words naming a *state* that can be made precise by an accompanying
#: criterion. "approved when at least one reviewer signed it" is fine; bare
#: "approved" is not.
STATE_TERMS = frozenset(
    {"ready", "complete", "completed", "approved", "done", "sufficient"}
)

#: Every term the rule looks for, for documentation and messages.
AMBIGUOUS_TERMS = PERCEPTION_TERMS | STATE_TERMS

#: Signals that a criterion is actually stated — presence of any of these
#: means the text is doing more than gesturing, so ambiguity is not reported.
CRITERION_SIGNALS = frozenset(
    {
        "when", "if", "at least", "no more than", "matches", "equals", "each",
        "every", "all ", "verified", "signed", "contains", "exists", "passes",
        "checklist", "criteria", "greater", "less than", "under", "within",
        "percent", "%", ">=", "<=", "confirmed", "reviewed by", "approved by",
    }
)

#: Phrases that mean the process lives in a person's memory.
MEMORY_PHRASES = (
    "in the operator's head", "in their head", "in his head", "in her head",
    "from memory", "remembers", "remember to", "just knows", "tribal knowledge",
    "nobody wrote", "not written down", "undocumented", "everyone knows",
)

#: Words carrying no matching signal when comparing failure-mode text.
_STOPWORDS = frozenset(
    {
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
        "of", "to", "in", "into", "on", "at", "for", "with", "and", "or", "but",
        "it", "its", "this", "that", "these", "those", "as", "by", "from",
        "out", "up", "own", "not", "no", "so", "then", "than", "there", "here",
        "turns", "becomes", "become", "goes", "gets", "actually", "usually",
        "sometimes", "really", "very", "own", "when", "if", "does", "do",
    }
)


def _undefined(text: str) -> bool:
    """True when a field is empty or filled with a placeholder that says nothing."""
    stripped = text.strip().lower().rstrip(".")
    return not stripped or stripped in PLACEHOLDERS


def _ambiguous_owner(text: str) -> bool:
    """True when an owner string names no one in particular."""
    return text.strip().lower().rstrip(".") in AMBIGUOUS_OWNERS


def _has_criterion(text: str) -> bool:
    """True when text states something checkable rather than gesturing at it."""
    low = text.lower()
    return any(sig in low for sig in CRITERION_SIGNALS) or any(ch.isdigit() for ch in low)


def _ambiguous_terms_in(text: str) -> list[str]:
    """Ambiguous terms that survive the criterion check, sorted deterministically.

    Perception words always count: no amount of surrounding grammar turns
    "looks fine" into something checkable. State words count only when the text
    offers no criterion alongside them, which is what keeps "approved when at
    least one reviewer has signed it" out of the report.
    """
    low = text.lower()
    present = lambda terms: {t for t in terms if re.search(rf"\b{re.escape(t)}", low)}
    flagged = present(PERCEPTION_TERMS)
    if not _has_criterion(text):
        flagged |= present(STATE_TERMS)
    return sorted(flagged)


def _content_words(text: str) -> set[str]:
    """Meaning-carrying words in text, for comparing two failure descriptions."""
    words = re.findall(r"[a-z]+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def _describes_same_failure(observed: str, declared: str) -> bool:
    """Whether a declared exception path plausibly covers an observed failure.

    Compares meaning-carrying words and asks whether at least half of the
    observed failure's vocabulary appears in the declared one. Exact string
    matching would be useless here — people never restate a failure in the
    same words twice — and anything cleverer would stop being predictable.
    Half is the documented threshold; a rule operators cannot predict is a
    rule they learn to ignore.
    """
    observed_words = _content_words(observed)
    if not observed_words:
        return False
    overlap = observed_words & _content_words(declared)
    return len(overlap) / len(observed_words) >= 0.5


# ------------------------------------------------------------------- indexing


@dataclass
class WorkflowIndex:
    """Precomputed structure shared by every rule, so no rule walks twice."""

    draft: HumanWorkflowDraft
    step_ids: set[str] = dataclass_field(default_factory=set)
    reachable: set[str] = dataclass_field(default_factory=set)
    gates_by_step: dict[str, list[ApprovalGate]] = dataclass_field(default_factory=dict)

    @classmethod
    def build(cls, draft: HumanWorkflowDraft) -> "WorkflowIndex":
        """Index a draft: known ids, reachability from the entry step, gates."""
        idx = cls(draft=draft, step_ids=draft.step_ids())
        for gate in draft.gates:
            idx.gates_by_step.setdefault(gate.at_step, []).append(gate)
        idx.reachable = idx._reachable_from_entry()
        return idx

    def _reachable_from_entry(self) -> set[str]:
        """Steps reachable from the entry step by any declared route.

        Exception paths and gate approve-targets count as routes: a step you
        can only arrive at by way of a failure is still reachable.
        """
        entry = self.draft.entry_step
        if entry is None:
            return set()
        seen: set[str] = set()
        frontier = [entry.step_id]
        while frontier:
            current = frontier.pop()
            if current in seen or current not in self.step_ids:
                continue
            seen.add(current)
            step = self.draft.step(current)
            frontier.extend(step.next_steps)
            frontier.extend(e.next_step for e in step.exception_paths if e.next_step)
            for gate in self.gates_by_step.get(current, []):
                if gate.on_approve:
                    frontier.append(gate.on_approve)
        return seen

    def terminal_steps(self) -> list[WorkflowStep]:
        """Reachable steps with no outgoing route."""
        return [
            s for s in self.draft.steps
            if s.step_id in self.reachable and not s.next_steps
        ]

    def actor_of(self, step_id: str) -> str:
        """The actor for a step id, or empty when unknown."""
        return self.draft.step(step_id).actor if step_id in self.step_ids else ""


# --------------------------------------------------------------------- rules


@dataclass(frozen=True)
class Rule:
    """One deterministic check, with everything an operator needs to act on it."""

    rule_id: str
    title: str
    description: str
    finding_type: FindingType
    severity: Severity
    blocking: bool
    remediation: str
    detect: Callable[[WorkflowIndex], list[WorkflowFinding]]
    version: str = RULE_SET_VERSION


def _make_finding(
    rule: Rule,
    workflow_id: str,
    message: str,
    *,
    step_id: str = "",
    gate_id: str = "",
    field: str = "",
    detail: str = "",
    discriminator: str = "",
    remediation: str = "",
) -> WorkflowFinding:
    """Build a finding for a rule, with a deterministic id that locates it.

    The id is derived from the rule and the place it fired rather than being a
    counter or a uuid, so the same workflow always yields the same ids —
    findings are persisted and referenced by risk acceptances, so a stable id
    is a correctness requirement, not a nicety.
    """
    parts = [p for p in (step_id, gate_id, field, discriminator) if p]
    finding_id = f"{rule.rule_id}:{'/'.join(parts) if parts else 'workflow'}"
    return WorkflowFinding(
        finding_id=finding_id,
        rule=RuleRef(rule_id=rule.rule_id, rule_version=rule.version),
        finding_type=rule.finding_type,
        severity=rule.severity,
        blocking=rule.blocking,
        message=message,
        location=FindingLocation(
            workflow_id=workflow_id, step_id=step_id, gate_id=gate_id,
            field=field, detail=detail,
        ),
        remediation=remediation or rule.remediation,
    )


# HW-001 ---------------------------------------------------------------------


def _detect_undefined_trigger(idx: WorkflowIndex) -> list[WorkflowFinding]:
    """A workflow nobody can say how it starts cannot be run or handed over."""
    d = idx.draft
    if _undefined(d.trigger):
        return [
            _make_finding(
                HW_001, d.workflow_id,
                "the workflow does not say what starts it",
                field="trigger", detail=d.trigger.strip(),
            )
        ]
    return []


# HW-002 ---------------------------------------------------------------------


def _detect_undefined_outcome(idx: WorkflowIndex) -> list[WorkflowFinding]:
    """Two distinct ways completion can be undefined; each gets its own finding."""
    d = idx.draft
    findings: list[WorkflowFinding] = []
    if _undefined(d.claimed_outcome):
        findings.append(
            _make_finding(
                HW_002, d.workflow_id,
                "the workflow does not say what it is supposed to achieve",
                field="claimed_outcome", detail=d.claimed_outcome.strip(),
                discriminator="outcome",
            )
        )
    if d.steps and not idx.terminal_steps():
        findings.append(
            _make_finding(
                HW_002, d.workflow_id,
                "no reachable step ends the workflow — every reachable step "
                "leads somewhere else, so the work never terminates",
                field="steps", discriminator="terminal",
                remediation=(
                    "Give the final step an empty next_steps list, or add the "
                    "step that completes the work."
                ),
            )
        )
    return findings


# HW-003 ---------------------------------------------------------------------


def _detect_missing_step_owner(idx: WorkflowIndex) -> list[WorkflowFinding]:
    """Work nobody owns is work that stalls silently."""
    return [
        _make_finding(
            HW_003, idx.draft.workflow_id,
            f"step '{s.step_id}' has no actor — nobody is named as performing it",
            step_id=s.step_id, field="actor", detail=s.actor.strip(),
        )
        for s in idx.draft.steps
        if _undefined(s.actor)
    ]


# HW-004 ---------------------------------------------------------------------


def _decision_is_made_here(idx: WorkflowIndex, step: WorkflowStep) -> bool:
    """Whether this step actually involves a decision someone must own.

    Deliberately narrower than "every step": a purely linear step that always
    does the same next thing decides nothing, and demanding an authority for it
    would produce noise on every well-formed workflow. A decision exists when
    the step branches, when a gate guards it, or when its effect is
    irreversible or high-risk — someone must own an act that cannot be undone.
    """
    return (
        len(step.next_steps) > 1
        or bool(idx.gates_by_step.get(step.step_id))
        or step.characteristics.reversibility is Reversibility.IRREVERSIBLE
        or step.characteristics.risk is RiskLevel.HIGH
    )


def _detect_decision_authority(idx: WorkflowIndex) -> list[WorkflowFinding]:
    """Unclear decision ownership is the most common cause of workflow stalls."""
    findings: list[WorkflowFinding] = []
    for s in idx.draft.steps:
        if not _decision_is_made_here(idx, s):
            continue
        if _undefined(s.decision_authority):
            findings.append(
                _make_finding(
                    HW_004, idx.draft.workflow_id,
                    f"step '{s.step_id}' makes a decision but names no decision "
                    f"authority",
                    step_id=s.step_id, field="decision_authority",
                    detail=s.decision_authority.strip(),
                )
            )
        elif _ambiguous_owner(s.decision_authority):
            findings.append(
                _make_finding(
                    HW_004, idx.draft.workflow_id,
                    f"step '{s.step_id}' names an ambiguous decision authority "
                    f"('{s.decision_authority.strip()}') — it identifies no "
                    f"particular person or role",
                    step_id=s.step_id, field="decision_authority",
                    detail=s.decision_authority.strip(), discriminator="ambiguous",
                )
            )
    for gate in idx.draft.gates:
        if _undefined(gate.approver):
            findings.append(
                _make_finding(
                    HW_004, idx.draft.workflow_id,
                    f"gate '{gate.gate_id}' has no approver",
                    gate_id=gate.gate_id, field="approver",
                )
            )
        elif _ambiguous_owner(gate.approver):
            findings.append(
                _make_finding(
                    HW_004, idx.draft.workflow_id,
                    f"gate '{gate.gate_id}' names an ambiguous approver "
                    f"('{gate.approver.strip()}')",
                    gate_id=gate.gate_id, field="approver",
                    detail=gate.approver.strip(), discriminator="ambiguous",
                )
            )
    return findings


# HW-005 ---------------------------------------------------------------------


def _detect_dangling_reference(idx: WorkflowIndex) -> list[WorkflowFinding]:
    """A route to a step that does not exist is a route to nowhere.

    Checks the three places that are documented as holding a step id. A gate's
    ``on_reject`` is excluded on purpose: it may legitimately hold a stated
    action rather than a step id, so HW-015 judges it instead.
    """
    findings: list[WorkflowFinding] = []
    d = idx.draft
    for s in d.steps:
        for target in s.next_steps:
            if target not in idx.step_ids:
                findings.append(
                    _make_finding(
                        HW_005, d.workflow_id,
                        f"step '{s.step_id}' points to '{target}', which is not "
                        f"a declared step",
                        step_id=s.step_id, field="next_steps", detail=target,
                        discriminator=target,
                    )
                )
        for exc in s.exception_paths:
            if exc.next_step and exc.next_step not in idx.step_ids:
                findings.append(
                    _make_finding(
                        HW_005, d.workflow_id,
                        f"exception path on step '{s.step_id}' points to "
                        f"'{exc.next_step}', which is not a declared step",
                        step_id=s.step_id, field="exception_paths.next_step",
                        detail=exc.next_step, discriminator=exc.next_step,
                    )
                )
    for gate in d.gates:
        if gate.at_step not in idx.step_ids:
            findings.append(
                _make_finding(
                    HW_005, d.workflow_id,
                    f"gate '{gate.gate_id}' guards '{gate.at_step}', which is "
                    f"not a declared step",
                    gate_id=gate.gate_id, field="at_step", detail=gate.at_step,
                )
            )
        if gate.on_approve and gate.on_approve not in idx.step_ids:
            findings.append(
                _make_finding(
                    HW_005, d.workflow_id,
                    f"gate '{gate.gate_id}' approves onward to "
                    f"'{gate.on_approve}', which is not a declared step",
                    gate_id=gate.gate_id, field="on_approve",
                    detail=gate.on_approve, discriminator=gate.on_approve,
                )
            )
    return findings


# HW-006 ---------------------------------------------------------------------


def _detect_unreachable_step(idx: WorkflowIndex) -> list[WorkflowFinding]:
    """A step nothing leads to happens only by luck or memory."""
    return [
        _make_finding(
            HW_006, idx.draft.workflow_id,
            f"step '{s.step_id}' cannot be reached from the entry step — "
            f"nothing routes to it",
            step_id=s.step_id, field="next_steps",
        )
        for s in idx.draft.steps
        if s.step_id not in idx.reachable
    ]


# HW-007 ---------------------------------------------------------------------


def _detect_dead_end(idx: WorkflowIndex) -> list[WorkflowFinding]:
    """A place work arrives, produces nothing, and cannot leave.

    Narrowed deliberately: a terminal step that produces an output is a
    legitimate ending, not a dead end. What makes an ending accidental is
    arriving somewhere that yields nothing and goes nowhere. Exception paths
    that neither handle nor route are the same defect in a different place.
    """
    findings: list[WorkflowFinding] = []
    d = idx.draft
    for s in d.steps:
        if s.step_id in idx.reachable and not s.next_steps and not s.outputs:
            findings.append(
                _make_finding(
                    HW_007, d.workflow_id,
                    f"step '{s.step_id}' is a dead end — it produces no output "
                    f"and leads to no next step",
                    step_id=s.step_id, field="next_steps",
                )
            )
        for exc in s.exception_paths:
            if not exc.next_step and _undefined(exc.handling):
                findings.append(
                    _make_finding(
                        HW_007, d.workflow_id,
                        f"failure '{exc.failure_mode.strip()}' on step "
                        f"'{s.step_id}' has no handling and no next step — work "
                        f"stops there with nothing done",
                        step_id=s.step_id, field="exception_paths",
                        detail=exc.failure_mode.strip(),
                        discriminator=exc.failure_mode.strip()[:40],
                        remediation=(
                            "Say what is done when this failure occurs, and "
                            "which step work resumes at."
                        ),
                    )
                )
    return findings


# HW-008 ---------------------------------------------------------------------


def _detect_implicit_handoff(idx: WorkflowIndex) -> list[WorkflowFinding]:
    """Work crossing between people with nothing verifiable handed over.

    Fires only for a genuine cross-actor transition where the upstream step
    produces no output carrying both an artifact type and an evidence
    requirement. Same-actor transitions are not handoffs, and an upstream step
    that produces a real, verifiable artifact has handed something over.
    """
    findings: list[WorkflowFinding] = []
    d = idx.draft
    has_verifiable_output = lambda s: any(
        not _undefined(o.artifact_type) and not _undefined(o.evidence_requirement)
        for o in s.outputs
    )
    for s in d.steps:
        if has_verifiable_output(s):
            continue
        for target in s.next_steps:
            if target not in idx.step_ids:
                continue  # HW-005 owns dangling references
            downstream_actor = idx.actor_of(target)
            if _undefined(s.actor) or _undefined(downstream_actor):
                continue  # HW-003 owns missing actors
            if s.actor.strip().lower() == downstream_actor.strip().lower():
                continue
            findings.append(
                _make_finding(
                    HW_008, d.workflow_id,
                    f"work passes from '{s.actor.strip()}' at step "
                    f"'{s.step_id}' to '{downstream_actor.strip()}' at step "
                    f"'{target}' with no verifiable artifact handed over",
                    step_id=s.step_id, field="outputs", detail=target,
                    discriminator=target,
                )
            )
    return findings


# HW-009 ---------------------------------------------------------------------


def _detect_missing_input_source(idx: WorkflowIndex) -> list[WorkflowFinding]:
    """A step that needs something but cannot say where it comes from."""
    return [
        _make_finding(
            HW_009, idx.draft.workflow_id,
            f"required input '{i.name}' on step '{s.step_id}' has no source",
            step_id=s.step_id, field="inputs.source", detail=i.name,
            discriminator=i.name,
        )
        for s in idx.draft.steps
        for i in s.inputs
        if i.required and _undefined(i.source)
    ]


# HW-010 ---------------------------------------------------------------------


def _detect_unverifiable_output(idx: WorkflowIndex) -> list[WorkflowFinding]:
    """An output nobody can point at or verify. Two defects, two findings."""
    findings: list[WorkflowFinding] = []
    for s in idx.draft.steps:
        for o in s.outputs:
            if _undefined(o.artifact_type):
                findings.append(
                    _make_finding(
                        HW_010, idx.draft.workflow_id,
                        f"output '{o.name}' on step '{s.step_id}' has no "
                        f"artifact type — there is no saying what is produced",
                        step_id=s.step_id, field="outputs.artifact_type",
                        detail=o.name, discriminator=f"{o.name}/type",
                        remediation="State what kind of thing this output is.",
                    )
                )
            if _undefined(o.evidence_requirement):
                findings.append(
                    _make_finding(
                        HW_010, idx.draft.workflow_id,
                        f"output '{o.name}' on step '{s.step_id}' has no "
                        f"evidence requirement — nothing proves it was produced",
                        step_id=s.step_id, field="outputs.evidence_requirement",
                        detail=o.name, discriminator=f"{o.name}/evidence",
                        remediation=(
                            "State what must exist to prove this output was "
                            "really produced."
                        ),
                    )
                )
    return findings


# HW-011 ---------------------------------------------------------------------


def _detect_unhandled_failure_mode(idx: WorkflowIndex) -> list[WorkflowFinding]:
    """A failure everyone has seen, that the workflow has no answer for."""
    d = idx.draft
    declared = [e.failure_mode for s in d.steps for e in s.exception_paths]
    findings: list[WorkflowFinding] = []
    for observed in d.observed_exceptions:
        if any(_describes_same_failure(observed, dec) for dec in declared):
            continue
        findings.append(
            _make_finding(
                HW_011, d.workflow_id,
                f"observed failure '{observed.strip()}' has no exception path "
                f"on any step — it happens in practice and the workflow has no "
                f"answer for it",
                field="observed_exceptions", detail=observed.strip(),
                discriminator=observed.strip()[:40],
            )
        )
    return findings


# HW-012 ---------------------------------------------------------------------


def _detect_unowned_exception(idx: WorkflowIndex) -> list[WorkflowFinding]:
    """A failure with a plan but no owner is the plan nobody executes."""
    findings: list[WorkflowFinding] = []
    for s in idx.draft.steps:
        for exc in s.exception_paths:
            if _undefined(exc.owner):
                findings.append(
                    _make_finding(
                        HW_012, idx.draft.workflow_id,
                        f"failure '{exc.failure_mode.strip()}' on step "
                        f"'{s.step_id}' has no owner",
                        step_id=s.step_id, field="exception_paths.owner",
                        detail=exc.failure_mode.strip(),
                        discriminator=exc.failure_mode.strip()[:40],
                    )
                )
            elif _ambiguous_owner(exc.owner):
                findings.append(
                    _make_finding(
                        HW_012, idx.draft.workflow_id,
                        f"failure '{exc.failure_mode.strip()}' on step "
                        f"'{s.step_id}' names an ambiguous owner "
                        f"('{exc.owner.strip()}')",
                        step_id=s.step_id, field="exception_paths.owner",
                        detail=exc.owner.strip(),
                        discriminator=f"{exc.failure_mode.strip()[:32]}/ambiguous",
                    )
                )
    return findings


# HW-013 ---------------------------------------------------------------------


def _detect_memory_dependency(idx: WorkflowIndex) -> list[WorkflowFinding]:
    """Knowledge that lives only in someone's head.

    Non-blocking on purpose. Recording an unwritten rule is an act of honesty
    and the whole point of stage one — flagging it makes the dependency visible
    without punishing the person who admitted it.
    """
    d = idx.draft
    findings = [
        _make_finding(
            HW_013, d.workflow_id,
            f"the workflow depends on an unwritten rule: '{rule.strip()}'",
            field="unwritten_rules", detail=rule.strip(),
            discriminator=rule.strip()[:40],
        )
        for rule in d.unwritten_rules
    ]
    for s in d.steps:
        for attr in ("description", "exit_condition", "notes"):
            text = getattr(s, attr)
            phrase = next((p for p in MEMORY_PHRASES if p in text.lower()), None)
            if phrase:
                findings.append(
                    _make_finding(
                        HW_013, d.workflow_id,
                        f"step '{s.step_id}' relies on knowledge held in "
                        f"memory ('{phrase}')",
                        step_id=s.step_id, field=attr, detail=phrase,
                        discriminator=f"{attr}/{phrase[:24]}",
                    )
                )
    return findings


# HW-014 ---------------------------------------------------------------------


def _detect_ambiguous_criteria(idx: WorkflowIndex) -> list[WorkflowFinding]:
    """States described by feel rather than criteria.

    Non-blocking: this is a keyword scan and the most false-positive-prone rule
    in the set. Text that states an actual criterion — a number, a "when", an
    "at least" — is left alone even when it also contains a soft word.
    """
    d = idx.draft
    findings: list[WorkflowFinding] = []

    def check(text: str, *, step_id: str = "", gate_id: str = "", field: str = "") -> None:
        # The criterion check lives inside _ambiguous_terms_in, because it
        # applies to state words only — perception words are never rescued by it.
        if _undefined(text):
            return
        terms = _ambiguous_terms_in(text)
        if not terms:
            return
        findings.append(
            _make_finding(
                HW_014, d.workflow_id,
                f"'{field}' describes a state as "
                f"{', '.join(repr(t) for t in terms)} without saying how it is "
                f"judged",
                step_id=step_id, gate_id=gate_id, field=field,
                detail=text.strip(), discriminator=terms[0],
            )
        )

    check(d.claimed_outcome, field="claimed_outcome")
    for s in d.steps:
        check(s.exit_condition, step_id=s.step_id, field="exit_condition")
    for gate in d.gates:
        if _undefined(gate.criteria):
            findings.append(
                _make_finding(
                    HW_014, d.workflow_id,
                    f"gate '{gate.gate_id}' states no criteria — the approver "
                    f"has nothing written to judge against",
                    gate_id=gate.gate_id, field="criteria",
                    discriminator="empty",
                )
            )
        else:
            check(gate.criteria, gate_id=gate.gate_id, field="criteria")
    return findings


# HW-015 ---------------------------------------------------------------------


def _detect_gate_without_next_action(idx: WorkflowIndex) -> list[WorkflowFinding]:
    """A checkpoint that can say no, with nothing saying what happens then.

    Mirrors a contract the runtime already enforces on blocked runs: a pause
    without a stated next action is abandonment, not a handoff.
    """
    return [
        _make_finding(
            HW_015, idx.draft.workflow_id,
            f"gate '{gate.gate_id}' has no rejection path — nothing says what "
            f"happens when the approver says no",
            gate_id=gate.gate_id, field="on_reject",
        )
        for gate in idx.draft.gates
        if _undefined(gate.on_reject)
    ]


# HW-016 ---------------------------------------------------------------------


def _detect_unsupported_completion(idx: WorkflowIndex) -> list[WorkflowFinding]:
    """A workflow that claims an outcome nothing in it can prove.

    Skipped when the outcome is undefined — that is HW-002's finding, and
    reporting both would be two findings for one root cause.
    """
    d = idx.draft
    if _undefined(d.claimed_outcome) or not d.steps:
        return []
    provable = any(
        not _undefined(o.evidence_requirement)
        for s in d.steps
        if s.step_id in idx.reachable
        for o in s.outputs
    )
    if provable:
        return []
    return [
        _make_finding(
            HW_016, d.workflow_id,
            "the workflow claims an outcome but no reachable step produces "
            "evidence that could prove it",
            field="claimed_outcome", detail=d.claimed_outcome.strip(),
        )
    ]


# ------------------------------------------------------------------- registry

HW_001 = Rule(
    rule_id="HW-001",
    title="Undefined workflow trigger",
    description="The workflow does not state what causes it to start.",
    finding_type=FindingType.STRUCTURE,
    severity=Severity.ERROR,
    blocking=True,
    remediation="State what event or condition starts this workflow.",
    detect=_detect_undefined_trigger,
)

HW_002 = Rule(
    rule_id="HW-002",
    title="Undefined claimed outcome or terminal completion",
    description=(
        "The workflow does not say what it achieves, or no reachable step ends it."
    ),
    finding_type=FindingType.STRUCTURE,
    severity=Severity.ERROR,
    blocking=True,
    remediation="State what the workflow achieves when it succeeds.",
    detect=_detect_undefined_outcome,
)

HW_003 = Rule(
    rule_id="HW-003",
    title="Missing step owner",
    description="A step does not name who performs it.",
    finding_type=FindingType.ACCOUNTABILITY,
    severity=Severity.ERROR,
    blocking=True,
    remediation="Name the person, role, or system that performs this step.",
    detect=_detect_missing_step_owner,
)

HW_004 = Rule(
    rule_id="HW-004",
    title="Missing or ambiguous decision authority",
    description=(
        "A step that branches, is gated, or has irreversible or high-risk "
        "effect does not name who decides — or names no one in particular."
    ),
    finding_type=FindingType.ACCOUNTABILITY,
    severity=Severity.ERROR,
    blocking=True,
    remediation="Name the specific person or role with authority to decide here.",
    detect=_detect_decision_authority,
)

HW_005 = Rule(
    rule_id="HW-005",
    title="Referenced next step does not exist",
    description="A route points to a step id that is not declared.",
    finding_type=FindingType.STRUCTURE,
    severity=Severity.ERROR,
    blocking=True,
    remediation="Add the missing step, or correct the reference to an existing one.",
    detect=_detect_dangling_reference,
)

HW_006 = Rule(
    rule_id="HW-006",
    title="Unreachable step",
    description="A declared step cannot be reached from the entry step.",
    finding_type=FindingType.STRUCTURE,
    severity=Severity.ERROR,
    blocking=True,
    remediation="Route to this step from where it really happens, or remove it.",
    detect=_detect_unreachable_step,
)

HW_007 = Rule(
    rule_id="HW-007",
    title="Accidental dead-end state",
    description=(
        "Work arrives somewhere that produces nothing and leads nowhere, or a "
        "failure has neither handling nor a next step."
    ),
    finding_type=FindingType.STRUCTURE,
    severity=Severity.ERROR,
    blocking=True,
    remediation=(
        "Say what this step produces, or route it onward to the step that follows."
    ),
    detect=_detect_dead_end,
)

HW_008 = Rule(
    rule_id="HW-008",
    title="Implicit or incomplete handoff",
    description=(
        "Work crosses from one actor to another with no verifiable artifact "
        "handed over."
    ),
    finding_type=FindingType.INFORMATION,
    severity=Severity.ERROR,
    blocking=True,
    remediation=(
        "Give the upstream step an output with an artifact type and an evidence "
        "requirement, so the receiver knows what they are getting."
    ),
    detect=_detect_implicit_handoff,
)

HW_009 = Rule(
    rule_id="HW-009",
    title="Missing required input source",
    description="A required input does not say where it comes from.",
    finding_type=FindingType.INFORMATION,
    severity=Severity.ERROR,
    blocking=True,
    remediation="Name the actor, system, or upstream step this input comes from.",
    detect=_detect_missing_input_source,
)

HW_010 = Rule(
    rule_id="HW-010",
    title="Output without artifact type or evidence requirement",
    description="An output cannot be identified or verified.",
    finding_type=FindingType.INFORMATION,
    severity=Severity.ERROR,
    blocking=True,
    remediation="State what kind of artifact this is and what proves it exists.",
    detect=_detect_unverifiable_output,
)

HW_011 = Rule(
    rule_id="HW-011",
    title="Missing exception path for a declared failure mode",
    description=(
        "A failure the workflow says happens in practice has no exception path."
    ),
    finding_type=FindingType.RESILIENCE,
    severity=Severity.ERROR,
    blocking=True,
    remediation=(
        "Add an exception path for this failure on the step where it occurs, "
        "with an owner and what is done."
    ),
    detect=_detect_unhandled_failure_mode,
)

HW_012 = Rule(
    rule_id="HW-012",
    title="Unowned exception",
    description="An exception path does not name who handles it.",
    finding_type=FindingType.RESILIENCE,
    severity=Severity.ERROR,
    blocking=True,
    remediation="Name the specific person or role who handles this failure.",
    detect=_detect_unowned_exception,
)

HW_013 = Rule(
    rule_id="HW-013",
    title="Human memory dependency or unwritten rule",
    description=(
        "The workflow depends on knowledge that exists only in someone's head."
    ),
    finding_type=FindingType.REASONING_LOAD,
    severity=Severity.WARNING,
    blocking=False,
    remediation=(
        "Write the rule into the step it governs, or accept it as a known "
        "residual risk with a rationale."
    ),
    detect=_detect_memory_dependency,
)

HW_014 = Rule(
    rule_id="HW-014",
    title="Ambiguous terms without criteria",
    description=(
        "A state is described by feel — 'ready', 'complete', 'approved' — with "
        "no criteria for judging it."
    ),
    finding_type=FindingType.INFORMATION,
    severity=Severity.WARNING,
    blocking=False,
    remediation=(
        "Replace the term with a checkable condition, or state the criteria "
        "used to judge it."
    ),
    detect=_detect_ambiguous_criteria,
)

HW_015 = Rule(
    rule_id="HW-015",
    title="Rejection or approval gate without a next action",
    description="A gate can reject, but nothing says what happens then.",
    finding_type=FindingType.RESILIENCE,
    severity=Severity.ERROR,
    blocking=True,
    remediation=(
        "State where work goes when this gate rejects — the step it returns to, "
        "or the action taken."
    ),
    detect=_detect_gate_without_next_action,
)

HW_016 = Rule(
    rule_id="HW-016",
    title="Unsupported completion claim",
    description=(
        "The workflow claims an outcome that no reachable step produces "
        "evidence for."
    ),
    finding_type=FindingType.ACCOUNTABILITY,
    severity=Severity.ERROR,
    blocking=True,
    remediation=(
        "Give the completing step an output whose evidence requirement proves "
        "the claimed outcome."
    ),
    detect=_detect_unsupported_completion,
)

#: Every rule, keyed by id. Ids map 1:1 to the release's declared rule set and
#: are never renumbered — they are persisted on findings and risk acceptances.
RULES: dict[str, Rule] = {
    r.rule_id: r
    for r in (
        HW_001, HW_002, HW_003, HW_004, HW_005, HW_006, HW_007, HW_008,
        HW_009, HW_010, HW_011, HW_012, HW_013, HW_014, HW_015, HW_016,
    )
}

#: Rules that block promotion to ACCOUNTABLE, for quick reference in docs/UI.
BLOCKING_RULE_IDS = frozenset(r.rule_id for r in RULES.values() if r.blocking)


def _sort_key(f: WorkflowFinding) -> tuple:
    """Deterministic report ordering: rule, then step, then gate, then field."""
    return (
        f.rule.rule_id,
        f.location.step_id,
        f.location.gate_id,
        f.location.field,
        f.finding_id,
    )


def validate_workflow(
    draft: HumanWorkflowDraft, rule_ids: Optional[list[str]] = None
) -> ValidationReport:
    """Run the rule set against a draft and return a deterministic report.

    Findings are sorted by rule, then location, so two runs over the same
    workflow produce byte-identical reports — which is what makes a report
    diffable and a promotion decision citable.

    Passing ``rule_ids`` restricts the run to those rules; it exists for
    testing and for explaining a single rule to an operator, not as a way to
    skip inconvenient checks during promotion.
    """
    index = WorkflowIndex.build(draft)
    selected = [RULES[rid] for rid in (rule_ids or sorted(RULES))]
    findings: list[WorkflowFinding] = []
    for rule in selected:
        findings.extend(rule.detect(index))
    findings.sort(key=_sort_key)
    return ValidationReport(
        workflow_id=draft.workflow_id,
        workflow_version=draft.version,
        rule_set_version=RULE_SET_VERSION,
        findings=findings,
    )
