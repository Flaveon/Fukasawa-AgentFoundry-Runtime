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



def _check_required_files(pkg: Path) -> list[str]:
    """Every file on the Agent Foundry standard list must be present.

    A package missing one of its required files cannot be read by the rest
    of this validator, let alone deployed — this check runs first so that
    a missing file is reported plainly instead of as a cascade of confusing
    failures from every check downstream of it.
    """
    findings: list[str] = []
    for name in PACKAGE_FILES:
        if not (pkg / name).exists():
            findings.append(f"missing required file: {name}")
    return findings


def _validate_manifest(pkg: Path) -> tuple[list[str], AgentPackageManifest | None]:
    """manifest.json must parse and satisfy its schema.

    The manifest is the machine-readable summary other tooling (and the
    checks below) read from; a manifest that fails its own schema cannot be
    trusted to describe the rest of the package correctly.
    """
    findings: list[str] = []
    manifest = None
    try:
        manifest = AgentPackageManifest.model_validate_json(
            (pkg / "manifest.json").read_text(encoding="utf-8")
        )
    except (ValidationError, json.JSONDecodeError) as exc:
        findings.append(f"manifest.json invalid: {exc}")
    return findings, manifest


def _validate_capsule(pkg: Path) -> tuple[list[str], AgentCapsuleContract | None]:
    """process_capsule.yaml must parse and satisfy the capsule contract.

    This is where the depth-level ceiling on individual steps is enforced
    by the schema itself (`AgentCapsuleContract` rejects a step above its
    own depth_level) — a capsule that fails to validate here means the
    agent's actual work instructions may already exceed its declared depth.
    """
    findings: list[str] = []
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
    return findings, capsule


def _validate_skill(pkg: Path) -> tuple[list[str], dict | None]:
    """SKILL.md's front matter must parse and declare the four fields the
    cross-file agreement check (`_check_agreements`) depends on: agent,
    maturity, depth_level and workspace_profile. A SKILL.md a human can read
    but a machine cannot parse is, for governance purposes, undeclared.
    """
    findings: list[str] = []
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
    return findings, skill


def _check_agreements(
    manifest: AgentPackageManifest, capsule: AgentCapsuleContract, skill: dict
) -> list[str]:
    """depth_level, agent name and maturity must agree across SKILL.md,
    manifest.json and process_capsule.yaml.

    This is the check that makes a declared depth boundary mean something:
    an agent cannot quietly promote itself (in depth or maturity) by editing
    only one of the three files that are each supposed to say the same
    thing. Only called once all three have parsed into real objects —
    comparing a value against a file that failed to parse would just be
    comparing against `None`.
    """
    findings: list[str] = []
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
    return findings


def _validate_evals(pkg: Path, manifest: AgentPackageManifest | None) -> list[str]:
    """evals.yaml must declare the three mandatory doctrine checks, and a
    package claiming any maturity beyond draft must show an overall pass.

    A package cannot promote itself past draft by editing manifest.json
    alone while evals.yaml still says the work is unverified — that is the
    gate `src/governance/maturity.py` relies on this check to enforce. A
    malformed or wrongly-shaped evals.yaml (not a mapping at all, e.g. a
    YAML list) is reported as a finding here rather than raised as an
    exception: the shape is wrong in the same way a missing mandatory check
    is wrong, and both must fail closed instead of crashing the validator.
    """
    findings: list[str] = []
    evals_overall = None
    try:
        evals = yaml.safe_load((pkg / "evals.yaml").read_text(encoding="utf-8"))
        if evals is not None and not isinstance(evals, dict):
            findings.append(
                f"evals.yaml must be a mapping with a 'checks' key, not a "
                f"{type(evals).__name__} — the three doctrine checks cannot "
                f"be located"
            )
            evals = None
        checks = (evals or {}).get("checks", {})
        if not isinstance(checks, dict):
            # A list of check names, or a string that happens to contain
            # them, would otherwise pass the `required not in checks` test
            # below by membership or substring match — true, and useless:
            # there is no per-check 'result'/'evidence' to read. Report the
            # shape and treat it the same as "no checks at all".
            findings.append(
                f"evals.yaml 'checks' must be a mapping of check name to "
                f"result, not a {type(checks).__name__} — the mandatory "
                f"checks cannot be located"
            )
            checks = {}
        for required in MANDATORY_EVAL_CHECKS:
            if required not in checks:
                findings.append(
                    f"evals.yaml missing mandatory check '{required}' — the "
                    f"three doctrine checks may be extended, never replaced"
                )
        evals_overall = (evals or {}).get("overall")
    except yaml.YAMLError as exc:
        findings.append(f"evals.yaml is not valid YAML: {exc}")

    if manifest and manifest.maturity is not Maturity.DRAFT:
        if evals_overall != "pass":
            findings.append(
                f"maturity is '{manifest.maturity.value}' but evals.yaml "
                f"overall is '{evals_overall}' — promotion beyond draft "
                f"requires passing evals"
            )
    return findings


