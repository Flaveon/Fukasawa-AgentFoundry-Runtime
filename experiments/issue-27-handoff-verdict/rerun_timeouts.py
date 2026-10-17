# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Amendment 1 run 2: re-ask ONLY the cases that timed out in baseline run 1.

See PROTOCOL.md's "Amendment 1 (2026-10-17)" section, which this script
implements exactly:

* Re-asks ONLY the 36 cases recorded `INFRASTRUCTURE_FAILURE` in
  ``results/baseline-run1.json`` (the 8 real ``OK`` answers from run 1 are
  left untouched -- they are not re-called).
* One donor-diagnosis retry, done FIRST, before any case re-ask.
* Same prompt text, same model, same ``temperature: 0`` as run 1. The only
  changed variable is ``timeout``: 600s instead of 180s/240s.
* Calls are sequential, never concurrent.
* Run 1's result files are never opened for writing by this script. This
  script writes ONLY ``results/baseline-run2.json`` and
  ``results/donor-diagnosis-run2.json``.
* HARD STOP: no model call may start after 09:45 UTC on 2026-10-17 (the
  owner's content pipeline needs this same llama.cpp server at 10:00 UTC).
  Checked with ``datetime.now(timezone.utc)`` before every single call --
  not estimated by hand. Any case not reached before the deadline is
  recorded ``NOT_RUN``, a status distinct from both ``OK`` and
  ``INFRASTRUCTURE_FAILURE``.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.kernel.models import ModelAdapter

from baseline import (  # reuse run 1's exact prompt/registry/poster code, unmodified
    DONOR_PROMPT,
    ENDPOINT_NAME,
    MODEL_ID,
    RecordingPoster,
    build_prompt,
    build_registry,
    load_cases,
    parse_adjudication,
)

EXPERIMENT_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EXPERIMENT_DIR / "results"
RUN1_PATH = RESULTS_DIR / "baseline-run1.json"
RUN2_PATH = RESULTS_DIR / "baseline-run2.json"
DONOR_RUN1_PATH = RESULTS_DIR / "donor-diagnosis-run1.json"
DONOR_RUN2_PATH = RESULTS_DIR / "donor-diagnosis-run2.json"

RETRY_TIMEOUT = 600.0

# Hard stop: no model call may START after this UTC instant.
HARD_STOP_UTC = datetime(2026, 10, 17, 9, 45, 0, tzinfo=timezone.utc)


def past_hard_stop() -> bool:
    """True if it is no longer safe to start a new model call."""
    return datetime.now(timezone.utc) >= HARD_STOP_UTC


def load_run1_infrastructure_failures() -> list[str]:
    """Return the case_ids that were INFRASTRUCTURE_FAILURE in run 1, in manifest order."""
    run1 = json.loads(RUN1_PATH.read_text(encoding="utf-8"))
    per_case = run1["baseline_b"]["per_case"]
    return [case_id for case_id, v in per_case.items() if v.get("status") == "INFRASTRUCTURE_FAILURE"]


def write_run2_checkpoint(per_case: dict[str, Any], not_run: list[str]) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    RUN2_PATH.write_text(
        json.dumps(
            {
                "model": MODEL_ID,
                "note": (
                    "Retries ONLY the 36 cases that were INFRASTRUCTURE_FAILURE in "
                    "results/baseline-run1.json, at timeout=600s instead of 180s. "
                    "Run 1's 8 OK cases are not repeated here. See PROTOCOL.md Amendment 1."
                ),
                "hard_stop_utc": HARD_STOP_UTC.isoformat(),
                "per_case": per_case,
                "not_run": not_run,
                "retried_count": len(per_case),
                "not_run_count": len(not_run),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def run_donor_retry(cases: dict[str, dict[str, Any]], registry) -> dict[str, Any]:
    """Retry the donor-diagnosis call at 600s, using the SAME prompt run 1 built.

    Reuses run 1's stored prompt text verbatim if available (so the retry
    is provably asking the identical question), rather than reconstructing
    it -- reconstruction would risk drifting from what run 1 actually sent
    if baseline.py's donor-case selection ever changes.
    """
    if past_hard_stop():
        return {"status": "NOT_RUN", "reason": "past hard stop before donor retry started"}

    run1_donor = json.loads(DONOR_RUN1_PATH.read_text(encoding="utf-8"))
    prompt = run1_donor.get("prompt")
    if not prompt:
        # Fall back to rebuilding it exactly as baseline.py does, from the
        # same development-split CONTRADICTION cases.
        from baseline import run_donor_diagnosis as _unused  # noqa: F401 - documents the fallback path

        prompt = DONOR_PROMPT  # last-resort: should not happen, run1 always records its prompt

    poster = RecordingPoster()
    adapter = ModelAdapter(registry=registry, poster=poster)
    start = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        result = adapter.execute(
            {
                "endpoint": ENDPOINT_NAME,
                "model": MODEL_ID,
                "prompt": prompt,
                "temperature": 0,
                "timeout": RETRY_TIMEOUT,
            }
        )
    except Exception as exc:  # noqa: BLE001 - infrastructure failure, not a crash
        elapsed = time.monotonic() - start
        return {
            "status": "INFRASTRUCTURE_FAILURE",
            "error": str(exc),
            "wall_time_seconds": elapsed,
            "started_at_utc": started_at,
            "timeout": RETRY_TIMEOUT,
        }
    elapsed = time.monotonic() - start
    if not result.ok:
        return {
            "status": "INFRASTRUCTURE_FAILURE",
            "error": result.note,
            "wall_time_seconds": elapsed,
            "started_at_utc": started_at,
            "timeout": RETRY_TIMEOUT,
        }
    return {
        "status": "OK",
        "prompt": prompt,
        "response": result.outputs.get("response", ""),
        "usage": poster.records[-1]["usage"] if poster.records else None,
        "wall_time_seconds": elapsed,
        "started_at_utc": started_at,
        "timeout": RETRY_TIMEOUT,
        "cases_used": run1_donor.get("cases_used", []),
    }


def main() -> None:
    cases = load_cases()
    to_retry = load_run1_infrastructure_failures()
    print(f"Run 2: {len(to_retry)} cases to retry (run 1's INFRASTRUCTURE_FAILUREs), "
          f"hard stop {HARD_STOP_UTC.isoformat()}.", flush=True)

    registry = build_registry()

    # Donor retry FIRST, per Amendment 1.
    if DONOR_RUN2_PATH.exists():
        print("Donor retry: results/donor-diagnosis-run2.json already exists; not re-calling.", flush=True)
    else:
        print(f"Donor retry: starting at {datetime.now(timezone.utc).isoformat()} (timeout {RETRY_TIMEOUT}s)...", flush=True)
        donor_result = run_donor_retry(cases, registry)
        DONOR_RUN2_PATH.write_text(json.dumps(donor_result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Donor retry: {donor_result['status']}", flush=True)

    # Resume support: if baseline-run2.json already has partial progress, keep it.
    per_case: dict[str, Any] = {}
    if RUN2_PATH.exists():
        existing = json.loads(RUN2_PATH.read_text(encoding="utf-8"))
        per_case = existing.get("per_case", {})
        print(f"Run 2: resuming, {len(per_case)} cases already attempted.", flush=True)

    not_run: list[str] = []
    for index, case_id in enumerate(to_retry, start=1):
        if case_id in per_case and per_case[case_id].get("status") == "OK":
            continue  # already resolved in an earlier invocation of this script

        if past_hard_stop():
            not_run.append(case_id)
            print(f"Run 2: HARD STOP reached before case {index}/{len(to_retry)} ({case_id}); "
                  f"recording NOT_RUN for it and all remaining cases.", flush=True)
            continue

        case = cases[case_id]
        prompt = build_prompt(case["payload"])
        started_at = datetime.now(timezone.utc).isoformat()
        print(f"Run 2: retrying case {index}/{len(to_retry)} ({case_id}) at {started_at} "
              f"(timeout {RETRY_TIMEOUT}s)...", flush=True)

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
                    "timeout": RETRY_TIMEOUT,
                }
            )
        except Exception as exc:  # noqa: BLE001 - infrastructure failure, not a crash
            elapsed = time.monotonic() - start
            per_case[case_id] = {
                "status": "INFRASTRUCTURE_FAILURE",
                "error": str(exc),
                "wall_time_seconds": elapsed,
                "started_at_utc": started_at,
                "timeout": RETRY_TIMEOUT,
                "ground_truth_label": case["manifest"]["label"],
            }
            write_run2_checkpoint(per_case, not_run)
            print(f"Run 2: case {index}/{len(to_retry)} ({case_id}) -> INFRASTRUCTURE_FAILURE "
                  f"({exc}) after {elapsed:.1f}s", flush=True)
            continue
        elapsed = time.monotonic() - start
        if not result.ok:
            per_case[case_id] = {
                "status": "INFRASTRUCTURE_FAILURE",
                "error": result.note,
                "wall_time_seconds": elapsed,
                "started_at_utc": started_at,
                "timeout": RETRY_TIMEOUT,
                "ground_truth_label": case["manifest"]["label"],
            }
            write_run2_checkpoint(per_case, not_run)
            print(f"Run 2: case {index}/{len(to_retry)} ({case_id}) -> INFRASTRUCTURE_FAILURE "
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
            "started_at_utc": started_at,
            "timeout": RETRY_TIMEOUT,
            "ground_truth_label": case["manifest"]["label"],
            "split": case["manifest"]["split"],
        }
        write_run2_checkpoint(per_case, not_run)
        print(f"Run 2: case {index}/{len(to_retry)} ({case_id}) -> "
              f"{per_case[case_id]['adjudication']} in {elapsed:.1f}s", flush=True)

    write_run2_checkpoint(per_case, not_run)
    oks = sum(1 for v in per_case.values() if v.get("status") == "OK")
    fails = sum(1 for v in per_case.values() if v.get("status") == "INFRASTRUCTURE_FAILURE")
    print(f"Run 2 done: {oks} OK, {fails} still INFRASTRUCTURE_FAILURE, {len(not_run)} NOT_RUN.", flush=True)


if __name__ == "__main__":
    main()
