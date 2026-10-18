# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Run the Level-0 rule against the RAW real files under ~/substack, read-only.

M4(d) from the post-review amendment (PROTOCOL.md Amendment 3): the main
shadow run (``shadow.py``) feeds the rule text *rebuilt* from the already-
sanitized fields in ``dataset/cases/*.json`` — it never reads a real
handoff or quality-report file. That rebuilt text happens to be close to
the real shape, but "close to" is not "is". This script closes that gap by
running the exact same rule, unmodified, against the REAL raw files for
every real run_id, read-only, and proves it with checksums rather than
asking anyone to trust that nothing was retyped by hand.

Privacy: this script writes ONLY aggregate verdict counts and per-case
SHA-256 checksums of the two source files it read — never any file
content, never a handoff line, never a quality-report finding. The
`ConsistencyResult.reasons` strings the rule returns for BLOCK/ABSTAIN
verdicts literally quote handoff text, so this script discards `.reasons`
entirely and keeps only `.verdict`. run_id strings are not sensitive here
— they already appear throughout the committed, public `dataset/` and
`results/` directories.

This script is read-only everywhere: it never writes to ~/substack or
~/pipeline, and its own output goes only to `results/local-only-run.json`.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

EXPERIMENT_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EXPERIMENT_DIR / "results"

sys.path.insert(0, str(EXPERIMENT_DIR))
from extract import HOME, SUBSTACK, DEPLOY, deploy_dirname, find_real_run_ids  # noqa: E402

from src.governance.package_consistency import check_package_consistency  # noqa: E402


def _sha256(path: Path) -> str:
    """Return the hex SHA-256 digest of a file's raw bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run() -> dict:
    """Run the rule against every real run_id's RAW files; return the aggregate result."""
    cases = []
    for date, run_id in find_real_run_ids():
        qr_path = DEPLOY / deploy_dirname(date) / run_id / "quality-report.json"
        handoff_path = SUBSTACK / date / "support" / f"{run_id}-duath-operator-handoff.md"

        qr_sha = _sha256(qr_path)
        quality_report = json.loads(qr_path.read_text(encoding="utf-8"))

        handoff_present = handoff_path.exists()
        handoff_sha = _sha256(handoff_path) if handoff_present else None
        handoff_text = (
            handoff_path.read_text(encoding="utf-8", errors="replace") if handoff_present else None
        )

        result = check_package_consistency(handoff_text, quality_report)
        cases.append(
            {
                "run_id": run_id,
                "verdict": result.verdict.value,
                "sha256": {"quality_report": qr_sha, "handoff": handoff_sha},
            }
        )

    verdict_counts: dict[str, int] = {}
    for case in cases:
        verdict_counts[case["verdict"]] = verdict_counts.get(case["verdict"], 0) + 1

    return {
        "note": (
            "Rule run against the RAW real files under ~/substack (read-only), not the "
            "rebuilt text shadow.py feeds it. No file content is stored here, only "
            "verdicts and SHA-256 checksums. See PROTOCOL.md Amendment 3 (M4)."
        ),
        "source_root": "~/substack",  # never the resolved absolute path (it embeds the username)
        "case_count": len(cases),
        "verdict_counts": verdict_counts,
        "cases": cases,
    }


def main() -> None:
    """Run the local-only check and write results/local-only-run.json."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    result = run()
    (RESULTS_DIR / "local-only-run.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result["verdict_counts"], indent=2))


if __name__ == "__main__":
    main()
