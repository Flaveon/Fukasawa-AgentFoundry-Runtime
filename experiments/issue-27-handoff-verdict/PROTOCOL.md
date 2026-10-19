# Issue #27 — Handoff/Quality-Report Verdict Consistency: Experiment Protocol

This dataset and its baselines were FROZEN as a commit boundary (Commit 1:
`baseline.py`, `results/v1/baseline-run1.json`, `results/v1/donor-diagnosis-run1.json`
— archived under `results/v1/` as of Amendment 3; written at
`results/baseline-run1.json` etc. at the time of Commit 1 itself)
before any rule code was *committed* under `src/governance/` — it was not,
in fact, written before the rule existed in the working tree at all; see
the Disclosure immediately below, which says so precisely rather than
leaving the header's "before any rule exists" claim uncorrected.

### Disclosure (2026-10-17)

In practice, `src/governance/package_consistency.py` and its tests were
drafted in the working tree, and `experiments/issue-27-handoff-verdict/shadow.py`
was written, before this commit was made — a session interruption changed
the order of operations from the original plan. What matters for the
freeze this commit represents: **no treatment result was ever written to
`results/treatment.json` or `results/comparison.md`, inspected, or compared
against Baseline A or B before this commit.** That file genuinely does not
exist at this commit. One caveat must be disclosed precisely rather than
rounded off: `tests/test_package_consistency_rollback.py::
test_baseline_a_identical_with_and_without_the_rule_imported` (part of
Commit 2, not yet committed at this point) calls the real, unpatched
`shadow.run_treatment()` once, in-memory, purely to prove Baseline A's
output is unaffected by the rule's existence — that call's per-case
verdicts were discarded immediately after the equality assertion, never
serialized, never read, and never used to compute or report any of the
metrics in this protocol. No one looked at what the rule said about the
dataset before freezing this baseline.

## Hypothesis

The Q2C content pipeline (`~/pipeline/q2c_pipeline.py`, private, read-only)
writes two documents per run that disagree with each other about whether a
package should ship:

* `build_package_quality_report()` (~4375-4397 build the inventory,
  ~4596 compute `verdict = "PASS" if not findings else "HOLD"`) — a
  deterministic gate driven by `html_release_blockers()` over the actual
  generated files. Written to
  `~/substack/deploy/<MM_DD_YY>/<run_id>/quality-report.json`.
* `build_duath_operator_handoff()` (~1334-1399, the "Shipping Decision" lines
  at ~1354-1356 and the "Angela verdict:" line at ~1349) — an
  operator-facing Markdown handoff. Its Shipping Decision lines read
  `scope.get("article_html", {}).get("ships", True)` etc. — Dwight's
  *deployment scope* (was this asset class even in scope), defaulting to
  ship when unset — **never** `html_release_blockers()` or the quality
  report's `verdict`. Written to
  `~/substack/<YYYY-MM-DD>/support/<run_id>-duath-operator-handoff.md`.

These are two independent computations over the same run, and the pipeline
never reconciles them. The owner's original intent for this exact gap is on
record in
`docs/source-archive/2026-05-31-fukasawa-quality-orchestrator-plan.md`
(read via the `m0-source-archive` worktree), Unit 3, "Whole-Package Quality
Gate": *"Duath/Angela PASS cannot override deterministic blockers"* and
*"Delivery notes cannot recommend publish for held artifacts."* Neither rule
was ever built. This experiment's hypothesis is that a Level-0 deterministic
check — no model, no network — can close this specific, narrow gap: flag the
handoff whenever it tells the operator to ship (or says Angela PASS) for a
run_id whose own `quality-report.json` says HOLD.

## Unit of analysis

