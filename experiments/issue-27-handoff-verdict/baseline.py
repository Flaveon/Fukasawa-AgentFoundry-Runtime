# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Baselines A and B for the issue #27 handoff-verdict experiment.

Baseline A — real-world, zero cost to measure: what the pipeline's handoff
actually told the operator, over the real cases. The handoff never consults
the quality report (that is the defect), so every CONTRADICTION-labelled
real case is, by construction, an escaped blocker under current pipeline
behavior.

Baseline B — reasoning baseline: ask the local model, through the repo's
existing ``src.kernel.models.ModelAdapter`` (a FROZEN component — this
script imports it but never edits it), to adjudicate SHIP/HOLD/ESCALATE for
every case in every split, given the same sanitized fields the Level-0 rule
sees. One call per case. The poster passed to ``ModelAdapter`` wraps the
adapter's own ``http_post_json`` to record wall time and the raw response's
``usage`` object, and refuses any URL whose host is not localhost/127.0.0.1
— this script makes no network call anywhere else.

Also runs the donor-diagnosis call: a higher-depth reasoning request over a
few development-split cases plus the relevant pipeline excerpts, asking for
root cause and a minimal deterministic check. Saved separately to
``results/donor-diagnosis.json``; what it proposed is evaluated by hand in
``CANDIDATES.md``.

This script never restarts or reconfigures the llama server (shared user
service). If the server is unreachable, each Baseline B call is recorded as
``INFRASTRUCTURE_FAILURE`` and the run continues; this script then reports
BLOCKED for the part it could not complete, rather than inventing numbers.
"""

from __future__ import annotations

import json
import tempfile
import time
import urllib.parse
from pathlib import Path
from typing import Any

import yaml

from src.kernel.models import ModelAdapter, ModelEndpointRegistry, http_post_json

EXPERIMENT_DIR = Path(__file__).resolve().parent
DATASET_DIR = EXPERIMENT_DIR / "dataset"
RESULTS_DIR = EXPERIMENT_DIR / "results" / "v1"  # v1 is archived; this script only ever reproduces v1

MODEL_ID = "Qwen_Qwen3.5-27B-Q4_K_M.gguf"
ENDPOINT_NAME = "local-llama"
ENDPOINT_URL = "http://localhost:8081"

# Reproduced verbatim in PROTOCOL.md.
BASELINE_B_PROMPT_TEMPLATE = """You are reviewing one Q2C content-pipeline run for a publish decision.

Deterministic quality report for this run:
- verdict: {verdict}
- finding counts by check: {finding_counts}

Operator handoff document for the SAME run:
- Angela verdict line: {angela_verdict_line}
- Shipping Decision lines: {shipping_decision_lines}

Based ONLY on the information above, answer with exactly one word on the
first line: SHIP, HOLD, or ESCALATE. Then, on a second line, give a one
sentence reason.
"""

DONOR_PROMPT = """You are diagnosing a defect in a content-publishing pipeline.

Below are three excerpts from the pipeline's source (q2c_pipeline.py). The
first writes an operator-facing handoff document. The second computes a
deterministic quality verdict for the same run. The third is the
deterministic blocker-detection function the second one calls.

--- build_duath_operator_handoff (writes the operator handoff) ---
{handoff_excerpt}

--- build_package_quality_report (writes quality-report.json) ---
{quality_report_excerpt}

--- html_release_blockers (the deterministic blocker check) ---
{blockers_excerpt}

Here are {n_cases} real run_ids where the quality report said HOLD but the
operator handoff's Shipping Decision said ship / Angela verdict said PASS
for the same run:

{case_summaries}

Question: what is the root cause of this contradiction, in one paragraph?
Then propose the MINIMAL deterministic (non-model) check that would catch
every instance of it, stated precisely enough to implement. Do not propose
a model-based or statistical fix.
"""


def refusing_non_localhost(url: str) -> None:
    """Raise if url's host is not localhost/127.0.0.1. No non-local calls, ever."""
    host = urllib.parse.urlparse(url).hostname
    if host not in ("localhost", "127.0.0.1"):
        raise ValueError(f"refusing non-localhost model endpoint URL: {url!r}")


