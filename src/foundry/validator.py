# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Agent package validator.

Checks a package directory against the Agent Foundry standard: every
required file present, every schema valid, and every declaration consistent
across files. The validator is how the runtime guarantees that a generated
agent cannot silently exceed its declared depth level — the depth appears in
SKILL.md, manifest.json, and process_capsule.yaml, and all three must agree
(and every capsule step must sit at or below it).

The validator returns findings instead of raising: a human reviewing a
package wants the full list of problems, not the first one.
"""

import json
from pathlib import Path

import yaml
from pydantic import ValidationError

from src.foundry.generator import PACKAGE_FILES
from src.schemas.agent_package import (
    AgentCapsuleContract,
    AgentPackageManifest,
    Maturity,
)

#: The three eval checks doctrine makes mandatory for every C-Pax agent.
MANDATORY_EVAL_CHECKS = (
    "output_schema_conformance",
    "escalation_correctness",
    "scope_compliance",
)


def _parse_skill_front_matter(text: str) -> dict:
    """Extract the YAML front matter block from SKILL.md.

    Raises ValueError if the block is missing or malformed — a SKILL.md
    without machine-readable depth and maturity cannot be validated.
    """
    if not text.startswith("---"):
        raise ValueError("SKILL.md has no YAML front matter block")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError("SKILL.md front matter block is not closed")
    data = yaml.safe_load(parts[1])
    if not isinstance(data, dict):
        raise ValueError("SKILL.md front matter is not a mapping")
    return data


def validate_package(package_dir: str | Path) -> list[str]:
    """Validate one agent package directory. Returns a list of findings.

    An empty list means the package passes. Findings are human sentences,
    each independently actionable.
    """
    pkg = Path(package_dir)
    findings: list[str] = []

    if not pkg.is_dir():
        return [f"'{pkg}' is not a directory"]

    # --- 1. every required file exists -----------------------------------
    for name in PACKAGE_FILES:
        if not (pkg / name).exists():
            findings.append(f"missing required file: {name}")
    if findings:
        # Without the core files the cross-checks below would just cascade.
        return findings

    # --- 2. manifest ------------------------------------------------------
    manifest = None
    try:
        manifest = AgentPackageManifest.model_validate_json(
            (pkg / "manifest.json").read_text(encoding="utf-8")
        )
    except (ValidationError, json.JSONDecodeError) as exc:
        findings.append(f"manifest.json invalid: {exc}")

    # --- 3. capsule contract ---------------------------------------------
    capsule = None
    try:
        raw = yaml.safe_load((pkg / "process_capsule.yaml").read_text(encoding="utf-8"))
        capsule = AgentCapsuleContract.model_validate(raw)
    except yaml.YAMLError as exc:
        findings.append(f"process_capsule.yaml is not valid YAML: {exc}")
    except ValidationError as exc:
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"]) or "(root)"
            findings.append(f"process_capsule.yaml invalid at {loc}: {err['msg']}")

    # --- 4. SKILL front matter -------------------------------------------
    skill = None
    try:
        skill = _parse_skill_front_matter(
            (pkg / "SKILL.md").read_text(encoding="utf-8")
        )
        for key in ("agent", "maturity", "depth_level", "workspace_profile"):
            if key not in skill:
                findings.append(f"SKILL.md front matter missing '{key}'")
    except ValueError as exc:
        findings.append(str(exc))

    # --- 5. depth and identity must agree everywhere ----------------------
    if manifest and capsule and skill:
        declared = {
            "SKILL.md": skill.get("depth_level"),
            "manifest.json": manifest.depth_level,
            "process_capsule.yaml": capsule.depth_level,
        }
        if len(set(declared.values())) > 1:
            findings.append(
                "depth_level disagrees across files: "
                + ", ".join(f"{k}={v}" for k, v in declared.items())
                + " — a depth boundary that differs by file is no boundary"
            )
        names = {
            "SKILL.md": skill.get("agent"),
            "manifest.json": manifest.agent_name,
            "process_capsule.yaml": capsule.owner_agent,
        }
        if len(set(names.values())) > 1:
            findings.append(
                "agent name disagrees across files: "
                + ", ".join(f"{k}={v}" for k, v in names.items())
            )
        maturities = {
            "SKILL.md": str(skill.get("maturity")),
            "manifest.json": manifest.maturity.value,
            "process_capsule.yaml": capsule.maturity.value,
        }
        if len(set(maturities.values())) > 1:
            findings.append(
                "maturity disagrees across files: "
                + ", ".join(f"{k}={v}" for k, v in maturities.items())
            )

    # --- 6. the three mandatory eval checks -------------------------------
    evals_overall = None
    try:
        evals = yaml.safe_load((pkg / "evals.yaml").read_text(encoding="utf-8"))
        checks = (evals or {}).get("checks", {})
        for required in MANDATORY_EVAL_CHECKS:
            if required not in checks:
                findings.append(
                    f"evals.yaml missing mandatory check '{required}' — the "
                    f"three doctrine checks may be extended, never replaced"
                )
        evals_overall = (evals or {}).get("overall")
    except yaml.YAMLError as exc:
        findings.append(f"evals.yaml is not valid YAML: {exc}")

    # --- 7. maturity claims need evidence ---------------------------------
    if manifest and manifest.maturity is not Maturity.DRAFT:
        if evals_overall != "pass":
            findings.append(
                f"maturity is '{manifest.maturity.value}' but evals.yaml "
                f"overall is '{evals_overall}' — promotion beyond draft "
                f"requires passing evals"
            )

    # --- 8. permissions must define paths ---------------------------------
    try:
        permissions = json.loads((pkg / "permissions.json").read_text(encoding="utf-8"))
        if not permissions.get("paths"):
            findings.append(
                "permissions.json defines no paths — agents with undefined "
                "paths are incomplete"
            )
    except json.JSONDecodeError as exc:
        findings.append(f"permissions.json is not valid JSON: {exc}")

    # --- 9. C-Pax SOUL inheritance ----------------------------------------
    if manifest and manifest.workspace_profile == "c-pax":
        soul = (pkg / "SOUL.md").read_text(encoding="utf-8")
        if "inherits:" not in soul:
            findings.append(
                "workspace profile is c-pax but SOUL.md declares no doctrine "
                "inheritance ('inherits: ../../doctrine.md')"
            )

    return findings
