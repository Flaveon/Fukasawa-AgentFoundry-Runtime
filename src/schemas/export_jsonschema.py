# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""JSON Schema export — the generation seam for non-Python consumers.

The Pydantic models in this package are the **canonical** contract source
(ADR-001). This module derives JSON Schema from them so that any future
consumer written in another language generates its types instead of
hand-writing a parallel definition that drifts.

Why this exists at all: the release Definition of Done originally required
fixtures proving Python and TypeScript agreed on serialized shapes. There is
no TypeScript in this repository, so that obligation was ruled not applicable
(architecture review D1, ratified 2026-07-25) and replaced with this: export
the schemas, pin them with golden tests, and document that generation is the
only permitted path to a second representation.

**Known limit, stated plainly.** JSON Schema captures field names, types,
defaults, and enum values. It does **not** capture rules enforced by Pydantic
validators or by the runtime — for example that an override may not increase
autonomy on a floored step, or that a CONSCIOUS transition cannot be owned by
an agent. A generated consumer that validates only against these artifacts
will accept data this runtime rejects. Those rules are listed in prose in
``docs/schema-reference.md``; a future consumer must implement them
deliberately.
"""

import json
from pathlib import Path

from pydantic import BaseModel

from src.schemas.cooperation import (
    CooperationAssessment,
    CooperativeWorkflow,
    StepAssignment,
)
from src.schemas.findings import (
    RiskAcceptance,
    ValidationReport,
    WorkflowFinding,
)
from src.schemas.human_workflow import (
    AccountableWorkflow,
    HumanWorkflowDraft,
    WorkflowStep,
)

#: The contracts exported for external consumption, by stable artifact name.
#: Keys are filenames (minus extension) and are part of the published surface —
#: renaming one is a breaking change for any generated consumer.
EXPORTED_CONTRACTS: dict[str, type[BaseModel]] = {
    "human-workflow-draft": HumanWorkflowDraft,
    "workflow-step": WorkflowStep,
    "accountable-workflow": AccountableWorkflow,
    "workflow-finding": WorkflowFinding,
    "validation-report": ValidationReport,
    "risk-acceptance": RiskAcceptance,
    "cooperation-assessment": CooperationAssessment,
    "step-assignment": StepAssignment,
    "cooperative-workflow": CooperativeWorkflow,
}


def contract_schema(model: type[BaseModel]) -> dict:
    """Return one model's JSON Schema as a plain dict.

    Uses Pydantic's ``model_json_schema`` with the serialization view, since
    what a consumer receives is serialized output rather than constructor
    input.
    """
    return model.model_json_schema(mode="serialization")


def all_schemas() -> dict[str, dict]:
    """Return every exported contract's JSON Schema, keyed by artifact name.

    Deterministic: keys are sorted, so repeated exports of unchanged models
    produce byte-identical output and the golden tests stay meaningful.
    """
    return {name: contract_schema(EXPORTED_CONTRACTS[name]) for name in sorted(EXPORTED_CONTRACTS)}


def schema_json(name: str) -> str:
    """Return one contract's JSON Schema as canonical, sorted-key JSON text."""
    if name not in EXPORTED_CONTRACTS:
        raise KeyError(
            f"no exported contract '{name}' (available: {sorted(EXPORTED_CONTRACTS)})"
        )
    return json.dumps(contract_schema(EXPORTED_CONTRACTS[name]), indent=2, sort_keys=True)


def write_schemas(out_dir: str | Path) -> list[Path]:
    """Write every exported contract to ``out_dir`` as ``<name>.schema.json``.

    Returns the paths written, in sorted order. Output is sorted-key JSON so
    the files are diffable and stable across runs.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name in sorted(EXPORTED_CONTRACTS):
        path = out / f"{name}.schema.json"
        path.write_text(schema_json(name) + "\n", encoding="utf-8")
        written.append(path)
    return written
