# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Amendment 2 run 3: re-ask ONLY the cases run 2 never reached (NOT_RUN).

See PROTOCOL.md's "Amendment 2 (2026-10-17)" section, which this script
implements exactly:

* Re-asks ONLY the 18 cases recorded ``NOT_RUN`` in run 2
  (``results/baseline-run2.json``'s ``not_run`` list) -- every case already
  resolved ``OK`` or confirmed ``INFRASTRUCTURE_FAILURE`` in run 1 or run 2
  is left untouched.
* Identical settings to run 2: same prompt text, same model, same
  ``temperature: 0``, same ``timeout: 600s``.
* Calls sequential, never concurrent.
* Writes ONLY ``results/baseline-run3.json``, incrementally, after every
  single case. Runs 1 and 2's result files are never opened for writing.
* HARD STOP: no model call may start after 09:30 UTC on 2026-10-18 (the
  owner's content pipeline needs this server again at 10:00 UTC that day).
  Checked with ``datetime.now(timezone.utc)`` before every call, not by
  hand. Any case not reached stays ``NOT_RUN`` in run 3's own record.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.kernel.models import ModelAdapter

from baseline import (  # reuse run 1/2's exact prompt/registry/poster code, unmodified
    ENDPOINT_NAME,
    MODEL_ID,
    RecordingPoster,
    build_prompt,
    build_registry,
    load_cases,
    parse_adjudication,
)

EXPERIMENT_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EXPERIMENT_DIR / "results" / "v1"  # v1 is archived; this script only ever reproduces v1
RUN2_PATH = RESULTS_DIR / "baseline-run2.json"
RUN3_PATH = RESULTS_DIR / "baseline-run3.json"

RETRY_TIMEOUT = 600.0

# Hard stop: no model call may START after this UTC instant.
HARD_STOP_UTC = datetime(2026, 10, 18, 9, 30, 0, tzinfo=timezone.utc)


def past_hard_stop() -> bool:
    """True if it is no longer safe to start a new model call."""
    return datetime.now(timezone.utc) >= HARD_STOP_UTC


def load_run2_not_run() -> list[str]:
    """Return the case_ids run 2 recorded NOT_RUN, in its original order."""
    run2 = json.loads(RUN2_PATH.read_text(encoding="utf-8"))
    return list(run2.get("not_run", []))


def write_run3_checkpoint(per_case: dict[str, Any], not_run: list[str]) -> None:
    """Overwrite results/baseline-run3.json with the current accumulated run-3 state."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    RUN3_PATH.write_text(
        json.dumps(
            {
                "model": MODEL_ID,
                "note": (
                    "Retries ONLY the 18 cases that were NOT_RUN in "
                    "results/baseline-run2.json (run 2's hard stop arrived before they "
                    "were attempted). Runs 1 and 2 are not repeated here. "
                    "See PROTOCOL.md Amendment 2."
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


def main() -> None:
    """Retry run 2's NOT_RUN cases at 600s, sequentially, until the run-3 hard stop."""
    cases = load_cases()
    to_retry = load_run2_not_run()
    print(f"Run 3: {len(to_retry)} cases to retry (run 2's NOT_RUNs), "
          f"hard stop {HARD_STOP_UTC.isoformat()}.", flush=True)

    registry = build_registry()

    per_case: dict[str, Any] = {}
    if RUN3_PATH.exists():
        existing = json.loads(RUN3_PATH.read_text(encoding="utf-8"))
        per_case = existing.get("per_case", {})
        print(f"Run 3: resuming, {len(per_case)} cases already attempted.", flush=True)

    not_run: list[str] = []
    for index, case_id in enumerate(to_retry, start=1):
        if case_id in per_case and per_case[case_id].get("status") == "OK":
            continue  # already resolved in an earlier invocation of this script

        if past_hard_stop():
            not_run.append(case_id)
            print(f"Run 3: HARD STOP reached before case {index}/{len(to_retry)} ({case_id}); "
                  f"recording NOT_RUN for it and all remaining cases.", flush=True)
            continue

        case = cases[case_id]
        prompt = build_prompt(case["payload"])
        started_at = datetime.now(timezone.utc).isoformat()
        print(f"Run 3: retrying case {index}/{len(to_retry)} ({case_id}) at {started_at} "
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
            write_run3_checkpoint(per_case, not_run)
            print(f"Run 3: case {index}/{len(to_retry)} ({case_id}) -> INFRASTRUCTURE_FAILURE "
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
            write_run3_checkpoint(per_case, not_run)
            print(f"Run 3: case {index}/{len(to_retry)} ({case_id}) -> INFRASTRUCTURE_FAILURE "
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
        write_run3_checkpoint(per_case, not_run)
        print(f"Run 3: case {index}/{len(to_retry)} ({case_id}) -> "
              f"{per_case[case_id]['adjudication']} in {elapsed:.1f}s", flush=True)

    write_run3_checkpoint(per_case, not_run)
    oks = sum(1 for v in per_case.values() if v.get("status") == "OK")
    fails = sum(1 for v in per_case.values() if v.get("status") == "INFRASTRUCTURE_FAILURE")
    print(f"Run 3 done: {oks} OK, {fails} still INFRASTRUCTURE_FAILURE, {len(not_run)} NOT_RUN.", flush=True)


if __name__ == "__main__":
    main()
