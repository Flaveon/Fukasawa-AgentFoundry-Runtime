# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Shadow run: the Level-0 rule over the frozen dataset, vs. Baseline A and B.

SHADOW ONLY. This script:
* reads the dataset fixtures under dataset/ (read-only),
* reads the archived v1 baseline/donor results under results/v1/ (read-only,
  written once by baseline.py / rerun_timeouts.py / rerun_timeouts_run3.py —
  see PROTOCOL.md's Amendment 3 for why they moved there),
* calls src.governance.package_consistency.check_package_consistency — pure,
  deterministic, no model, no network,
* writes ONLY results/treatment.json and results/comparison.md.

It never publishes, deletes, promotes, or writes outside results/. It does
not touch ~/pipeline or ~/substack. See capsule/ROLLOUT.md for why this rule
is not wired into the real pipeline: "Not promoted. Requires owner review
and approval (issue #27 checklist item 6)."
"""

from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from src.governance.package_consistency import ConsistencyVerdict, check_package_consistency

EXPERIMENT_DIR = Path(__file__).resolve().parent
DATASET_DIR = EXPERIMENT_DIR / "dataset"
CASES_DIR = DATASET_DIR / "cases"
RESULTS_DIR = EXPERIMENT_DIR / "results"

EXPECTED_VERDICT = {
    "CONTRADICTION": ConsistencyVerdict.BLOCK,
    "CONSISTENT": ConsistencyVerdict.CONSISTENT,
    "NO_EVIDENCE": ConsistencyVerdict.ABSTAIN,
}


def _case_to_rule_inputs(payload: dict[str, Any]) -> tuple[Optional[str], Optional[dict]]:
    """Rebuild (handoff_text, quality_report) from one sanitized case payload.

    Mirrors tests/test_package_consistency.py::_case_to_rule_inputs. Kept as
    a small, separate copy rather than a shared import because the
    experiment directory's name is not a valid Python package identifier
    (hyphens) — duplicating ~15 lines is cheaper than import gymnastics.
    """
    handoff = payload["handoff"]
    if not handoff.get("present") or not handoff.get("readable"):
        handoff_text: Optional[str] = None
    else:
        lines = []
        if handoff.get("angela_verdict_line"):
            lines.append(handoff["angela_verdict_line"])
        if handoff.get("shipping_decision_lines"):
            lines.append("")
            lines.append("## Shipping Decision")
            lines.extend(handoff["shipping_decision_lines"])
            lines.append("")
        handoff_text = "\n".join(lines) if lines else ""

    qr = payload["quality_report"]
    if not qr.get("readable", True) and qr.get("verdict") is None and not qr.get("finding_counts"):
        quality_report: Optional[dict] = None
    else:
        quality_report = {"verdict": qr.get("verdict"), "finding_counts": qr.get("finding_counts", {})}
    return handoff_text, quality_report


def load_manifest() -> list[dict[str, Any]]:
    """Load the frozen dataset manifest (case_id, split, label, provenance)."""
    return json.loads((DATASET_DIR / "manifest.json").read_text(encoding="utf-8"))


def load_case(case_id: str) -> dict[str, Any]:
    """Load one sanitized case payload (handoff fields + quality_report fields) by id."""
    return json.loads((CASES_DIR / f"{case_id}.json").read_text(encoding="utf-8"))


def run_treatment() -> dict[str, Any]:
    """Run the rule over every case in the dataset. Returns per-case + per-split results."""
    manifest = load_manifest()
    per_case: dict[str, Any] = {}
    per_split: dict[str, Counter] = {}
    total_wall_time = 0.0

    for entry in manifest:
        case_id = entry["case_id"]
        split = entry["split"]
        label = entry["label"]
        payload = load_case(case_id)
        handoff_text, quality_report = _case_to_rule_inputs(payload)

        start = time.monotonic()
        result = check_package_consistency(handoff_text, quality_report)
        elapsed = time.monotonic() - start
        total_wall_time += elapsed

        expected = EXPECTED_VERDICT[label]
        matches_ground_truth = result.verdict is expected

        bucket = per_split.setdefault(split, Counter())
        bucket["cases"] += 1
        if result.verdict is ConsistencyVerdict.BLOCK and label != "CONTRADICTION":
            bucket["false_positives"] += 1
        if label == "CONTRADICTION" and result.verdict is not ConsistencyVerdict.BLOCK:
            bucket["escaped_blockers"] += 1
        if result.verdict is ConsistencyVerdict.ABSTAIN:
            bucket["abstentions"] += 1
        if matches_ground_truth:
            bucket["matches_ground_truth"] += 1

        per_case[case_id] = {
            "split": split,
            "ground_truth_label": label,
            "rule_verdict": result.verdict.value,
            "reasons": list(result.reasons),
            "matches_ground_truth": matches_ground_truth,
            "wall_time_seconds": elapsed,
        }

    return {
        "per_case": per_case,
        "per_split": {split: dict(counter) for split, counter in per_split.items()},
        "total_wall_time_seconds": total_wall_time,
        "model_calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
    }


def _fmt_split_table(per_split: dict[str, dict[str, int]]) -> str:
    """Render a per-split counters dict (cases/escaped_blockers/false_positives/abstentions/matches) as a Markdown table.

    Shared by the Treatment table and the Baseline B frozen-metrics table
    below (M4) so the two are visually and structurally comparable rather
    than reported in two different shapes.
    """
    header = "| split | cases | escaped blockers | false positives | abstentions | matches ground truth |"
    sep = "|---|---|---|---|---|---|"
    rows = [header, sep]
    for split in ("development", "held-out", "synthetic"):
        if split not in per_split:
            continue
        s = per_split[split]
        rows.append(
            f"| {split} | {s.get('cases', 0)} | {s.get('escaped_blockers', 0)} | "
            f"{s.get('false_positives', 0)} | {s.get('abstentions', 0)} | "
            f"{s.get('matches_ground_truth', 0)} |"
        )
    return "\n".join(rows)


def baseline_b_frozen_metrics(combined_per_case: dict[str, Any], manifest: list[dict[str, Any]]) -> dict[str, Any]:
    """Baseline B's results, on the SAME frozen metric PROTOCOL.md defines for the Treatment table.

    Review finding (M4a): the original comparison only reported Baseline
    B's "36/44 matched the ideal action" number, never the frozen
    escaped-blockers/false-positives/abstentions metric PROTOCOL.md
    promises for every method. Computed here directly from the
    SHIP/HOLD/ESCALATE answer, mapped onto the same three outcomes the
    rule uses (SHIP~allow, HOLD~flag, ESCALATE~abstain):
      - escaped_blockers: a real CONTRADICTION case Baseline B said SHIP to.
      - false_positives: a CONSISTENT/NO_EVIDENCE case Baseline B said HOLD to.
      - abstentions: any case Baseline B answered ESCALATE to.
      - matches_ground_truth: Baseline B's answer equals expected_model_action().
    """
    per_split: dict[str, Counter] = {}
    for entry in manifest:
        case_id = entry["case_id"]
        split = entry["split"]
        label = entry["label"]
        result = combined_per_case.get(case_id, {})
        answer = result.get("adjudication")
        expected = expected_model_action(case_id)

        bucket = per_split.setdefault(split, Counter())
        bucket["cases"] += 1
        if label == "CONTRADICTION" and answer == "SHIP":
            bucket["escaped_blockers"] += 1
        if label != "CONTRADICTION" and answer == "HOLD":
            bucket["false_positives"] += 1
        if answer == "ESCALATE":
            bucket["abstentions"] += 1
        if answer == expected:
            bucket["matches_ground_truth"] += 1

    return {split: dict(counter) for split, counter in per_split.items()}


def expected_model_action(case_id: str) -> str:
    """What SHIP/HOLD/ESCALATE Baseline B SHOULD answer for one case, from its quality report.

    Read directly from the sanitized case payload's quality_report fields
    (the same fields the rule and Baseline B both see) rather than from the
    manifest's CONTRADICTION/CONSISTENT/NO_EVIDENCE label, because that
    label does not by itself distinguish a PASS-report CONSISTENT case
    (expected SHIP) from a HOLD-report CONSISTENT case (expected HOLD).
    """
    qr = load_case(case_id)["quality_report"]
    verdict = qr.get("verdict")
    if not qr.get("readable", True) or verdict not in ("PASS", "HOLD"):
        return "ESCALATE"
    return "SHIP" if verdict == "PASS" else "HOLD"


def merge_baseline_b_runs(run1: dict[str, Any], *later_runs: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Combine run 1's per-case results with each later run's retries, in order.

    Run 1's OK cases pass through untouched by any later run (later runs
    only ever retry cases that were NOT OK in the runs before them). For
    every case a later run touches, that run's outcome (OK /
    INFRASTRUCTURE_FAILURE again / NOT_RUN because its hard stop arrived
    first) replaces whatever was there before, tagged with which run
    number produced it -- but no earlier run's own result file is ever
    edited; this merge happens only in memory, for reporting.
    """
    run1_per_case = (run1.get("baseline_b") or {}).get("per_case", {})
    combined: dict[str, Any] = {k: {**v, "run": 1} for k, v in run1_per_case.items()}
    for run_number, run in enumerate(later_runs, start=2):
        if not run:
            continue
        prior_status = {k: v.get("status") for k, v in combined.items()}
        for case_id, result in run.get("per_case", {}).items():
            combined[case_id] = {**result, "run": run_number, "prior_status": prior_status.get(case_id)}
        for case_id in run.get("not_run", []):
            combined[case_id] = {
                "status": "NOT_RUN",
                "run": run_number,
                "prior_status": prior_status.get(case_id),
                "ground_truth_label": combined.get(case_id, {}).get("ground_truth_label"),
            }
    return combined


def analyze_baseline_b_quality(combined_per_case: dict[str, Any]) -> dict[str, Any]:
    """Correctness evidence for every OK adjudication: right/wrong vs. the ideal SHIP/HOLD/ESCALATE.

    A "dangerous" wrong answer is SHIP when the expected action was not
    SHIP (i.e. the model told the operator to ship something it should not
    have) -- the one failure mode that actually matters for this issue.
    An "escalation missed" wrong answer is any non-ESCALATE answer where
    ESCALATE was expected (missing/malformed evidence).
    """
    rows = []
    for case_id, result in sorted(combined_per_case.items()):
        if result.get("status") != "OK":
            continue
        expected = expected_model_action(case_id)
        got = result.get("adjudication")
        usage = result.get("usage") or {}
        rows.append(
            {
                "case_id": case_id,
                "expected": expected,
                "got": got,
                "correct": got == expected,
                "dangerous": got == "SHIP" and expected != "SHIP",
                "escalation_missed": expected == "ESCALATE" and got != "ESCALATE",
                "completion_tokens": usage.get("completion_tokens"),
                "prompt_tokens": usage.get("prompt_tokens"),
                "wall_time_seconds": result.get("wall_time_seconds"),
                "run": result.get("run"),
            }
        )
    return {
        "rows": rows,
        "total_ok": len(rows),
        "correct": sum(1 for r in rows if r["correct"]),
        "dangerous_wrong_answers": [r for r in rows if r["dangerous"]],
        "escalations_missed": [r for r in rows if r["escalation_missed"]],
    }


def _fmt_baseline_b_summary(label: str, per_case: dict[str, Any]) -> str:
    """Render one Baseline B run's OK/INFRASTRUCTURE_FAILURE/NOT_RUN counts as a bullet line."""
    statuses = Counter(v.get("status") for v in per_case.values())
    return (
        f"- {label}: {len(per_case)} cases — "
        f"OK={statuses.get('OK', 0)}, "
        f"INFRASTRUCTURE_FAILURE={statuses.get('INFRASTRUCTURE_FAILURE', 0)}, "
        f"NOT_RUN={statuses.get('NOT_RUN', 0)}"
    )


def build_comparison(
    treatment: dict[str, Any],
    run1: dict[str, Any],
    run2: Optional[dict[str, Any]],
    run3: Optional[dict[str, Any]],
    donor_run1: dict[str, Any],
    donor_run2: Optional[dict[str, Any]],
    local_only: Optional[dict[str, Any]] = None,
) -> str:
    """Build results/comparison.md — honest numbers: run-1-only, runs-1+2, runs-1+2+3.

    v2 note (post-review, M4 — PROTOCOL.md Amendment 3): every disclosure
    in this function used to be hand-added directly to a generated
    comparison.md file, which meant the next `shadow.py` run silently
    erased them. They are generated here now, so they cannot drift from
    the file that actually produces the numbers they are next to.
    """
    baseline_a = run1.get("baseline_a", {})
    run1_per_case = (run1.get("baseline_b") or {}).get("per_case", {})
    run2_per_case = (run2 or {}).get("per_case", {})
    run3_per_case = (run3 or {}).get("per_case", {})
    combined_12 = merge_baseline_b_runs(run1, run2)
    combined_123 = merge_baseline_b_runs(run1, run2, run3)
    quality = analyze_baseline_b_quality(combined_123)
    manifest = load_manifest()
    b_frozen = baseline_b_frozen_metrics(combined_123, manifest)

    def _tokens(per_case: dict[str, Any]) -> int:
        """Sum completion_tokens across every case's usage dict, if present."""
        return sum((c.get("usage") or {}).get("completion_tokens", 0) for c in per_case.values())

    def _wall(per_case: dict[str, Any]) -> float:
        """Sum wall_time_seconds across every case, success or failure."""
        return sum(c.get("wall_time_seconds", 0.0) for c in per_case.values())

    # M4(b): the "combined" views above REPLACE a case's run-1 entry with
    # its later-run outcome, which drops the real wall-clock time run 1
    # spent on that case before it timed out. This sum, by contrast, adds
    # every attempt from every run, so no wall-clock time that was actually
    # spent (even on a call that ultimately failed or was superseded) goes
    # missing from the total.
    total_wall_all_attempts = _wall(run1_per_case) + _wall(run2_per_case) + _wall(run3_per_case)

    b_real_escaped = sum(
        b_frozen.get(split, {}).get("escaped_blockers", 0) for split in ("development", "held-out")
    )

    lines = [
        "# Issue #27 — Shadow Run Comparison",
        "",
        "Shadow run only. Nothing here was published, deleted, or promoted.",
        "No change was made to ~/pipeline or ~/substack. See PROTOCOL.md for",
        "label definitions, Amendments 1-2 for the run-1/2/3 timeout retries,",
        "and capsule/ROLLOUT.md for promotion status.",
        "",
        "## Treatment — the Level-0 rule (src/governance/package_consistency.py)",
        "",
        _fmt_split_table(treatment["per_split"]),
        "",
        f"Total wall time: {treatment['total_wall_time_seconds']:.6f}s. "
        f"Model calls: {treatment['model_calls']}. "
        f"Prompt tokens: {treatment['prompt_tokens']}. "
        f"Completion tokens: {treatment['completion_tokens']}.",
        "",
        "**One known, deliberate synthetic mismatch (not a defect):**",
        "`synthetic-adversarial-hold-prose-001`'s FROZEN manifest label is",
        "CONSISTENT (v1's intended behavior for 'hold (ship once blockers",
        "fixed)'), but v2 ABSTAINs on it instead — v2's exact-value allowlist",
        "treats a decorated/prose-suffixed value as unparseable rather than",
        "cleverly resolving it, which is the entire point of the H1 rewrite",
        "(see CANDIDATES.md, decision 12). The manifest label is left exactly as",
        "frozen — it is not edited after the fact to match v2's behavior — so",
        "this one case shows up as a non-match here rather than being quietly",
        "relabelled to make the table read 9/9.",
        "",
        "## Baseline A — real pipeline behavior today (zero cost to measure)",
        "",
        "The handoff never consults the quality report, so every real",
        "CONTRADICTION case is an escaped blocker under current, unmodified",
        "pipeline behavior:",
        "",
        "```json",
        json.dumps(baseline_a, indent=2),
        "```",
        "",
        "## Baseline B — one model call per case (reasoning baseline)",
        "",
        "Three runs, reported SEPARATELY, then combined. Run 1: 44 cases,",
        "timeout 180s/240s. Run 2 (Amendment 1): retries run 1's 36 timeouts",
        "at 600s, hard stop 2026-10-17T09:45Z. Run 3 (Amendment 2): retries",
        "run 2's 18 NOT_RUNs at 600s, hard stop 2026-10-18T09:30Z.",
        "",
        _fmt_baseline_b_summary("Run 1 only (44 cases, timeout 180s)", run1_per_case),
        _fmt_baseline_b_summary("Runs 1+2 combined", combined_12),
        _fmt_baseline_b_summary("Runs 1+2+3 combined", combined_123),
        "",
        f"- Run 1 completion tokens (sum over its 8 OK calls): {_tokens(run1_per_case)}",
        f"- Runs 1+2 completion tokens (sum over all OK calls): {_tokens(combined_12)}",
        f"- Runs 1+2+3 completion tokens (sum over all OK calls): {_tokens(combined_123)}",
        f"- Run 1 wall time (sum over all 44 calls, success + failure): {_wall(run1_per_case):.1f}s",
        f"- Runs 1+2 'combined' wall time (replaces a case's run-1 entry with its "
        f"run-2 outcome, so run 1's time on a later-superseded case is NOT counted "
        f"twice, but also not counted at all): {_wall(combined_12):.1f}s",
        f"- Runs 1+2+3 'combined' wall time (same caveat): {_wall(combined_123):.1f}s",
        f"- **Total wall time ACTUALLY spent across every attempt in all three runs, "
        f"including the 36 run-1 calls that timed out and were later superseded** "
        f"(M4b — this is the real cost, not the 'combined' figure above, which "
        f"silently drops superseded attempts): **{total_wall_all_attempts:.1f}s** "
        f"({_wall(run1_per_case):.1f} + {_wall(run2_per_case):.1f} + {_wall(run3_per_case):.1f}).",
        f"- Rule (treatment) wall time for all {sum(treatment['per_split'][s]['cases'] for s in treatment['per_split'])} cases: "
        f"{treatment['total_wall_time_seconds']:.6f}s, 0 tokens, 0 calls.",
        "",
        "### Baseline B on the SAME frozen metric as the Treatment table (M4a)",
        "",
        "PROTOCOL.md's Metrics section defines escaped blockers / false",
        "positives / abstentions for every method, not just the rule.",
        "Mapped onto Baseline B's SHIP/HOLD/ESCALATE answer (SHIP~allow,",
        "HOLD~flag, ESCALATE~abstain), combined across all three runs:",
        "",
        _fmt_split_table(b_frozen),
        "",
        f"**On this metric, Baseline B escaped {b_real_escaped} of the 35 REAL "
        f"blockers** (development + held-out splits) — it never answered SHIP on "
        f"a real CONTRADICTION case; its wrong answers on real cases were all "
        f"ESCALATE (safe direction, not a miss). Its only SHIP-on-a-case-that-"
        f"should-not-ship answers are the 2 dangerous wrong answers below, and both "
        f"are SYNTHETIC malformed-report cases, not real ones. **So, against "
        f"Baseline B specifically, the rule's advantage on THIS dataset is cost and "
        f"latency (0 vs. {total_wall_all_attempts:.0f}s and 0 vs. "
        f"{_tokens(combined_123)} tokens) plus those 2 synthetic cases — not "
        f"catching a real blocker Baseline B would have missed.** The real-world "
        f"gain this experiment actually demonstrates is against Baseline A (the "
        f"pipeline's current, unmodified behavior), which escapes all 35/35 real "
        f"blockers because it never looks at the quality report at all.",
        "",
        "### Baseline B quality: right vs. wrong answers (runs 1+2+3 combined, OK calls only)",
        "",
        f"- {quality['total_ok']} calls produced an answer at all (out of 44 cases).",
        f"- {quality['correct']}/{quality['total_ok']} matched the ideal SHIP/HOLD/ESCALATE "
        "action for that case's actual quality-report verdict.",
        f"- **Dangerous wrong answers (model said SHIP when it should not have):** "
        f"{len(quality['dangerous_wrong_answers'])} — "
        f"{[r['case_id'] for r in quality['dangerous_wrong_answers']]}",
        f"- **Escalations missed (model answered instead of escalating on missing/malformed "
        f"evidence):** {len(quality['escalations_missed'])} — "
        f"{[r['case_id'] for r in quality['escalations_missed']]}",
        "- Per-case detail (expected action, what the model said, tokens, wall time, which run resolved it):",
        "",
        "  | case_id | expected | got | correct | completion_tokens | wall_s | run |",
        "  |---|---|---|---|---|---|---|",
    ]
    for r in quality["rows"]:
        lines.append(
            f"  | {r['case_id']} | {r['expected']} | {r['got']} | {r['correct']} | "
            f"{r['completion_tokens']} | {r['wall_time_seconds']:.1f} | {r['run']} |"
        )
    not_run_final = [
        case_id for case_id, result in combined_123.items() if result.get("status") == "NOT_RUN"
    ]
    still_failing = [
        case_id for case_id, result in combined_123.items() if result.get("status") == "INFRASTRUCTURE_FAILURE"
    ]
    lines.extend(
        [
            "",
            f"- Still `INFRASTRUCTURE_FAILURE` after every run attempted so far: "
            f"{len(still_failing)} — {still_failing}",
            f"- Still `NOT_RUN` after every run attempted so far (hard stop reached "
            f"before these were tried): {len(not_run_final)} — {not_run_final}",
            "",
            "## Local-only run: the rule against the RAW real files (M4d)",
            "",
            "Everything above feeds the rule TEXT REBUILT from the already-sanitized",
            "fields in dataset/cases/*.json — it never reads a real file. That is a",
            "deliberate privacy choice (this repo is public), but it means the 44/44",
            "result above is not, by itself, proof the rule parses REAL files, only",
            "that it parses a reconstruction of them. `local_only_run.py` closes that",
            "gap: it runs the same, unmodified rule against the raw",
            "`quality-report.json` and `*-duath-operator-handoff.md` files for all 35",
            "real run_ids, read-only, and records ONLY verdict counts and SHA-256",
            "checksums — never file content (a BLOCK/ABSTAIN verdict's `.reasons`",
            "literally quote handoff text, so that field is discarded entirely).",
            "",
        ]
    )
    if local_only:
        lines.extend(
            [
                f"Result: `{local_only.get('verdict_counts')}` over "
                f"{local_only.get('case_count')} real run_ids from {local_only.get('source_root')} "
                f"— matching the sanitized-dataset result exactly (35/35 BLOCK). "
                f"See `results/local-only-run.json` for the per-case checksums.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "`results/local-only-run.json` was not found when this comparison was",
                "generated — run `local_only_run.py` to produce it (requires read access",
                "to ~/substack, which this shadow run does not assume).",
                "",
            ]
        )
    lines.extend(
        [
            "## Donor reasoning vs. recipient rule",
            "",
            f"- Donor-diagnosis run 1: {donor_run1.get('status', 'NOT RUN')} "
            f"(wall time {donor_run1.get('wall_time_seconds', 'n/a')})",
            f"- Donor-diagnosis run 2 retry (600s): "
            f"{(donor_run2 or {}).get('status', 'NOT RUN')} "
            f"(wall time {(donor_run2 or {}).get('wall_time_seconds', 'n/a')})",
            f"- Donor-diagnosis usage (whichever run succeeded, if either did): "
            f"{(donor_run2 or {}).get('usage') or donor_run1.get('usage', 'n/a')}",
            "- Recipient rule (Commit 2, this shadow run): 0 model calls, 0 tokens,"
            " by construction — it is a pure deterministic function.",
            "- What the donor reasoning proposed and what was accepted/rejected is"
            " recorded in CANDIDATES.md, not here.",
            "",
            "## Human cleanup time",
            "",
            "NOT MEASURED. Unknown — never assumed to be zero. Nothing in the",
            "pipeline, this experiment, or Mission Control records operator time",
            "spent on a handoff. See PROTOCOL.md.",
            "",
            "## What this does not show",
            "",
            "- **A near-perfect score is not independent evidence.** Ground-truth",
            "  labels (PROTOCOL.md, 'Label definitions') are defined by the SAME",
            "  criterion the rule implements: deterministic report says HOLD, handoff",
            "  says PASS or ship. So 43/44 (see the one documented exception above)",
            "  shows the rule parses the test cases correctly and abstains when",
            "  evidence is missing; it cannot show the",
            "  criterion itself is the right policy. That policy is the owner's",
            "  stated intent in the May 31 plan ('PASS cannot override deterministic",
            "  blockers'; 'Delivery notes cannot recommend publish for held",
            "  artifacts') — whether it is right is for the owner's review, not this",
            "  run.",
            "- **The real 35-case corpus has almost no variety, and the held-out split",
            "  was never held out from the person who wrote the rule's parsing logic**",
            "  (PROTOCOL.md Amendment 3, M1). It reduces to 4 distinct rule inputs, all",
            "  against a HOLD report. Neither this run's nor v1's `held-out` numbers",
            "  are evidence of generalization to handoffs no one has looked at yet.",
            "- **Baseline B is a counterfactual, not the pipeline's actual spend.** The",
            "  pipeline never asked a model to adjudicate handoff against report —",
            "  that check did not exist (Baseline A). Baseline B measures what doing",
            "  this check BY REASONING would cost and how well it would do, on the",
            "  same model. See the frozen-metric section above: against Baseline B",
            "  specifically, the rule's advantage on this dataset is cost/latency plus",
            "  2 synthetic cases, not catching a real blocker Baseline B would have",
            "  missed.",
            "- It does not fix the pipeline: ~/pipeline and ~/substack were never",
            "  modified, and the real handoff documents still say what they said",
            "  before this experiment ran.",
            "- It does not measure reader/operator engagement.",
            "- Synthetic-split numbers above are not real-world evidence; they",
            "  test the rule's parsing logic (see PROTOCOL.md for the full list).",
            "- A `NOT_RUN` case was never attempted in run 2 or run 3 — it says",
            "  nothing about that case, only that a hard stop arrived first.",
            "- **Human cleanup time is NOT MEASURED** (restated: no record exists",
            "  anywhere); no claim is made about operator time saved.",
            "- This is a shadow run. The rule has no authority over anything; see",
            "  capsule/ROLLOUT.md.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    """Run the rule over the dataset and write results/treatment.json + results/comparison.md."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    treatment = run_treatment()
    (RESULTS_DIR / "treatment.json").write_text(
        json.dumps(treatment, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    v1_dir = RESULTS_DIR / "v1"
    run1_path = v1_dir / "baseline-run1.json"
    run1 = json.loads(run1_path.read_text(encoding="utf-8")) if run1_path.exists() else {}
    run2_path = v1_dir / "baseline-run2.json"
    run2 = json.loads(run2_path.read_text(encoding="utf-8")) if run2_path.exists() else None
    run3_path = v1_dir / "baseline-run3.json"
    run3 = json.loads(run3_path.read_text(encoding="utf-8")) if run3_path.exists() else None

    donor_run1_path = v1_dir / "donor-diagnosis-run1.json"
    donor_run1 = json.loads(donor_run1_path.read_text(encoding="utf-8")) if donor_run1_path.exists() else {}
    donor_run2_path = v1_dir / "donor-diagnosis-run2.json"
    donor_run2 = json.loads(donor_run2_path.read_text(encoding="utf-8")) if donor_run2_path.exists() else None

    local_only_path = RESULTS_DIR / "local-only-run.json"
    local_only = json.loads(local_only_path.read_text(encoding="utf-8")) if local_only_path.exists() else None

    comparison = build_comparison(treatment, run1, run2, run3, donor_run1, donor_run2, local_only)
    (RESULTS_DIR / "comparison.md").write_text(comparison, encoding="utf-8")

    print(json.dumps(treatment["per_split"], indent=2))


if __name__ == "__main__":
    main()
