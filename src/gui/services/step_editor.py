# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Step editing services — §16.3, the guided half of the guided step editor.

The editor's *guidance* is what makes it guided rather than a form, and it is
computed here rather than typed into the view, for one reason: every hint is
read out of the live rule registry (`src/governance/workflow_rules.RULES`).
A field's advice is the remediation text of the rule that fires on that field.
Change a rule's remediation and the editor's advice changes with it — there is
no second copy to forget.

This is not rule logic in the GUI (directive §6.3). Nothing here decides
whether a rule fires or what it means; it reads the registry the validator
owns and maps fields to it. The map itself — "HW-003 is about `actor`" — is a
presentation fact, and it is asserted by a test rather than trusted.

**Editing writes YAML back, and YAML comments do not survive.** ``ruamel`` is
the round-tripping loader that would preserve them, and adding a dependency is
forbidden for this release. Rather than silently discarding an operator's
annotations, ``write_step`` copies the file to ``<name>.yaml.bak`` first and
says so in its summary. The teaching comments in the skeleton are the ones
most likely to be lost, and they exist in `src/schemas/templates.py` anyway.

Three field kinds cross the service/view boundary as **text**, so the view
needs no dynamic widget arrays and every field round-trips through a plain
string:

* ``text``    — a single line or paragraph, as-is.
* ``lines``   — a list of strings, one per line.
* ``records`` — a list of objects, one per line, ``|``-separated in the column
  order the guidance states. Empty trailing columns may be omitted.
* ``choice``  — one of a fixed set of values, named in ``choices``.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from src.governance.workflow_rules import RULES, validate_workflow
from src.gui.services.workflow import (
    FindingView,
    Outcome,
    _finding_views,
    _ledger,
    _load_draft,
)
from src.runtime.ledger import DEFAULT_DB_PATH
from src.schemas.human_workflow import (
    DataSensitivity,
    Determinism,
    HumanWorkflowDraft,
    JudgmentLoad,
    Repeatability,
    Reversibility,
    RiskLevel,
    WorkflowStep,
)

#: Column separator for ``records`` fields. A pipe rather than a comma because
#: prose belongs in these columns — "escalate to the editor, then retry" has a
#: comma in it and no operator should have to think about quoting.
SEPARATOR = "|"


@dataclass
class FieldGuidance:
    """What one step field is for, and which rule cares about it.

    ``rule_id`` is empty for fields no rule fires on. That is not a gap: the
    editor still shows those fields, it simply has no rule to cite, and saying
    so is more honest than inventing advice.
    """

    name: str
    label: str
    kind: str
    hint: str
    rule_id: str = ""
    blocking: bool = False
    choices: list[str] = field(default_factory=list)
    #: Column names for a ``records`` field, in order. Empty otherwise.
    columns: list[str] = field(default_factory=list)


@dataclass
class StepView:
    """One step, flattened to editable text plus the findings against it."""

    step_id: str
    name: str
    values: dict[str, str] = field(default_factory=dict)
    findings: list[FindingView] = field(default_factory=list)


@dataclass
class StepResult(Outcome):
    """The editor's view of a draft: every step id, and one step open."""

    workflow_id: str = ""
    step_ids: list[str] = field(default_factory=list)
    step: Optional[StepView] = None
    #: Set by ``write_step`` when a backup was taken, so the view can say where.
    backup_path: str = ""


# ------------------------------------------------------------------- guidance


def _choices(enum_cls) -> list[str]:
    """Every value of a characteristics enum, UNKNOWN first."""
    return [m.value for m in enum_cls]


#: Field → the rule that fires on it. Presentation only; the rules themselves
#: live in the validator. Asserted against ``RULES`` by a test so a renumbered
#: or retired rule cannot leave a dangling citation here.
_FIELD_RULES = {
    "actor": "HW-003",
    "decision_authority": "HW-004",
    "next_steps": "HW-005",
    "exit_condition": "HW-014",
    "inputs": "HW-009",
    "outputs": "HW-010",
    "exception_paths": "HW-012",
}

