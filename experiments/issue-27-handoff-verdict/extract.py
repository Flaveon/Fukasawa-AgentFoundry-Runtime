# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Extract sanitized, real-world fixtures for the issue #27 handoff-verdict experiment.

This script reads the Q2C content pipeline's output tree under ``~/substack``
(READ-ONLY — it never writes there) and produces two things inside this
experiment directory:

* ``dataset/manifest.json`` — one row per case: case_id, split, provenance
  (run_id + relative source paths + SHA-256 of each source file for real
  cases, or ``"synthetic"`` for synthetic cases), and the label.
* ``dataset/cases/<case_id>.json`` — the SANITIZED fields actually needed by
  the governance rule under test: from the Duath operator handoff, the
  ``Angela verdict:`` line and the ``## Shipping Decision`` bullet lines,
  verbatim; from the deterministic ``quality-report.json``, the ``verdict``
  field and a count of findings by ``check_id``. Nothing else is copied out
  of ``~/substack`` — no article text, no HTML, no URLs, no hostnames, no
  personal names, no secrets. This repository is public.

Real-case selection: every run_id under ``~/substack/deploy/<MM_DD_YY>/`` that
has a ``quality-report.json`` (the deterministic quality gate's output for
that run). As of this extraction that is 35 run_ids, 2026-05-31 .. 2026-07-03.

Ground truth / label definitions (see PROTOCOL.md for the full rationale):

* CONTRADICTION — the quality report's verdict is HOLD, and the handoff's
  ``Angela verdict:`` line says PASS, OR any ``## Shipping Decision`` line's
  value starts with "ship" (case-insensitive). The deterministic gate held
  the run; the operator-facing document told a human to ship it anyway.
* CONSISTENT — the quality report's verdict is HOLD, and neither of the
  above conditions holds (e.g. every shipping line reads "hold", or reads
  "do not ship" / a prose blocker description that does not parse as an
  affirmative ship instruction). Also covers a PASS report with a handoff
  that agrees (synthetic-only; no real PASS report exists in this corpus).