class RecordingPoster:
    """Wraps http_post_json: records wall time + raw usage, refuses non-local URLs."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def __call__(self, url: str, payload: dict, timeout: float) -> dict:
        refusing_non_localhost(url)
        start = time.monotonic()
        response = http_post_json(url, payload, timeout)
        elapsed = time.monotonic() - start
        self.records.append(
            {
                "url": url,
                "wall_time_seconds": elapsed,
                "usage": response.get("usage"),
            }
        )
        return response


def load_cases() -> dict[str, dict[str, Any]]:
    """Load the manifest + every sanitized case payload."""
    manifest = json.loads((DATASET_DIR / "manifest.json").read_text(encoding="utf-8"))
    cases: dict[str, dict[str, Any]] = {}
    for entry in manifest:
        case_id = entry["case_id"]
        payload = json.loads((DATASET_DIR / "cases" / f"{case_id}.json").read_text(encoding="utf-8"))
        cases[case_id] = {"manifest": entry, "payload": payload}
    return cases


def run_baseline_a(cases: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """What the pipeline's real handoff told the operator, over real cases only.

    The handoff never consults the quality report (the defect itself), so
    every CONTRADICTION-labelled real case is an escaped blocker under
    current, unmodified pipeline behavior. This costs nothing to measure:
    no model call, no new computation — just reading the label already
    computed from the pipeline's own two real artifacts.
    """
    per_split: dict[str, dict[str, Any]] = {}
    for case_id, case in cases.items():
        if case["manifest"]["provenance"]["type"] != "real":
            continue
        split = case["manifest"]["split"]
        label = case["manifest"]["label"]
        bucket = per_split.setdefault(
            split, {"cases": 0, "escaped_blockers": 0, "case_ids_escaped": []}
        )
        bucket["cases"] += 1
        if label == "CONTRADICTION":
            bucket["escaped_blockers"] += 1
            bucket["case_ids_escaped"].append(case_id)
    return per_split


def build_prompt(payload: dict[str, Any]) -> str:
    """Render the Baseline B prompt for one sanitized case payload."""
    qr = payload["quality_report"]
    ho = payload["handoff"]
    return BASELINE_B_PROMPT_TEMPLATE.format(
        verdict=qr.get("verdict"),
        finding_counts=qr.get("finding_counts"),
        angela_verdict_line=ho.get("angela_verdict_line"),
        shipping_decision_lines=ho.get("shipping_decision_lines"),
    )


def parse_adjudication(text: str) -> str:
    """Pull SHIP / HOLD / ESCALATE out of the model's first line, or UNPARSEABLE."""
    first_line = text.strip().splitlines()[0].strip().upper() if text.strip() else ""
    for word in ("SHIP", "HOLD", "ESCALATE"):
        if word in first_line:
            return word
    return "UNPARSEABLE"


def build_registry() -> ModelEndpointRegistry:
    """Build a registry from a throwaway FUKASAWA_HOME-style model_endpoints.yaml."""
    fukasawa_home = Path(tempfile.mkdtemp(prefix="fukasawa-home-baseline-"))
    config_path = fukasawa_home / "model_endpoints.yaml"
    config_path.write_text(
        yaml.safe_dump({"endpoints": {ENDPOINT_NAME: {"kind": "llamacpp", "url": ENDPOINT_URL}}}),
        encoding="utf-8",
    )
    return ModelEndpointRegistry.from_config(config_path)


def load_existing_results() -> dict[str, Any]:
    """Load a prior (possibly partial) results/baseline.json, or an empty skeleton.

    Baseline B makes 44 blocking HTTP calls to a local reasoning model that
    emits a chain-of-thought before its answer (confirmed: an 8s round trip
    for a two-word "Say OK" prompt against a 105-token response) -- a full
    run can take tens of minutes. This run is checkpointed after every
    single case specifically so an interruption never discards completed
    work; resuming re-reads whatever was last written and only calls the
    model for cases that are not yet recorded with status "OK".
    """
    path = RESULTS_DIR / "baseline-run1.json"
    if not path.exists():
        return {"baseline_a": {}, "baseline_b": {"per_case": {}, "infrastructure_failures": 0, "total_calls": 0}}
    return json.loads(path.read_text(encoding="utf-8"))