#: The editable surface of a ``WorkflowStep``, in the order an observer
#: naturally answers them: what is it, who does it, what does it need, what
#: does it produce, where does it go, what can go wrong, and what is it like.
#: ``step_id`` is deliberately absent — it is referenced by ``next_steps``,
#: exception paths and gates, and renaming it from a form would silently break
#: those references. Change it in the YAML, where the consequences are visible.
_FIELDS: list[FieldGuidance] = [
    FieldGuidance("name", "Name", "text", "Short name for the step."),
    FieldGuidance(
        "description", "Description", "text", "What happens here, in plain language."
    ),
    FieldGuidance(
        "actor",
        "Actor",
        "text",
        "Who performs this step — a person, role, team, or system.",
    ),
    FieldGuidance("action", "Action", "text", "The work done, as a verb phrase."),
    FieldGuidance("trigger", "Trigger", "text", "What causes this step to begin."),
    FieldGuidance(
        "preconditions",
        "Preconditions",
        "lines",
        "What must already be true before this starts. One per line.",
    ),
    FieldGuidance(
        "inputs",
        "Inputs",
        "records",
        "What this step consumes. One per line.",
        columns=["name", "source", "required (yes/no)"],
    ),
    FieldGuidance(
        "outputs",
        "Outputs",
        "records",
        "What this step produces. One per line.",
        columns=["name", "artifact type", "evidence requirement"],
    ),
    FieldGuidance(
        "entry_condition",
        "Entry condition",
        "text",
        "How you know the step has properly begun.",
    ),
    FieldGuidance(
        "exit_condition",
        "Exit condition",
        "text",
        "How you know it is finished.",
    ),
    FieldGuidance(
        "decision_authority",
        "Decision authority",
        "text",
        "Who has authority to decide here.",
    ),
    FieldGuidance(
        "next_steps",
        "Next steps",
        "lines",
        "Step ids that may follow. One per line. Empty means terminal.",
    ),
    FieldGuidance(
        "exception_paths",
        "Exception paths",
        "records",
        "What happens when this step fails. One per line.",
        columns=["failure mode", "owner", "handling", "next step id"],
    ),
    FieldGuidance(
        "judgment_load",
        "Judgment load",
        "choice",
        "How much human judgment the decision needs.",
        choices=_choices(JudgmentLoad),
    ),
    FieldGuidance(
        "repeatability",
        "Repeatability",
        "choice",
        "How often this recurs in the same shape.",
        choices=_choices(Repeatability),
    ),
    FieldGuidance(
        "determinism",
        "Determinism",
        "choice",
        "Whether identical inputs give identical output.",
        choices=_choices(Determinism),
    ),
    FieldGuidance(
        "risk",
        "Risk",
        "choice",
        "How much damage a wrong outcome causes.",
        choices=_choices(RiskLevel),
    ),
    FieldGuidance(
        "reversibility",
        "Reversibility",
        "choice",
        "Whether the effect can be undone.",
        choices=_choices(Reversibility),
    ),
    FieldGuidance(
        "data_sensitivity",
        "Data sensitivity",
        "choice",
        "How sensitive the data handled here is.",
        choices=_choices(DataSensitivity),
    ),
    FieldGuidance("notes", "Notes", "text", "Anything else the observer recorded."),
]

#: The six fields that live under ``characteristics`` rather than on the step.
#: They drive cooperation assessment, so they are edited here rather than being
#: left to YAML — a step nobody characterized is never treated as automatable,
#: and an operator who cannot see that is not being guided.
CHARACTERISTIC_FIELDS = frozenset(
    {
        "judgment_load",
        "repeatability",
        "determinism",
        "risk",
        "reversibility",
        "data_sensitivity",
    }
)


def step_field_guidance() -> list[FieldGuidance]:
    """Every editable field, with the rule that governs it.

    The hint is the field's own description plus, where a rule fires on it,
    that rule's remediation text read live from the registry. This is why the
    editor is *guided*: the advice next to a box is the same sentence the
    finding will give if the box is left wrong.
    """
    out: list[FieldGuidance] = []
    for spec in _FIELDS:
        rule_id = _FIELD_RULES.get(spec.name, "")
        rule = RULES.get(rule_id)
        hint = spec.hint
        if rule is not None:
            hint = f"{spec.hint}  {rule.rule_id}: {rule.remediation}"
        out.append(
            FieldGuidance(
                name=spec.name,
                label=spec.label,
                kind=spec.kind,
                hint=hint,
                rule_id=rule_id,
                blocking=bool(rule and rule.blocking),
                choices=list(spec.choices),
                columns=list(spec.columns),
            )
        )
    return out