def _validate_permissions(pkg: Path) -> list[str]:
    """permissions.json must declare at least one path the agent may touch.

    Doctrine is blunt about this: an agent with undefined paths is
    incomplete, not merely under-specified. A permissions.json that is not
    a JSON object at all (e.g. a list) is reported as a finding here rather
    than raised as an exception — the wrong shape fails closed the same way
    an empty 'paths' mapping does.
    """
    findings: list[str] = []
    try:
        permissions = json.loads((pkg / "permissions.json").read_text(encoding="utf-8"))
        if not isinstance(permissions, dict):
            return [
                f"permissions.json must be a JSON object with a 'paths' "
                f"key, not a {type(permissions).__name__}"
            ]
        if not permissions.get("paths"):
            findings.append(
                "permissions.json defines no paths — agents with undefined "
                "paths are incomplete"
            )
    except json.JSONDecodeError as exc:
        findings.append(f"permissions.json is not valid JSON: {exc}")
    return findings


def _validate_soul(pkg: Path, manifest: AgentPackageManifest | None) -> list[str]:
    """On a C-Pax workspace, SOUL.md must declare doctrine inheritance.

    A C-Pax agent's behavioral identity is supposed to come from the
    project's shared doctrine.md, not be invented per agent; this check
    only applies once the manifest has parsed and named the workspace
    profile, since there is nothing to check an undeclared profile against.
    """
    findings: list[str] = []
    if manifest and manifest.workspace_profile == "c-pax":
        soul = (pkg / "SOUL.md").read_text(encoding="utf-8")
        if "inherits:" not in soul:
            findings.append(
                "workspace profile is c-pax but SOUL.md declares no doctrine "
                "inheritance ('inherits: ../../doctrine.md')"
            )
    return findings


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
    req_findings = _check_required_files(pkg)
    findings.extend(req_findings)
    if findings:
        # Without the core files the cross-checks below would just cascade.
        return findings

    # --- 2. manifest ------------------------------------------------------
    man_findings, manifest = _validate_manifest(pkg)
    findings.extend(man_findings)

    # --- 3. capsule contract ---------------------------------------------
    cap_findings, capsule = _validate_capsule(pkg)
    findings.extend(cap_findings)

    # --- 4. SKILL front matter -------------------------------------------
    skill_findings, skill = _validate_skill(pkg)
    findings.extend(skill_findings)

    # --- 5. depth and identity must agree everywhere ----------------------
    if manifest and capsule and skill:
        findings.extend(_check_agreements(manifest, capsule, skill))

    # --- 6 & 7. evals and maturity ----------------------------------------
    findings.extend(_validate_evals(pkg, manifest))

    # --- 8. permissions ---------------------------------------------------
    findings.extend(_validate_permissions(pkg))

    # --- 9. C-Pax SOUL inheritance ----------------------------------------
    findings.extend(_validate_soul(pkg, manifest))

    return findings