def write_checkpoint(baseline_a: dict, baseline_b_per_case: dict, infra_failures: int) -> None:
    """Overwrite results/baseline.json with the current accumulated state."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "baseline-run1.json").write_text(
        json.dumps(
            {
                "model": MODEL_ID,
                "endpoint": ENDPOINT_URL,
                "baseline_a": baseline_a,
                "baseline_b": {
                    "per_case": baseline_b_per_case,
                    "infrastructure_failures": infra_failures,
                    "total_calls": len(baseline_b_per_case),
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def run_baseline_b(
    cases: dict[str, dict[str, Any]],
    registry: ModelEndpointRegistry,
    baseline_a: dict[str, Any],
    existing_per_case: Optional[dict[str, Any]] = None,
) -> tuple[dict[str, Any], int]:
    """One adjudication call per case, all cases, all splits. Returns (per_case, infra_failures).

    Resumable: any case already present in ``existing_per_case`` with
    status "OK" is kept as-is and NOT re-called. Every other case (missing,
    or previously INFRASTRUCTURE_FAILURE) is called fresh, and the full
    accumulated result is checkpointed to results/baseline.json after each
    one -- so killing this process never loses more than the one call that
    was in flight at the time.
    """
    poster = RecordingPoster()
    adapter = ModelAdapter(registry=registry, poster=poster)
    per_case: dict[str, Any] = dict(existing_per_case or {})
    infra_failures = sum(1 for v in per_case.values() if v.get("status") == "INFRASTRUCTURE_FAILURE")
    total = len(cases)
    already_ok = sum(1 for v in per_case.values() if v.get("status") == "OK")
    print(f"Baseline B: {already_ok}/{total} cases already OK from a prior run; resuming the rest.", flush=True)

    for index, (case_id, case) in enumerate(sorted(cases.items()), start=1):
        if per_case.get(case_id, {}).get("status") == "OK":
            continue  # already have a good answer for this case; do not re-call
        was_retried = case_id in per_case  # previously recorded as INFRASTRUCTURE_FAILURE
        prompt = build_prompt(case["payload"])
        print(f"Baseline B: calling model for case {index}/{total} ({case_id})...", flush=True)
        start = time.monotonic()
        try:
            result = adapter.execute(
                {
                    "endpoint": ENDPOINT_NAME,
                    "model": MODEL_ID,
                    "prompt": prompt,
                    "temperature": 0,
                    "timeout": 180,
                }
            )
        except Exception as exc:  # noqa: BLE001 - adapters are documented not to raise,
            # but this script treats any unexpected exception as an
            # infrastructure failure rather than letting it abort the run.
            elapsed = time.monotonic() - start
            infra_failures += 1
            per_case[case_id] = {
                "status": "INFRASTRUCTURE_FAILURE",
                "error": str(exc),
                "wall_time_seconds": elapsed,
                "ground_truth_label": case["manifest"]["label"],
                "retried_after_prior_infrastructure_failure": was_retried,
            }
            write_checkpoint(baseline_a, per_case, infra_failures)
            print(f"Baseline B: case {index}/{total} ({case_id}) -> INFRASTRUCTURE_FAILURE "
                  f"({exc}) after {elapsed:.1f}s", flush=True)
            continue
        elapsed = time.monotonic() - start
        if not result.ok:
            infra_failures += 1
            per_case[case_id] = {
                "status": "INFRASTRUCTURE_FAILURE",
                "error": result.note,
                "wall_time_seconds": elapsed,
                "ground_truth_label": case["manifest"]["label"],
                "retried_after_prior_infrastructure_failure": was_retried,
            }
            write_checkpoint(baseline_a, per_case, infra_failures)
            print(f"Baseline B: case {index}/{total} ({case_id}) -> INFRASTRUCTURE_FAILURE "
                  f"({result.note}) after {elapsed:.1f}s", flush=True)
            continue
        text = result.outputs.get("response", "")
        usage = poster.records[-1]["usage"] if poster.records else None
        per_case[case_id] = {
            "status": "OK",
            "adjudication": parse_adjudication(text),
            "raw_response_text": text,
            "usage": usage,
            "wall_time_seconds": elapsed,
            "ground_truth_label": case["manifest"]["label"],
            "split": case["manifest"]["split"],
            "retried_after_prior_infrastructure_failure": was_retried,
        }
        write_checkpoint(baseline_a, per_case, infra_failures)
        print(f"Baseline B: case {index}/{total} ({case_id}) -> {per_case[case_id]['adjudication']} "
              f"in {elapsed:.1f}s", flush=True)
    return per_case, infra_failures


def run_donor_diagnosis(cases: dict[str, dict[str, Any]], registry: ModelEndpointRegistry) -> dict[str, Any]:
    """One higher-depth reasoning call: root cause + minimal deterministic check proposal."""
    dev_cases = [
        c for c in cases.values()
        if c["manifest"]["split"] == "development" and c["manifest"]["label"] == "CONTRADICTION"
    ][:3]
    summaries = []
    for case in dev_cases:
        qr = case["payload"]["quality_report"]
        ho = case["payload"]["handoff"]
        summaries.append(
            f"- {case['manifest']['case_id']}: quality-report verdict={qr.get('verdict')} "
            f"findings={qr.get('finding_counts')} | handoff Angela={ho.get('angela_verdict_line')} "
            f"shipping={ho.get('shipping_decision_lines')}"
        )

    handoff_excerpt = (
        'lines = [\n'
        '    "# Duath Operator Handoff", "",\n'
        '    f"Topic: {topic_plan[\'topic\']}",\n'
        '    f"Angela verdict: {angela_result.get(\'pass_fail\', \'UNKNOWN\')}",\n'
        '    "", "## Shipping Decision",\n'
        '    f"- Article HTML: {\'ship\' if scope.get(\'article_html\', {}).get(\'ships\', True) else \'hold\'}",\n'
        '    f"- Visual support: {\'ship\' if scope.get(\'visual_support\', {}).get(\'ships\', True) else \'hold\'}",\n'
        '    f"- Interactive tool: {\'ship\' if tool_ships else \'do not ship\'}",\n'
        ']'
    )
    quality_report_excerpt = (
        'verdict = "PASS" if not findings else "HOLD"\n'
        'return {"run_id": run_id, "verdict": verdict, "findings": findings, ...}'
    )
    blockers_excerpt = (
        'def html_release_blockers(filename, content):\n'
        '    # returns a list of blocker strings: pending-QC label, placeholder href="#",\n'
        '    # placeholder image URL, unevidenced "100% success rate" claim, tool missing\n'
        '    # inputs/script, etc. Feeds build_package_quality_report()\'s findings.'
    )

    prompt = DONOR_PROMPT.format(
        handoff_excerpt=handoff_excerpt,
        quality_report_excerpt=quality_report_excerpt,
        blockers_excerpt=blockers_excerpt,
        n_cases=len(dev_cases),
        case_summaries="\n".join(summaries),
    )

    poster = RecordingPoster()
    adapter = ModelAdapter(registry=registry, poster=poster)
    start = time.monotonic()
    try:
        result = adapter.execute(
            {
                "endpoint": ENDPOINT_NAME,
                "model": MODEL_ID,
                "prompt": prompt,
                "temperature": 0,
                "timeout": 240,
            }
        )
    except Exception as exc:  # noqa: BLE001 - same rationale as run_baseline_b.
        elapsed = time.monotonic() - start
        return {
            "status": "INFRASTRUCTURE_FAILURE",
            "error": str(exc),
            "wall_time_seconds": elapsed,
            "prompt": prompt,
            "cases_used": [c["manifest"]["case_id"] for c in dev_cases],
        }
    elapsed = time.monotonic() - start
    if not result.ok:
        return {
            "status": "INFRASTRUCTURE_FAILURE",
            "error": result.note,
            "wall_time_seconds": elapsed,
            "prompt": prompt,
            "cases_used": [c["manifest"]["case_id"] for c in dev_cases],
        }
    return {
        "status": "OK",
        "prompt": prompt,
        "response": result.outputs.get("response", ""),
        "usage": poster.records[-1]["usage"] if poster.records else None,
        "wall_time_seconds": elapsed,
        "cases_used": [c["manifest"]["case_id"] for c in dev_cases],
    }


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    cases = load_cases()

    baseline_a = run_baseline_a(cases)
    print("Baseline A (real-world, current pipeline behavior):", flush=True)
    print(json.dumps(baseline_a, indent=2), flush=True)

    existing = load_existing_results()
    registry = build_registry()
    baseline_b_per_case, infra_failures = run_baseline_b(
        cases, registry, baseline_a, existing_per_case=existing.get("baseline_b", {}).get("per_case", {})
    )
    write_checkpoint(baseline_a, baseline_b_per_case, infra_failures)
    print(f"Baseline B: {len(baseline_b_per_case)} calls, {infra_failures} infrastructure failures", flush=True)

    donor_path = RESULTS_DIR / "donor-diagnosis-run1.json"
    existing_donor = json.loads(donor_path.read_text(encoding="utf-8")) if donor_path.exists() else None
    if existing_donor and existing_donor.get("status") == "OK":
        print("Donor diagnosis: already OK from a prior run; not re-calling.", flush=True)
    else:
        donor = run_donor_diagnosis(cases, registry)
        donor_path.write_text(json.dumps(donor, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Donor diagnosis status: {donor['status']}", flush=True)


if __name__ == "__main__":
    main()