# --------------------------------------------------------- text <-> contract


def _records_to_text(records: list[dict], columns: list[str]) -> str:
    """Render a list of objects as one ``|``-separated line each."""
    lines = []
    for record in records:
        cells = [str(record.get(c, "")) for c in columns]
        while cells and not cells[-1]:
            cells.pop()  # trailing empties add nothing to read
        lines.append(f" {SEPARATOR} ".join(cells))
    return "\n".join(lines)


def _text_to_records(text: str, columns: list[str]) -> list[dict]:
    """Parse ``|``-separated lines back into objects.

    Missing trailing columns become empty strings rather than an error: an
    operator who typed only a failure mode has recorded something true, and
    the validator will tell them what is still missing. Refusing the line
    would lose the part they did know.
    """
    records = []
    for line in text.splitlines():
        if not line.strip():
            continue
        cells = [c.strip() for c in line.split(SEPARATOR)]
        cells += [""] * (len(columns) - len(cells))
        records.append(dict(zip(columns, cells[: len(columns)])))
    return records


def _step_to_values(step: WorkflowStep) -> dict[str, str]:
    """Flatten a step into the editor's text values."""
    characteristics = step.characteristics
    values: dict[str, str] = {}
    for spec in _FIELDS:
        if spec.name in CHARACTERISTIC_FIELDS:
            values[spec.name] = getattr(characteristics, spec.name).value
        elif spec.kind == "lines":
            values[spec.name] = "\n".join(getattr(step, spec.name))
        elif spec.kind == "records":
            source = [item.model_dump(mode="json") for item in getattr(step, spec.name)]
            values[spec.name] = _records_to_text(source, _RECORD_KEYS[spec.name])
        else:
            values[spec.name] = getattr(step, spec.name)
    return values


#: Contract field names behind each ``records`` column, in the same order the
#: guidance shows them. Kept beside the guidance rather than derived from the
#: models, because the column *labels* are prose ("required (yes/no)") and the
#: contract names are not.
_RECORD_KEYS = {
    "inputs": ["name", "source", "required"],
    "outputs": ["name", "artifact_type", "evidence_requirement"],
    "exception_paths": ["failure_mode", "owner", "handling", "next_step"],
}

#: Values accepted for ``StepInput.required``. Anything else is a typo, and a
#: typo that silently means False would quietly drop a rule's coverage.
_TRUE = {"yes", "true", "y", "1", "required"}
_FALSE = {"no", "false", "n", "0", "optional"}


def _values_to_step(step: WorkflowStep, values: dict[str, str]) -> dict:
    """Apply edited values onto a step, returning its raw dict.

    Only fields present in ``values`` are changed, so a caller may submit one
    field without having to round-trip the rest.
    """
    raw = step.model_dump(mode="json")
    for spec in _FIELDS:
        if spec.name not in values:
            continue
        text = values[spec.name]
        if spec.name in CHARACTERISTIC_FIELDS:
            raw["characteristics"][spec.name] = text.strip()
        elif spec.kind == "lines":
            raw[spec.name] = [line.strip() for line in text.splitlines() if line.strip()]
        elif spec.kind == "records":
            keys = _RECORD_KEYS[spec.name]
            records = _text_to_records(text, keys)
            for record in records:
                if "required" in record:
                    flag = record["required"].strip().lower()
                    record["required"] = flag not in _FALSE if flag else True
                if "next_step" in record:
                    record["next_step"] = record["next_step"] or None
            raw[spec.name] = records
        else:
            raw[spec.name] = text.strip() if "\n" not in text else text
    return raw


def _bad_required_values(values: dict[str, str]) -> list[str]:
    """Any ``required`` cell that is neither a yes nor a no, quoted back."""
    text = values.get("inputs", "")
    offenders = []
    for record in _text_to_records(text, _RECORD_KEYS["inputs"]):
        flag = str(record.get("required", "")).strip().lower()
        if flag and flag not in _TRUE and flag not in _FALSE:
            offenders.append(record["required"])
    return offenders


# ---------------------------------------------------------------- the service


