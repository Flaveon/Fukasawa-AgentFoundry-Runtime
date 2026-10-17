# Issue #27 — Shadow Run Comparison

Shadow run only. Nothing here was published, deleted, or promoted.
No change was made to ~/pipeline or ~/substack. See PROTOCOL.md for
label definitions, Amendments 1-2 for the run-1/2/3 timeout retries,
and capsule/ROLLOUT.md for promotion status.

## Treatment — the Level-0 rule (src/governance/package_consistency.py)

| split | cases | escaped blockers | false positives | abstentions | matches ground truth |
|---|---|---|---|---|---|
| development | 12 | 0 | 0 | 0 | 12 |
| held-out | 23 | 0 | 0 | 0 | 23 |
| synthetic | 9 | 0 | 0 | 5 | 9 |

Total wall time: 0.000379s. Model calls: 0. Prompt tokens: 0. Completion tokens: 0.

## Baseline A — real pipeline behavior today (zero cost to measure)

The handoff never consults the quality report, so every real
CONTRADICTION case is an escaped blocker under current, unmodified
pipeline behavior:

```json
{
  "development": {
    "case_ids_escaped": [
      "2026-05-31-9g1bby-qwen",
      "2026-06-01-ba5jeu-qwen",
      "2026-06-01-srbg5n-qwen",
      "2026-06-02-eh9b86-qwen",
      "2026-06-03-udu9ao-qwen",
      "2026-06-04-xnbb4a-qwen",
      "2026-06-05-ekybc8-qwen",
      "2026-06-07-cjqitx-qwen",
      "2026-06-08-hdtkkb-qwen",
      "2026-06-08-n8ozaf-qwen",
      "2026-06-09-7w2lpc-qwen",
      "2026-06-10-6ltoq6-qwen"
    ],
    "cases": 12,
    "escaped_blockers": 12
  },
  "held-out": {
    "case_ids_escaped": [
      "2026-06-11-hgw14w-qwen",
      "2026-06-12-at6n35-qwen",
      "2026-06-14-pz9w7x-qwen",
      "2026-06-15-hd2vdp-qwen",
      "2026-06-15-jka6fm-qwen",
      "2026-06-16-pd5de4-qwen",
      "2026-06-17-qotwco-qwen",
      "2026-06-18-zi2xoz-qwen",
      "2026-06-19-5zluoi-qwen",
      "2026-06-21-6xnpnd-qwen",
      "2026-06-22-jwxir2-qwen",
      "2026-06-22-zxxg0t-qwen",
      "2026-06-23-jl1vfi-qwen",
      "2026-06-24-th9m1a-qwen",
      "2026-06-25-22mg2t-qwen",
      "2026-06-26-sie9rv-qwen",
      "2026-06-28-bwttks-qwen",
      "2026-06-29-eibsww-qwen",
      "2026-06-29-k2r6mf-qwen",
      "2026-06-30-c4c1oc-qwen",
      "2026-07-01-3yl25b-qwen",
      "2026-07-02-irhj4k-qwen",
      "2026-07-03-dr3o6n-qwen"
    ],
    "cases": 23,
    "escaped_blockers": 23
  }
}
```

## Baseline B — one model call per case (reasoning baseline)

Three runs, reported SEPARATELY, then combined. Run 1: 44 cases,
timeout 180s/240s. Run 2 (Amendment 1): retries run 1's 36 timeouts
at 600s, hard stop 2026-10-17T09:45Z. Run 3 (Amendment 2): retries
run 2's 18 NOT_RUNs at 600s, hard stop 2026-10-18T09:30Z.

- Run 1 only (44 cases, timeout 180s): 44 cases — OK=8, INFRASTRUCTURE_FAILURE=36, NOT_RUN=0
- Runs 1+2 combined: 44 cases — OK=26, INFRASTRUCTURE_FAILURE=0, NOT_RUN=18
- Runs 1+2+3 combined: 44 cases — OK=44, INFRASTRUCTURE_FAILURE=0, NOT_RUN=0