One `run_id`. A case is: the quality report's `verdict` + finding counts for
that run_id, and the matching handoff's `Angela verdict:` line + `##
Shipping Decision` bullet lines for the *same* run_id.

## Ground truth

`quality-report.json`'s `verdict` field is authoritative — it is the
pipeline's own deterministic, re-runnable check
(`html_release_blockers()`/`build_package_quality_report()`), not a model
opinion. The handoff is the artifact under test: does it say something that
contradicts the authoritative verdict?

### Label definitions

* **CONTRADICTION** — `quality-report.json.verdict == "HOLD"` AND
  (the handoff's `Angela verdict:` line says PASS, OR any `## Shipping
  Decision` line's value starts with "ship", case-insensitive). The
  deterministic gate held the run; the handoff told a human to ship it (or
  that Angela passed it) anyway.
* **CONSISTENT** — the report and handoff do not contradict each other: a
  HOLD report whose shipping lines all read "hold" / "do not ship" / a
  prose blocker description that does not parse as an affirmative ship
  instruction (e.g. "hold (ship once blockers fixed)" — the word "ship"
  appears in prose, but the parsed *value* is "hold"); or (synthetic-only; no
  real case in this corpus) a PASS report whose handoff agrees.
* **NO_EVIDENCE** — no deterministic comparison can be made: the quality
  report is missing, unreadable, or malformed (invalid JSON, or valid JSON
  with no `verdict` key); OR the handoff is missing, present-but-empty, or
  present but has neither an `Angela verdict:` line nor a `## Shipping
  Decision` section to compare against. **Expected behavior for every
  NO_EVIDENCE case is to abstain and escalate to a human operator — never to
  report PASS/CONSISTENT.** This widens the task brief's literal "no quality
  report" definition to "no usable evidence of either kind", because that is
  what the deterministic rule under test is actually built to abstain on
  (see `src/governance/package_consistency.py`'s `ABSTAIN` verdict). This
  widening is recorded here, not applied silently.

### Dataset split

Fixed by date, not randomized:

* **development** — the earliest ~third of real run_ids by date (12 of 35,
  2026-05-31 .. 2026-06-10).
* **held-out** — the rest (23 of 35, 2026-06-11 .. 2026-07-03).
* **synthetic** — 9 hand-labelled cases (see below). A separate bucket, not
  part of development/held-out. **Synthetic cases are synthetic, not
  real-world evidence.** They exist only to exercise label paths
  (CONSISTENT, NO_EVIDENCE) that essentially do not occur in this real
  corpus, and to pressure-test string parsing against case/whitespace/prose
  variation. Do not read synthetic-split numbers as evidence about the Q2C
  pipeline's real behavior; read them as evidence about the rule's logic.

### Real-case outcome (a finding, not a design choice)

All 35 real run_ids in this corpus label CONTRADICTION. The pipeline's
`## Shipping Decision` lines for `Article HTML` and `Visual support` never
read "hold" anywhere in this sample; only `Interactive tool` ever reads
anything other than "ship" (it reads "do not ship" when Dwight scoped no
tool for that run, which is a legitimate *scope* decision, not a quality
hold). There is, in other words, no real-world example of the pipeline's
handoff correctly reporting a hold for the same reason the quality gate
held. This is itself evidence for the defect, not an artifact of case
selection — see `extract.py`'s `find_real_run_ids()`, which takes every
run_id with a quality report, no filtering by outcome.

### Synthetic cases (full list, see `extract.py::synthetic_cases()`)

| case_id | label | what it tests |
|---|---|---|
| `synthetic-clean-pass-001` | CONSISTENT | PASS report + handoff agrees — the only clean-pass example in the dataset, since none exists in the real corpus |
| `synthetic-adversarial-spacing-001` | CONTRADICTION | extra whitespace, mixed case ("Ship", "ship   ") |
| `synthetic-adversarial-lowercase-001` | CONTRADICTION | "angela verdict: pass" entirely lowercase |
| `synthetic-adversarial-hold-prose-001` | CONSISTENT | shipping line literally contains the word "ship" in prose ("hold (ship once blockers fixed)") but its parsed value is "hold" |
| `synthetic-adversarial-missing-section-001` | NO_EVIDENCE | handoff present, HOLD report, but the handoff has neither an Angela line nor a Shipping Decision section |
| `synthetic-malformed-truncated-json-001` | NO_EVIDENCE | quality report could not be parsed |
| `synthetic-malformed-missing-verdict-key-001` | NO_EVIDENCE | quality report parses but has no `verdict` key |
| `synthetic-malformed-empty-handoff-001` | NO_EVIDENCE | handoff file present but empty |
| `synthetic-tool-failure-unreadable-handoff-001` | NO_EVIDENCE | handoff file exists but could not be read (I/O failure, distinct from "empty") |