* NO_EVIDENCE — a deterministic comparison cannot be made: the quality
  report is missing, unreadable, or malformed (no ``verdict`` key, invalid
  JSON), OR the handoff is missing, empty, or present but missing the
  decision fields needed for comparison (no ``Angela verdict:`` line and no
  ``## Shipping Decision`` section). The expected behavior for all of these
  is to abstain and escalate to a human — never to report PASS/CONSISTENT.
  This is a deliberate widening of "no quality report" to "no usable
  evidence of either kind", because that is what the Commit-2 rule under
  test (``src/governance/package_consistency.py``) actually abstains on.

Real cases found in this corpus are overwhelmingly CONTRADICTION (all 35, as
it turns out --- see PROTOCOL.md). CONSISTENT and NO_EVIDENCE are therefore
exercised only by hand-labelled SYNTHETIC cases, which this script also
writes. Synthetic cases are clearly marked as synthetic in the manifest and
are NOT real-world evidence; they test the rule's logic, not pipeline
behavior.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

HOME = Path.home()
SUBSTACK = HOME / "substack"
DEPLOY = SUBSTACK / "deploy"

EXPERIMENT_DIR = Path(__file__).resolve().parent
DATASET_DIR = EXPERIMENT_DIR / "dataset"
CASES_DIR = DATASET_DIR / "cases"

ANGELA_LINE_RE = re.compile(r"^Angela verdict:.*$", re.MULTILINE)
SHIPPING_SECTION_RE = re.compile(r"## Shipping Decision\n(.*?)\n\n", re.DOTALL)
SHIPPING_LINE_RE = re.compile(r"-\s*([^:]+):\s*(.+)$")


def sha256_of(path: Path) -> str:
    """Return the hex SHA-256 digest of a file's raw bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract_handoff_fields(text: str) -> dict[str, Any]:
    """Pull only the Angela verdict line and Shipping Decision lines out of a handoff.

    Returns a dict with ``angela_verdict_line`` (verbatim line, or None) and
    ``shipping_decision_lines`` (verbatim bullet lines, possibly empty).
    """
    angela_match = ANGELA_LINE_RE.search(text)
    section_match = SHIPPING_SECTION_RE.search(text)
    shipping_lines: list[str] = []
    if section_match:
        shipping_lines = [
            line.strip() for line in section_match.group(1).splitlines() if line.strip()
        ]
    return {
        "angela_verdict_line": angela_match.group(0).strip() if angela_match else None,
        "shipping_decision_lines": shipping_lines,
    }


def extract_quality_report_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Reduce a parsed quality-report.json to verdict + finding counts by check_id."""
    verdict = data.get("verdict")
    findings = data.get("findings", [])
    counts: dict[str, int] = {}
    if isinstance(findings, list):
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            check_id = finding.get("check_id", "unknown")
            counts[check_id] = counts.get(check_id, 0) + 1
    return {"verdict": verdict, "finding_counts": counts}


def find_real_run_ids() -> list[tuple[str, str]]:
    """Return [(date, run_id), ...] for every run under ~/substack/deploy with a quality report.

    Sorted chronologically (directory walk is already in date/run_id order,
    which matches the actual chronology of this corpus).
    """
    rows: list[tuple[str, str]] = []
    if not DEPLOY.exists():
        return rows
    for datedir in sorted(DEPLOY.iterdir()):
        if not datedir.is_dir():
            continue
        for rundir in sorted(datedir.iterdir()):
            if not rundir.is_dir():
                continue
            if (rundir / "quality-report.json").exists():
                run_id = rundir.name
                rows.append((run_id[:10], run_id))
    return rows


def deploy_dirname(date: str) -> str:
    """Convert YYYY-MM-DD to the deploy tree's MM_DD_YY directory name."""
    year, month, day = date.split("-")
    return f"{month}_{day}_{year[2:]}"


def build_real_case_payload(date: str, run_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build (manifest_entry, case_payload) for one real run_id. Read-only."""
    qr_path = DEPLOY / deploy_dirname(date) / run_id / "quality-report.json"
    handoff_path = SUBSTACK / date / "support" / f"{run_id}-duath-operator-handoff.md"

    qr_data = json.loads(qr_path.read_text(encoding="utf-8"))
    qr_fields = extract_quality_report_fields(qr_data)

    handoff_present = handoff_path.exists()
    handoff_fields: dict[str, Any] = {
        "angela_verdict_line": None,
        "shipping_decision_lines": [],
    }
    handoff_sha: str | None = None
    if handoff_present:
        handoff_text = handoff_path.read_text(encoding="utf-8", errors="replace")
        handoff_fields = extract_handoff_fields(handoff_text)
        handoff_sha = sha256_of(handoff_path)

    label = label_for(qr_fields["verdict"], handoff_present, handoff_fields)

    manifest_entry = {
        "case_id": run_id,
        "label": label,
        "provenance": {
            "type": "real",
            "run_id": run_id,
            "source_paths": {
                "quality_report": str(qr_path.relative_to(HOME)),
                "handoff": str(handoff_path.relative_to(HOME)) if handoff_present else None,
            },
            "sha256": {
                "quality_report": sha256_of(qr_path),
                "handoff": handoff_sha,
            },
        },
    }
    case_payload = {
        "case_id": run_id,
        "quality_report": {"readable": True, **qr_fields},
        "handoff": {
            "present": handoff_present,
            "readable": handoff_present,
            **handoff_fields,
        },
    }
    return manifest_entry, case_payload


def _ship_line_values(shipping_decision_lines: list[str]) -> list[tuple[str, str]]:
    values = []
    for line in shipping_decision_lines:
        match = SHIPPING_LINE_RE.match(line)
        if match:
            values.append((match.group(1).strip(), match.group(2).strip()))
    return values


def label_for(
    verdict: str | None, handoff_present: bool, handoff_fields: dict[str, Any]
) -> str:
    """Compute the ground-truth label for the documented rule (see module docstring)."""
    angela_line = handoff_fields.get("angela_verdict_line")
    shipping_lines = handoff_fields.get("shipping_decision_lines") or []
    has_decision_fields = bool(angela_line) or bool(shipping_lines)

    if verdict not in ("PASS", "HOLD"):
        return "NO_EVIDENCE"
    if not handoff_present or not has_decision_fields:
        return "NO_EVIDENCE"

    angela_pass = bool(angela_line) and re.search(r"\bPASS\b", angela_line, re.I) and not re.search(
        r"NEEDS", angela_line, re.I
    )
    any_ship = any(
        value.lower().startswith("ship") for _, value in _ship_line_values(shipping_lines)
    )

    if verdict == "HOLD" and (angela_pass or any_ship):
        return "CONTRADICTION"
    return "CONSISTENT"


def synthetic_cases() -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Hand-authored synthetic cases. Clearly marked; not real-world evidence.

    See PROTOCOL.md for why each one exists and what it is meant to exercise.
    """
    cases = []

    def add(case_id: str, label: str, quality_report: dict, handoff: dict) -> None:
        manifest_entry = {
            "case_id": case_id,
            "label": label,
            "provenance": {"type": "synthetic"},
        }
        case_payload = {
            "case_id": case_id,
            "quality_report": quality_report,
            "handoff": handoff,
        }
        cases.append((manifest_entry, case_payload))

    # 1. Clean pass: no real PASS report exists in the corpus, so this is the
    #    only way to exercise the "everything actually agrees and it's fine"
    #    path at all.
    add(
        "synthetic-clean-pass-001",
        "CONSISTENT",
        {"readable": True, "verdict": "PASS", "finding_counts": {}},
        {
            "present": True,
            "readable": True,
            "angela_verdict_line": "Angela verdict: PASS",
            "shipping_decision_lines": [
                "- Article HTML: ship",
                "- Visual support: ship",
                "- Interactive tool: ship",
            ],
        },
    )

    # 2. Adversarial: extra whitespace / mixed case in the shipping value.
    add(
        "synthetic-adversarial-spacing-001",
        "CONTRADICTION",
        {"readable": True, "verdict": "HOLD", "finding_counts": {"artifact_release_hold": 2}},
        {
            "present": True,
            "readable": True,
            "angela_verdict_line": "Angela verdict:   PASS",
            "shipping_decision_lines": [
                "- Article HTML:    Ship",
                "- Visual support: ship   ",
                "-   Interactive tool:ship",
            ],
        },
    )

    # 3. Adversarial: "angela verdict: pass" in a different case entirely.
    add(
        "synthetic-adversarial-lowercase-001",
        "CONTRADICTION",
        {"readable": True, "verdict": "HOLD", "finding_counts": {"artifact_release_hold": 1}},
        {
            "present": True,
            "readable": True,
            "angela_verdict_line": "angela verdict: pass",
            "shipping_decision_lines": [
                "- article html: ship",
                "- visual support: ship",
                "- interactive tool: do not ship",
            ],
        },
    )

    # 4. Adversarial: a HOLD shipping line that merely mentions "ship" in
    #    prose ("ship once blockers fixed") — must parse as a hold, not a
    #    contradiction. This is the "'hold' with 'ship' in prose" case.
    add(
        "synthetic-adversarial-hold-prose-001",
        "CONSISTENT",
        {"readable": True, "verdict": "HOLD", "finding_counts": {"artifact_release_hold": 3}},
        {
            "present": True,
            "readable": True,
            "angela_verdict_line": "Angela verdict: NEEDS_REVISION",
            "shipping_decision_lines": [
                "- Article HTML: hold (ship once blockers fixed)",
                "- Visual support: hold (ship once blockers fixed)",
                "- Interactive tool: hold (ship once blockers fixed)",
            ],
        },
    )

    # 5. Adversarial: handoff file present but contains neither an Angela
    #    verdict line nor a Shipping Decision section at all — a HOLD report
    #    with a handoff "missing the section". Nothing to compare -> abstain.
    add(
        "synthetic-adversarial-missing-section-001",
        "NO_EVIDENCE",
        {"readable": True, "verdict": "HOLD", "finding_counts": {"artifact_release_hold": 1}},
        {
            "present": True,
            "readable": True,
            "angela_verdict_line": None,
            "shipping_decision_lines": [],
        },
    )

    # 6. Malformed: quality report JSON was truncated mid-parse. Represented
    #    here as "unreadable" since extract.py / the rule under test never
    #    sees raw bytes for synthetic cases, only the already-sanitized
    #    outcome of attempting to parse them.
    add(
        "synthetic-malformed-truncated-json-001",
        "NO_EVIDENCE",
        {"readable": False, "verdict": None, "finding_counts": {}, "error": "truncated JSON"},
        {
            "present": True,
            "readable": True,
            "angela_verdict_line": "Angela verdict: PASS",
            "shipping_decision_lines": ["- Article HTML: ship"],
        },
    )

    # 7. Malformed: quality report parses as JSON but has no "verdict" key.
    add(
        "synthetic-malformed-missing-verdict-key-001",
        "NO_EVIDENCE",
        {"readable": True, "verdict": None, "finding_counts": {"artifact_release_hold": 2}},
        {
            "present": True,
            "readable": True,
            "angela_verdict_line": "Angela verdict: PASS",
            "shipping_decision_lines": ["- Article HTML: ship"],
        },
    )

    # 8. Malformed: handoff file exists but is empty.
    add(
        "synthetic-malformed-empty-handoff-001",
        "NO_EVIDENCE",
        {"readable": True, "verdict": "HOLD", "finding_counts": {"artifact_release_hold": 4}},
        {"present": True, "readable": True, "angela_verdict_line": None, "shipping_decision_lines": []},
    )

    # 9. Tool failure: the handoff file could not be read at all (distinct
    #    from "empty" or "malformed content" — this is an I/O-level failure,
    #    e.g. permission denied or the file vanished mid-read).
    add(
        "synthetic-tool-failure-unreadable-handoff-001",
        "NO_EVIDENCE",
        {"readable": True, "verdict": "HOLD", "finding_counts": {"artifact_release_hold": 1}},
        {"present": True, "readable": False, "angela_verdict_line": None, "shipping_decision_lines": []},
    )

    return cases


def main() -> None:
    """Build the full dataset: real cases from ~/substack (read-only) + synthetic cases."""
    CASES_DIR.mkdir(parents=True, exist_ok=True)

    real_run_ids = find_real_run_ids()
    n_real = len(real_run_ids)
    # "earliest ~third of real runs" by date -> development; the rest -> held-out.
    n_development = round(n_real / 3)

    manifest: list[dict[str, Any]] = []

    for index, (date, run_id) in enumerate(real_run_ids):
        manifest_entry, case_payload = build_real_case_payload(date, run_id)
        manifest_entry["split"] = "development" if index < n_development else "held-out"
        manifest.append(manifest_entry)
        (CASES_DIR / f"{run_id}.json").write_text(
            json.dumps(case_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    for manifest_entry, case_payload in synthetic_cases():
        manifest_entry["split"] = "synthetic"
        manifest.append(manifest_entry)
        (CASES_DIR / f"{manifest_entry['case_id']}.json").write_text(
            json.dumps(case_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    DATASET_DIR.joinpath("manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"real cases: {n_real} (development={n_development}, held-out={n_real - n_development})")
    print(f"synthetic cases: {len(manifest) - n_real}")
    print(f"total cases written: {len(manifest)}")


if __name__ == "__main__":
    main()