- Run 1 completion tokens (sum over its 8 OK calls): 11403
- Runs 1+2 completion tokens (sum over all OK calls): 93162
- Runs 1+2+3 completion tokens (sum over all OK calls): 179918
- Run 1 wall time (sum over all 44 calls, success + failure): 7226.8s
- Runs 1+2 wall time: 6153.4s
- Runs 1+2+3 wall time: 11736.2s
- Rule (treatment) wall time for all 44 cases: 0.000379s, 0 tokens, 0 calls.

### Baseline B quality: right vs. wrong answers (runs 1+2+3 combined, OK calls only)

- 44 calls produced an answer at all (out of 44 cases).
- 36/44 matched the ideal SHIP/HOLD/ESCALATE action for that case's actual quality-report verdict.
- **Dangerous wrong answers (model said SHIP when it should not have):** 2 — ['synthetic-malformed-missing-verdict-key-001', 'synthetic-malformed-truncated-json-001']
- **Escalations missed (model answered instead of escalating on missing/malformed evidence):** 2 — ['synthetic-malformed-missing-verdict-key-001', 'synthetic-malformed-truncated-json-001']
- Per-case detail (expected action, what the model said, tokens, wall time, which run resolved it):

  | case_id | expected | got | correct | completion_tokens | wall_s | run |
  |---|---|---|---|---|---|---|
  | 2026-05-31-9g1bby-qwen | HOLD | ESCALATE | False | 7648 | 508.3 | 2 |
  | 2026-06-01-ba5jeu-qwen | HOLD | HOLD | True | 2672 | 174.1 | 1 |
  | 2026-06-01-srbg5n-qwen | HOLD | HOLD | True | 3247 | 214.7 | 2 |
  | 2026-06-02-eh9b86-qwen | HOLD | ESCALATE | False | 5215 | 344.9 | 2 |
  | 2026-06-03-udu9ao-qwen | HOLD | HOLD | True | 5051 | 334.2 | 2 |
  | 2026-06-04-xnbb4a-qwen | HOLD | HOLD | True | 4292 | 283.6 | 2 |
  | 2026-06-05-ekybc8-qwen | HOLD | HOLD | True | 2763 | 182.6 | 2 |
  | 2026-06-07-cjqitx-qwen | HOLD | HOLD | True | 3496 | 230.9 | 2 |
  | 2026-06-08-hdtkkb-qwen | HOLD | HOLD | True | 5827 | 385.7 | 2 |
  | 2026-06-08-n8ozaf-qwen | HOLD | HOLD | True | 5335 | 353.1 | 2 |
  | 2026-06-09-7w2lpc-qwen | HOLD | HOLD | True | 5010 | 331.5 | 2 |
  | 2026-06-10-6ltoq6-qwen | HOLD | HOLD | True | 4414 | 291.8 | 2 |
  | 2026-06-11-hgw14w-qwen | HOLD | HOLD | True | 5010 | 331.6 | 2 |
  | 2026-06-12-at6n35-qwen | HOLD | HOLD | True | 2766 | 182.3 | 2 |
  | 2026-06-14-pz9w7x-qwen | HOLD | HOLD | True | 4865 | 321.7 | 2 |
  | 2026-06-15-hd2vdp-qwen | HOLD | ESCALATE | False | 4938 | 326.6 | 2 |
  | 2026-06-15-jka6fm-qwen | HOLD | HOLD | True | 2888 | 190.9 | 2 |
  | 2026-06-16-pd5de4-qwen | HOLD | HOLD | True | 3436 | 226.8 | 2 |
  | 2026-06-17-qotwco-qwen | HOLD | ESCALATE | False | 5558 | 367.9 | 2 |
  | 2026-06-18-zi2xoz-qwen | HOLD | HOLD | True | 2831 | 182.0 | 3 |
  | 2026-06-19-5zluoi-qwen | HOLD | HOLD | True | 3785 | 243.8 | 3 |
  | 2026-06-21-6xnpnd-qwen | HOLD | HOLD | True | 7554 | 488.6 | 3 |
  | 2026-06-22-jwxir2-qwen | HOLD | HOLD | True | 7554 | 487.7 | 3 |
  | 2026-06-22-zxxg0t-qwen | HOLD | ESCALATE | False | 4292 | 275.5 | 3 |
  | 2026-06-23-jl1vfi-qwen | HOLD | HOLD | True | 3785 | 243.1 | 3 |
  | 2026-06-24-th9m1a-qwen | HOLD | HOLD | True | 4998 | 321.1 | 3 |
  | 2026-06-25-22mg2t-qwen | HOLD | HOLD | True | 5467 | 351.9 | 3 |
  | 2026-06-26-sie9rv-qwen | HOLD | ESCALATE | False | 4641 | 298.5 | 3 |
  | 2026-06-28-bwttks-qwen | HOLD | HOLD | True | 3705 | 238.0 | 3 |
  | 2026-06-29-eibsww-qwen | HOLD | HOLD | True | 5064 | 325.7 | 3 |
  | 2026-06-29-k2r6mf-qwen | HOLD | HOLD | True | 5374 | 345.8 | 3 |
  | 2026-06-30-c4c1oc-qwen | HOLD | HOLD | True | 3195 | 205.2 | 3 |
  | 2026-07-01-3yl25b-qwen | HOLD | HOLD | True | 1846 | 120.9 | 1 |
  | 2026-07-02-irhj4k-qwen | HOLD | HOLD | True | 5585 | 359.6 | 3 |
  | 2026-07-03-dr3o6n-qwen | HOLD | HOLD | True | 5585 | 359.3 | 3 |
  | synthetic-adversarial-hold-prose-001 | HOLD | HOLD | True | 567 | 37.8 | 1 |
  | synthetic-adversarial-lowercase-001 | HOLD | HOLD | True | 4872 | 312.8 | 3 |
  | synthetic-adversarial-missing-section-001 | HOLD | HOLD | True | 1450 | 95.1 | 1 |
  | synthetic-adversarial-spacing-001 | HOLD | HOLD | True | 4796 | 308.5 | 3 |
  | synthetic-clean-pass-001 | SHIP | SHIP | True | 659 | 43.6 | 1 |
  | synthetic-malformed-empty-handoff-001 | HOLD | HOLD | True | 1725 | 111.1 | 1 |
  | synthetic-malformed-missing-verdict-key-001 | ESCALATE | SHIP | False | 3673 | 235.8 | 3 |
  | synthetic-malformed-truncated-json-001 | ESCALATE | SHIP | False | 855 | 55.9 | 1 |
  | synthetic-tool-failure-unreadable-handoff-001 | HOLD | HOLD | True | 1629 | 105.6 | 1 |

