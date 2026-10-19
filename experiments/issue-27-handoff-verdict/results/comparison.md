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
| synthetic | 9 | 0 | 0 | 6 | 8 |

Total wall time: 0.000611s. Model calls: 0. Prompt tokens: 0. Completion tokens: 0.

**One known, deliberate synthetic mismatch (not a defect):**
`synthetic-adversarial-hold-prose-001`'s FROZEN manifest label is
CONSISTENT (v1's intended behavior for 'hold (ship once blockers
fixed)'), but v2 ABSTAINs on it instead — v2's exact-value allowlist
treats a decorated/prose-suffixed value as unparseable rather than
cleverly resolving it, which is the entire point of the H1 rewrite
(see CANDIDATES.md, decision 12). The manifest label is left exactly as
frozen — it is not edited after the fact to match v2's behavior — so
this one case shows up as a non-match here rather than being quietly
relabelled to make the table read 9/9.

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
- Runs 1+2 'combined' wall time (replaces a case's run-1 entry with its run-2 outcome, so run 1's time on a later-superseded case is NOT counted twice, but also not counted at all): 6153.4s
- Runs 1+2+3 'combined' wall time (same caveat): 11736.2s
- **Total wall time ACTUALLY spent across every attempt in all three runs, including the 36 run-1 calls that timed out and were later superseded** (M4b — this is the real cost, not the 'combined' figure above, which silently drops superseded attempts): **18219.0s** (7226.8 + 5409.2 + 5582.9).
- Rule (treatment) wall time for all 44 cases: 0.000611s, 0 tokens, 0 calls.

### Baseline B on the SAME frozen metric as the Treatment table (M4a)

PROTOCOL.md's Metrics section defines escaped blockers / false
positives / abstentions for every method, not just the rule.
Mapped onto Baseline B's SHIP/HOLD/ESCALATE answer (SHIP~allow,
HOLD~flag, ESCALATE~abstain), combined across all three runs:

**Caveat on this mapping (round-2 review nit):** counting every HOLD
answer as a 'false positive' when the label is not CONTRADICTION is
coarser than it sounds. B's HOLD means 'don't ship' -- a cautious,
safe recommendation, not necessarily a claim that a contradiction was
found. On `synthetic-adversarial-hold-prose-001` (label CONSISTENT; a
HOLD report whose handoff ALSO legitimately says hold) and the 3
NO_EVIDENCE cases whose underlying report happens to be HOLD, B
correctly said HOLD -- the SAFE answer -- and it is counted below as a
'false positive' anyway, because this metric only tracks SHIP/HOLD/
ESCALATE against CONTRADICTION/not-CONTRADICTION, not against what a
human would actually have wanted B to say. Read the table's
'false positives' column as 'B said HOLD on a non-CONTRADICTION case',
not as 'B invented a contradiction that was not there'.

| split | cases | escaped blockers | false positives | abstentions | matches ground truth |
|---|---|---|---|---|---|
| development | 12 | 0 | 0 | 2 | 10 |
| held-out | 23 | 0 | 0 | 4 | 19 |
| synthetic | 9 | 0 | 4 | 0 | 7 |

**On this metric, Baseline B escaped 0 of the 35 REAL blockers** (development + held-out splits) — it never answered SHIP on a real CONTRADICTION case; its wrong answers on real cases were all ESCALATE (safe direction, not a miss). Its only SHIP-on-a-case-that-should-not-ship answers are the 2 dangerous wrong answers below, and both are SYNTHETIC malformed-report cases, not real ones. **So, against Baseline B specifically, the rule's advantage on THIS dataset is cost and latency (0 vs. 18219s and 0 vs. 179918 tokens) plus those 2 synthetic cases — not catching a real blocker Baseline B would have missed.** The real-world gain this experiment actually demonstrates is against Baseline A (the pipeline's current, unmodified behavior), which escapes all 35/35 real blockers because it never looks at the quality report at all.

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

## Local-only run: the rule against the RAW real files (M4d)

Everything above feeds the rule TEXT REBUILT from the already-sanitized
fields in dataset/cases/*.json — it never reads a real file. That is a
deliberate privacy choice (this repo is public), but it means the 44/44
result above is not, by itself, proof the rule parses REAL files, only
that it parses a reconstruction of them. `local_only_run.py` closes that
gap: it runs the same, unmodified rule against the raw
`quality-report.json` and `*-duath-operator-handoff.md` files for all 35
real run_ids, read-only, and records ONLY verdict counts and SHA-256
checksums — never file content (a BLOCK/ABSTAIN verdict's `.reasons`
literally quote handoff text, so that field is discarded entirely).

Result: `{'BLOCK': 35}` over 35 real run_ids from ~/substack — matching the sanitized-dataset result exactly (35/35 BLOCK). See `results/local-only-run.json` for the per-case checksums.

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

- **A near-perfect score is not independent evidence.** Ground-truth
  labels (PROTOCOL.md, 'Label definitions') are defined by the SAME
  criterion the rule implements: deterministic report says HOLD, handoff
  says PASS or ship. So 43/44 (see the one documented exception above)
  shows the rule parses the test cases correctly and abstains when
  evidence is missing; it cannot show the
  criterion itself is the right policy. That policy is the owner's
  stated intent in the May 31 plan ('PASS cannot override deterministic
  blockers'; 'Delivery notes cannot recommend publish for held
  artifacts') — whether it is right is for the owner's review, not this
  run.
- **The real 35-case corpus has almost no variety, and the held-out split
  was never held out from the person who wrote the rule's parsing logic**
  (PROTOCOL.md Amendment 3, M1). It reduces to 4 distinct rule inputs, all
  against a HOLD report. Neither this run's nor v1's `held-out` numbers
  are evidence of generalization to handoffs no one has looked at yet.
- **Baseline B is a counterfactual, not the pipeline's actual spend.** The
  pipeline never asked a model to adjudicate handoff against report —
  that check did not exist (Baseline A). Baseline B measures what doing
  this check BY REASONING would cost and how well it would do, on the
  same model. See the frozen-metric section above: against Baseline B
  specifically, the rule's advantage on this dataset is cost/latency plus
  2 synthetic cases, not catching a real blocker Baseline B would have
  missed.
- It does not fix the pipeline: ~/pipeline and ~/substack were never
  modified, and the real handoff documents still say what they said
  before this experiment ran.
- It does not measure reader/operator engagement.
- Synthetic-split numbers above are not real-world evidence; they
  test the rule's parsing logic (see PROTOCOL.md for the full list).
- A `NOT_RUN` case was never attempted in run 2 or run 3 — it says
  nothing about that case, only that a hard stop arrived first.
- **Human cleanup time is NOT MEASURED** (restated: no record exists
  anywhere); no claim is made about operator time saved.
- This is a shadow run. The rule has no authority over anything; see
  capsule/ROLLOUT.md.