## Metrics

Reported per split (development / held-out / synthetic), real vs. synthetic
kept visually and numerically separate in `results/comparison.md`:

* **escaped blockers** — CONTRADICTION cases the method did not flag.
* **false positives** — CONSISTENT (or NO_EVIDENCE-handled-as-fine) cases the
  method wrongly flagged as a contradiction.
* **abstentions** — cases the method declined to adjudicate (ABSTAIN /
  ESCALATE).
* **reasoning (model) calls** — count of calls to a model. Fixed at 0 for
  the Level-0 rule (Commit 2) and for Baseline A (it makes none). Baseline B
  makes exactly one per case.
* **prompt / completion tokens** — read from the raw HTTP response's
  `usage` object (OpenAI-compatible `/v1/chat/completions` shape from
  llama.cpp: `usage.prompt_tokens`, `usage.completion_tokens`). Baseline A
  and the Level-0 rule: 0 (no model call exists to report usage for).
* **wall time** — measured with `time.monotonic()` around each unit of
  work. Reported per case and summed per split.
* **human cleanup time** — **NOT MEASURED. State plainly: unknown, never
  zero.** Nothing in this experiment, the pipeline, or Mission Control
  records operator time spent reading a handoff, noticing or not noticing a
  contradiction, or cleaning up a bad publish. (Confirmed absent: Mission
  Control's `token_usage` table has the right columns but 0 rows for this
  pipeline; no duration field exists anywhere in the Q2C support/*.json
  artifacts.)

### Infrastructure failure vs. wrong answer

A model call that fails or times out is recorded as `INFRASTRUCTURE_FAILURE`
in `results/v1/baseline-run1.json` (run 1; see Amendment 1 for
`results/v1/baseline-run2.json` — both archived under `results/v1/` as of
Amendment 3), distinct from a call that completed but gave a wrong
SHIP/HOLD/ESCALATE adjudication. These are never merged into the same count.

## Model configuration (Baseline B and the donor-diagnosis call)

* Endpoint: local llama.cpp, `http://localhost:8081`, OpenAI-compatible
  `/v1/chat/completions`. Confirmed live and serving via
  `curl http://localhost:8081/v1/models` at the time of this experiment:
  `Qwen_Qwen3.5-27B-Q4_K_M.gguf` (the only model listed).
* `temperature`: 0.
* `max_tokens`: **not controllable from this script.** `src/kernel/models.py`
  is FROZEN (this experiment imports `ModelAdapter`/`ModelEndpointRegistry`/
  `http_post_json` from it but may not edit it, per the task's FROZEN-path
  rule), and `ModelAdapter.execute()`'s llamacpp branch posts only
  `{"model", "messages", "temperature"}` — it does not forward a
  `max_tokens` field to the request body. Output length is bounded only by
  instructing the model in the prompt itself ("answer with exactly one
  word... then one sentence"), not by a server-enforced token cap. This is
  recorded here rather than silently claiming a cap that is not actually
  enforced.
* Prompt text: see `baseline.py::BASELINE_B_PROMPT_TEMPLATE` and
  `baseline.py::DONOR_PROMPT` — reproduced verbatim below.
* `timeout`: 180 seconds per Baseline B adjudication call, 240 seconds for
  the donor-diagnosis call, in run 1 (see Amendment 1: run 2 raises this to
  600s for the cases run 1 timed out on). **Observed in practice, over the
  full run 1: this model, on this hardware, under this frozen adapter's
  lack of a `max_tokens` cap, timed out on 36 of 44 calls (82%)** —
  including the very first (case `2026-05-31-9g1bby-qwen`, timed out at
  exactly 180.1s) and the donor-diagnosis call itself (timed out at
  240.1s). A model that free-runs its chain-of-thought with no length cap
  and a ~13.7 token/s decode speed (measured: a trivial "Say OK" prompt
  still produced 105 tokens of reasoning in 8.3s) routinely needs far more
  completion tokens of hidden reasoning than that budget buys before it
  emits the one-word answer this prompt asked for. This is recorded as
  `INFRASTRUCTURE_FAILURE`, never folded into "the model got it wrong" —
  but it is itself a finding: part of the real cost of a reasoning-model
  baseline on this hardware is that a bounded timeout and an unbounded
  chain-of-thought are in tension, and the Level-0 rule has no equivalent
  failure mode at all.
* The llama server is a shared user service. This experiment never
  restarts, reconfigures, or sends it any request whose URL is not
  `http://localhost:8081` — enforced in code (`baseline.py` refuses any
  non-localhost poster URL before sending).

### Baseline B prompt (verbatim)

```
You are reviewing one Q2C content-pipeline run for a publish decision.

Deterministic quality report for this run:
- verdict: {verdict}
- finding counts by check: {finding_counts}

Operator handoff document for the SAME run:
- Angela verdict line: {angela_verdict_line}
- Shipping Decision lines: {shipping_decision_lines}

Based ONLY on the information above, answer with exactly one word on the
first line: SHIP, HOLD, or ESCALATE. Then, on a second line, give a one
sentence reason.
```

### Hardware

16 CPU threads. GPUs (models only, no hostnames): RTX 4060 Ti 16GB, RTX 3060
12GB.

### Workflow version

* This repo (Fukasawa-AgentFoundry-Runtime), worktree `issue-27-shadow`,
  branch `feat/issue-27-handoff-verdict-shadow`: recorded as the commit SHA
  of Commit 1 in this experiment (see git log; base `95d8867`).
* Pipeline repo (`~/pipeline`, private, read-only, never modified):
  `git -C ~/pipeline rev-parse HEAD` = `c49a5cb644cf210731517a6af91fce284568324a`
  at the time this experiment ran.

## Baseline A — the pipeline's real-world behavior (zero cost to measure)

What the handoff documents *actually told the operator*, for the 35 real
cases: count how many of them are CONTRADICTION (an escaped blocker the
handoff shipped past the operator unflagged) under the pipeline's current,
unmodified behavior — i.e. the handoff never flags anything, by
construction, since `build_duath_operator_handoff()` does not look at the
quality report at all. See `baseline.py::run_baseline_a()`.

## Baseline B — one-call model adjudication

For every case in every split, ask the local model (via
`src.kernel.models.ModelAdapter`, with an injected recording poster that
wraps `http_post_json` to capture wall time and the raw response's `usage`
object) to adjudicate SHIP/HOLD/ESCALATE from the same sanitized fields the
Level-0 rule sees. One call per case. A failed/timed-out call is recorded as
`INFRASTRUCTURE_FAILURE` and the run continues with the remaining cases.

### Checkpointing / resumability

Given the timeout behavior above, a full Baseline B run can take well over
an hour of wall time. `baseline.py` writes `results/v1/baseline-run1.json`
(see Amendment 1 for `results/v1/baseline-run2.json`) after
**every single case** (success or `INFRASTRUCTURE_FAILURE`), and on
startup re-reads whatever is already there, skipping any case already
recorded with `status: "OK"`. An interrupted run loses at most the one call
that was in flight, never prior progress, and a case already marked
`INFRASTRUCTURE_FAILURE` is retried on the next run (recorded with
`retried_after_prior_infrastructure_failure: true` if it still fails) —
never silently dropped, and never silently overwritten without the retry
being visible in the record itself.

## Donor-diagnosis call

One higher-depth reasoning call: 2-3 development-split cases plus the
relevant pipeline function excerpts (verbatim, from the private read-only
pipeline — not committed as pipeline source, only quoted in the prompt) are
given to the model, asking for root cause and a minimal deterministic check.
Saved to `results/donor-diagnosis-run1.json` (prompt + response + usage;
see Amendment 1 for the retry). What it proposed, and the finding on
review that it does NOT demonstrate issue #27 checklist item 4 ("generate
... from higher-depth reasoning with existing model adapters" — see H2 in
the review this amendment responds to), is recorded in `CANDIDATES.md`.
The rule itself was hand-written by the implementing agent; this call is
kept as its own, separately-dated artifact, not as "the reasoning that
produced the rule."

## Amendment 1 (2026-10-17)

Run 1 (frozen in `results/baseline-run1.json` / `results/donor-diagnosis-run1.json`,
Commit 1) hit the 180s timeout on 36 of 44 Baseline B cases, and on the one
donor-diagnosis call, because the model's hidden chain-of-thought reasoning
routinely exceeds what a 180s/240s budget buys at this decode speed. This
amendment is committed BEFORE any re-run is executed.

**Run 2 plan** (`experiments/issue-27-handoff-verdict/rerun_timeouts.py`,
writes `results/baseline-run2.json` / `results/donor-diagnosis-run2.json`):

* Re-asks ONLY the 36 cases that were `INFRASTRUCTURE_FAILURE` in run 1 —
  the 8 that got a real `OK` answer in run 1 are not re-called.
* One donor-diagnosis retry, done FIRST, before any of the 36 case
  re-asks.
* Same prompt text, same model, same `temperature: 0` (`max_tokens` is
  still not controllable — see above) — the only changed variable is
  `timeout`, raised from 180s/240s to **600s** for both the case re-asks
  and the donor retry.
* Calls are made sequentially (one at a time, not concurrently) — this is
  a shared llama.cpp instance and the host has one GPU pair, not a pool.
* **Run 1's results are kept, never overwritten.** `results/baseline-run1.json`
  and `results/donor-diagnosis-run1.json` are frozen as of Commit 1. Run 2
  writes to separate files. A case that still fails in run 2 stays
  recorded as `INFRASTRUCTURE_FAILURE` there — run 2 does not invent a
  better outcome for a case that genuinely did not resolve.
* **Reported metrics use run 1 OKs + run 2 OKs as the combined Baseline B
  result**, and `results/comparison.md` ALSO reports run-1-only numbers
  separately, so the effect of the longer timeout is visible rather than
  silently absorbed into one blended figure.
* **Hard stop: no model call may start after 09:45 UTC on 2026-10-17.** The
  owner's Q2C content pipeline is scheduled to use the same llama.cpp
  server starting at 10:00 UTC that day, and this experiment must not be
  still holding the server when that happens. This is checked with
  `datetime.now(timezone.utc)` in code before every single call (case
  re-asks and the donor retry alike) — not estimated by hand from a start
  time and an expected per-call duration. Any case the run 2 script does
  not reach before the deadline is recorded with status `NOT_RUN`,
  distinct from both `OK` and `INFRASTRUCTURE_FAILURE`: a `NOT_RUN` case
  was never attempted in run 2 at all, for a reason that has nothing to do
  with the case itself (it is a scheduling constraint, not a result).

**Disclosure (2026-10-17, on committing run 2's results):**
`rerun_timeouts.py` was written and run ONCE — producing
`results/baseline-run2.json` and `results/donor-diagnosis-run2.json` — before
the script itself, or either result file, was committed to git; all three
were untracked for the duration of that run. Nothing was altered after the
fact to make the results look different from what the run actually
produced; this commit records, after the run, what already happened. The
donor retry (timeout 600s) succeeded: 372.1s wall time, 750 prompt tokens,
5706 completion tokens of hidden reasoning before a 676-character answer
(full text in `CANDIDATES.md`). The 36 case retries ran until the hard
stop: **18 resolved OK, 18 were NOT_RUN** (the hard stop arrived mid-run,
during case 19's would-be retry window — see Amendment 2 below for those
18).

## Amendment 2 (2026-10-17)

Run 2 honored its hard stop: of the 36 cases retried, 18 got a real answer
(`OK`) and 18 were never attempted (`NOT_RUN`) because 09:45 UTC arrived
first. The owner's Q2C content pipeline ran and finished (10:21 UTC that
day) on schedule; its next scheduled run is 10:00 UTC on 2026-10-18, and
the llama.cpp server is confirmed idle in between.

**Run 3 plan** (`results/baseline-run3.json`, same script pattern as run 2,
reading its retry list from run 2's `not_run` array instead of run 1's
`INFRASTRUCTURE_FAILURE` list):

* Re-asks ONLY the 18 cases run 2 recorded `NOT_RUN` — every case that got
  an `OK` or a confirmed `INFRASTRUCTURE_FAILURE` in run 1 or run 2 is left
  untouched.
* Identical settings to run 2: same prompt text, same model, same
  `temperature: 0`, same `timeout: 600s`.
* Calls sequential, never concurrent.
* Runs 1 and 2's result files are kept as-is, never overwritten. Run 3
  writes only `results/baseline-run3.json`.
* **Hard stop: no model call may start after 09:30 UTC on 2026-10-18** —
  30 minutes of margin before the owner's 10:00 UTC pipeline run, checked
  the same way as Amendment 1 (`datetime.now(timezone.utc)` in code before
  every call). Any case not reached stays `NOT_RUN` in run 3's own record.
* `results/comparison.md` reports run-1-only, runs-1+2, and runs-1+2+3
  numbers separately, with `INFRASTRUCTURE_FAILURE` and `NOT_RUN` always
  broken out rather than folded into each other or into the OK count.

**Disclosure (2026-10-17, on committing run 3's results):**
`experiments/issue-27-handoff-verdict/rerun_timeouts_run3.py` was written
and run ONCE — producing `results/baseline-run3.json` — before the script
itself or its result file was committed to git; both were untracked for
the duration of that run, the same sequencing as run 2's
`rerun_timeouts.py` (see the disclosure above). Nothing was altered after
the fact. Run 3 did not hit its hard stop: **all 18 cases that run 2 left
`NOT_RUN` resolved `OK`** this time (run 3 started at 13:04 UTC on
2026-10-17, well inside its 2026-10-18 09:30 UTC hard stop, and finished
long before it). As of run 3, every one of the 44 Baseline B cases has a
real `OK` answer — zero remain `INFRASTRUCTURE_FAILURE` or `NOT_RUN`.

## Amendment 3 (post-review)

An independent review of commits `8b7bc0f..c1eb681` (full report in the
implementer's working notes; summarized in `CANDIDATES.md` and this
amendment) found CHANGES_REQUIRED: 2 High findings, 4 Medium, several Low.
The most important: the rule (`src/governance/package_consistency.py`)
**fails open** — it only abstains when BOTH the Angela line and the
Shipping Decision section are completely absent; any OTHER unparseable or
adversarially-shaped input (markup, emoji, homoglyphs, fullwidth
characters, unrecognized bullet markers, header drift, a blank line
splitting a section, a second section, a duplicate Angela line, a
qualified PASS claim like "PASSED" or "PASS - zero failures", an Angela
value of UNKNOWN, a PASS report that still lists findings) is read as "not
ship" / "not PASS" and returns `CONSISTENT` — the one answer this rule
must never give when it cannot actually tell. This is being fixed. Before
touching the rule, the following is committed first, as a record-keeping
step, per the review process:

* **v1 is archived, not deleted.** `results/treatment.json` and
  `results/comparison.md` as they stood at commit `c1eb681`, plus
  `results/baseline-run{1,2,3}.json` and `results/donor-diagnosis-run{1,2}.json`,
  move to `results/v1/` (same filenames, new directory) in the same commit
  as this amendment. They remain the complete, honest record of the v1
  rule's behavior and of Baseline A/B on the same dataset. Nothing in
  `results/v1/` is edited after the move.
* **The rule is revised to v2** to close the fail-open gap: an allowlist
  of recognized shapes and values, with anything outside that allowlist
  routed to `ABSTAIN` rather than silently read as "not ship". v2 is
  evaluated on the exact same frozen dataset (`dataset/`) as v1 — no new
  real or synthetic cases are added for this revision — and its results
  are written fresh to `results/treatment.json` / `results/comparison.md`
  (v1's copies, under `results/v1/`, are untouched).
* **Correction (round 2 of review): labels did NOT change.** An earlier
  version of this bullet said "v2's labels are assigned post-hoc", which
  reads as though the dataset's labels were edited to fit v2 — they were
  not. `dataset/manifest.json` is byte-identical to how it stood at `c1eb681`
  and is never edited by this rewrite. What actually changed is narrower:
  v2's rule logic was written by the implementing agent with knowledge of
  what it needs to parse (it could hardly be written otherwise), and the
  rule's logic was NOT independently re-derived by someone who could not
  see the dataset first — see M1 below for why neither v1's nor v2's
  numbers on this dataset are evidence of generalization to inputs no one
  has looked at yet. (One case's EXPECTED OUTCOME under the rule, not its
  frozen label, does change — `synthetic-adversarial-hold-prose-001`; see
  `results/comparison.md`'s Treatment section for exactly what and why.)
* **Timing, stated honestly.** This amendment (`122c294`) was committed at
  2026-10-17 23:03:40 UTC; the v2 rule rewrite (`6a34f2b`) was committed at
  2026-10-17 23:19:34 UTC — 16 minutes later. Nothing in git records
  whether the v2 rule was drafted entirely inside that 16-minute window or
  had already been drafted (in the working tree, uncommitted) before this
  amendment was committed. This cannot be proven either way from the
  repository's history; it is recorded here rather than asserted one way
  or the other.
* **M1, stated plainly:** `CANDIDATES.md` already said the rule's
  parsing decisions were "arrived at through hand iteration against the
  real 35-case corpus" — that corpus is ALL 35 real cases, including every
  one of the 23 labelled `held-out`. The held-out split was never
  held out from the person writing the rule. Neither v1's nor v2's
  `held-out` numbers in `results/comparison.md` are evidence the rule
  generalizes to handoffs it was not shaped against — they show it
  handles cases from the same corpus its parsing logic was tuned on.
  Additionally: the 35 real cases are not 35 independent examples. They
  reduce to **4 distinct rule inputs** (Angela PASS or NEEDS_REVISION,
  crossed with Interactive Tool "ship" or "do not ship"), all against a
  HOLD report — the real corpus has zero verdict variety and most of its
  apparent sample size is repetition, not variety. `results/comparison.md`
  states this beside the split table rather than reporting "23/23" without
  context.

## Amendment 4 (post-review round 2)

A second independent review of `122c294`, `6a34f2b`, `d847616` (and the
merges up to `7b93dd3`) found one High, residual fail-open gap in v2: a
single DISGUISED or RENAMED field could still make the OTHER field decide
the outcome alone, reaching `CONSISTENT` by accident. Concretely, against
a HOLD report with `Angela verdict: NEEDS_REVISION` and real "ship"
bullets, v2 returned `CONSISTENT` (not `ABSTAIN`) whenever the Shipping
Decision section's loose "is this even attempted" detector failed to
notice the section at all — a renamed header (`## Shipping`, `## Ship
Decision`, `## Publish Decision`, `## Shipping-Decision` with a hyphen
instead of a space), a zero-width space or a Cyrillic homoglyph inside
"Shipping Decision", or no header at all (bullets with nothing introducing
them). The mirror case — a renamed or disguised Angela label (`Angela's
verdict:`, a ZWSP or Cyrillic letter in "Angela", `Reviewer verdict:`)
paired with real, clean "hold" bullets — missed an Angela PASS claim the
same way. Neither case triggered any of v2's existing ABSTAIN branches,
because from the rule's point of view that field was never "attempted" at
all, not malformed — and a field that is absent, by v2's rule-before-this-
amendment, simply does not contribute to the comparison, letting the OTHER
field decide alone.

**The fix, effective immediately (committed in the SAME step as this
amendment, per the review process — code changes follow in the next
commit):** on a HOLD report, `CONSISTENT` now requires BOTH the Angela
line AND the Shipping Decision section to be present and successfully
parsed. A single recognized field can still produce `BLOCK` on its own (a
clean, unqualified Angela PASS, or any clean "ship" bullet, is still acted
on immediately — see Amendment 1-era decision 10, BLOCK still takes
priority). But a single recognized, NON-blocking field (a clean
NEEDS_REVISION with no parseable Shipping section at all, or a clean
"hold"/"do not ship" Shipping section with no parseable Angela line at
all) now resolves to `ABSTAIN`, not `CONSISTENT` — the renamed/disguised
field is simply missing evidence, and missing evidence is never read as
"everything is fine."

**Label impact — verified, not assumed:** the frozen ground-truth label
definition in this file (see "Label definitions" above) is amended
identically, for consistency between what the rule does and what the
label definition says a correct rule should do. Checked directly against
`dataset/`: **all 35 real run_ids have BOTH an Angela verdict line and a
Shipping Decision section present** (verified by reading
`dataset/cases/*.json`'s `handoff.angela_verdict_line` and
`handoff.shipping_decision_lines` for every real case) — so **no real
case's label changes**. Of the 9 synthetic cases, the 3 that have NEITHER
field at all (`synthetic-adversarial-missing-section-001`,
`synthetic-malformed-empty-handoff-001`,
`synthetic-tool-failure-unreadable-handoff-001`) were already `NO_EVIDENCE`
/ `ABSTAIN` under the "neither field attempted" branch that existed before
this amendment and is unchanged by it — **no synthetic case's label or
expected outcome changes either.** `dataset/manifest.json` itself is not
edited by this amendment; only the rule's logic and this file's label
definition change, and both changes land on data this dataset does not
actually contain an example of (every real and synthetic case either has
both fields or neither).

**Scope of the fix:** this closes the specific gap `adv2.py`'s 11
disguised/renamed-field cases demonstrate. It does not change how a field
that IS attempted but fails to parse (markup, decoration, qualifiers,
duplicates, etc. — the round-1 H1 fixes) is handled; those already
ABSTAIN and continue to.

## What this experiment does not show

* It does not fix the pipeline. `~/pipeline` and `~/substack` are never
  modified — the defect this experiment is built around is still live in
  production after this experiment runs.
* It does not measure operator engagement, publish outcomes, or reader
  impact.
* It does not measure human cleanup time (see above — not measured, not
  zero).
* Synthetic-case numbers are not evidence about real pipeline behavior.
* This is a shadow run only (Commit 2, `shadow.py`). Nothing here is
  promoted, wired into the pipeline, or given any authority to block,
  delete, or publish anything. See `capsule/ROLLOUT.md`.

## Open questions for the owner (not resolved by this experiment)

* **Per-artifact vs. run-level scope.** The owner's plan language talks
  about *held artifacts* (per-artifact), but this rule's BLOCK/CONSISTENT/
  ABSTAIN verdict is for the whole run. Whether a finer-grained,
  per-artifact version is worth building is an owner decision, not one
  this experiment makes — see `package_consistency.py`'s boundaries list.
* **Publishing pipeline-excerpt quotes in a public repo.** This repo is
  public. `results/v1/donor-diagnosis-run{1,2}.json` quote short excerpts
  of the private `~/pipeline/q2c_pipeline.py` (function bodies, inline in
  the donor prompt), and this file itself cites that pipeline's private
  line numbers and its git HEAD SHA. Nothing here redistributes the full
  file, and the excerpts are the same handful of lines already summarized
  in this file's Hypothesis section — but whether quoting ANY excerpt of a
  private repo's source in a public one is acceptable is the owner's call,
  not this implementer's. Flagged here rather than decided unilaterally.