def _open(draft: HumanWorkflowDraft, step_id: str, db) -> StepResult:
    """Build a StepResult for one step of an already-loaded draft."""
    step_ids = [s.step_id for s in draft.steps]
    if not step_ids:
        return StepResult(
            ok=False,
            summary="This draft has no steps",
            refusal=(
                "Add a step to the YAML before editing. The editor changes "
                "steps; it does not create the first one."
            ),
            workflow_id=draft.workflow_id,
        )
    target = step_id or step_ids[0]
    if target not in step_ids:
        return StepResult(
            ok=False,
            summary="Unknown step",
            refusal=f"'{target}' is not a step of '{draft.workflow_id}'.",
            workflow_id=draft.workflow_id,
            step_ids=step_ids,
        )

    report = validate_workflow(draft)
    findings = [f for f in _finding_views(report) if f.location == target]
    step = draft.step(target)
    return StepResult(
        ok=True,
        summary=(
            f"{step.name or target} — {len(findings)} finding(s) against this step."
        ),
        workflow_id=draft.workflow_id,
        step_ids=step_ids,
        step=StepView(
            step_id=target,
            name=step.name,
            values=_step_to_values(step),
            findings=findings,
        ),
    )


def read_step(
    path: str | Path, step_id: str = "", db: str | Path = DEFAULT_DB_PATH
) -> StepResult:
    """Open one step for editing, with the findings that name it.

    Defaults to the first step, so opening the editor on a fresh draft shows
    something rather than an empty pane. The findings are filtered to this step
    only: the point of the editor is to fix *this* step, and a full report on
    every screen teaches an operator to stop reading it.
    """
    draft, problem = _load_draft(path)
    if draft is None:
        return StepResult(ok=False, summary="Could not read the draft", refusal=problem)
    return _open(draft, step_id, db)


def write_step(
    path: str | Path,
    step_id: str,
    values: dict[str, str],
    db: str | Path = DEFAULT_DB_PATH,
    *,
    save_to_ledger: bool = True,
) -> StepResult:
    """Write edited values back to the draft file, then re-validate.

    The write is contract-checked before it touches the disk: values are
    applied to a copy, the whole draft is re-validated against the schema, and
    a draft that would no longer load is refused with the field named. An
    editor that could write a file its own loader rejects would be a way to
    lose work.

    A backup is taken first because YAML comments do not survive the
    round-trip — see the module docstring.
    """
    draft, problem = _load_draft(path)
    if draft is None:
        return StepResult(ok=False, summary="Could not read the draft", refusal=problem)

    step_ids = [s.step_id for s in draft.steps]
    if step_id not in step_ids:
        return StepResult(
            ok=False,
            summary="Unknown step",
            refusal=f"'{step_id}' is not a step of '{draft.workflow_id}'.",
            workflow_id=draft.workflow_id,
            step_ids=step_ids,
        )

    offenders = _bad_required_values(values)
    if offenders:
        return StepResult(
            ok=False,
            summary="Unrecognised value in the inputs 'required' column",
            refusal=(
                f"{', '.join(repr(o) for o in offenders)} — write yes or no. "
                f"Guessing which one you meant is how a required input quietly "
                f"becomes optional."
            ),
            workflow_id=draft.workflow_id,
            step_ids=step_ids,
        )

    raw = draft.model_dump(mode="json")
    index = step_ids.index(step_id)
    raw["steps"][index] = _values_to_step(draft.step(step_id), values)
    try:
        edited = HumanWorkflowDraft.model_validate(raw)
    except Exception as exc:  # pydantic ValidationError, reported not raised
        return StepResult(
            ok=False,
            summary="The edit does not match the contract",
            refusal=str(exc),
            workflow_id=draft.workflow_id,
            step_ids=step_ids,
        )

    file = Path(path)
    backup = file.with_suffix(file.suffix + ".bak")
    try:
        backup.write_text(file.read_text(encoding="utf-8"), encoding="utf-8")
        file.write_text(
            yaml.safe_dump(raw, sort_keys=False, width=100, allow_unicode=True),
            encoding="utf-8",
        )
    except OSError as exc:
        return StepResult(
            ok=False,
            summary="Could not write the draft",
            refusal=str(exc),
            workflow_id=draft.workflow_id,
            step_ids=step_ids,
        )

    if save_to_ledger:
        _ledger(db).save_workflow_draft(edited)

    result = _open(edited, step_id, db)
    result.backup_path = str(backup)
    result.summary = (
        f"Saved '{step_id}'. {result.summary}  "
        f"Comments were not preserved; the previous file is at {backup.name}."
    )
    return result