- Still `INFRASTRUCTURE_FAILURE` after every run attempted so far: 0 — []
- Still `NOT_RUN` after every run attempted so far (hard stop reached before these were tried): 0 — []

## Donor reasoning vs. recipient rule

- Donor-diagnosis run 1: INFRASTRUCTURE_FAILURE (wall time 240.08241359499516)
- Donor-diagnosis run 2 retry (600s): OK (wall time 372.0900344779948)
- Donor-diagnosis usage (whichever run succeeded, if either did): {'completion_tokens': 5706, 'prompt_tokens': 750, 'total_tokens': 6456}
- Recipient rule (Commit 2, this shadow run): 0 model calls, 0 tokens, by construction — it is a pure deterministic function.
- What the donor reasoning proposed and what was accepted/rejected is recorded in CANDIDATES.md, not here.

## Human cleanup time

NOT MEASURED. Unknown — never assumed to be zero. Nothing in the
pipeline, this experiment, or Mission Control records operator time
spent on a handoff. See PROTOCOL.md.

## What this does not show

- It does not fix the pipeline: ~/pipeline and ~/substack were never
  modified, and the real handoff documents still say what they said
  before this experiment ran.
- It does not measure reader/operator engagement.
- Synthetic-split numbers above are not real-world evidence; they
  test the rule's parsing logic (see PROTOCOL.md for the full list).
- A `NOT_RUN` case was never attempted in run 2 or run 3 — it says
  nothing about that case, only that a hard stop arrived first.
- This is a shadow run. The rule has no authority over anything; see
  capsule/ROLLOUT.md.

