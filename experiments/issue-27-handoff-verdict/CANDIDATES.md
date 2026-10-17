# Issue #27 — Candidate Rule Variants and the Donor-Diagnosis Call

This records the reasoning that produced
`src/governance/package_consistency.py`: what the donor-diagnosis model
call proposed, and which parts of the final rule were accepted, rejected,
or changed, and why. The rule itself (the "recipient") makes zero model
calls at runtime — this file is where the one-time reasoning that shaped
it lives, kept separate from the rule's own behavior, per the Fukasawa
doctrine of migrating stable reasoning into deterministic rules and
recording the migration (see `AGENTS.md`).

## Donor-diagnosis call

Run 1 (`results/donor-diagnosis-run1.json`, timeout 240s) timed out without
an answer — the model's hidden chain-of-thought exceeded that budget, the
same failure mode documented in PROTOCOL.md for Baseline B generally.
Run 2 (`results/donor-diagnosis-run2.json`, PROTOCOL.md Amendment 1, same
prompt, timeout raised to 600s) succeeded: 372.1s wall time, 750 prompt
tokens, **5706 completion tokens of hidden reasoning** before a 676-character
final answer. That ratio — over 8 tokens of invisible reasoning for every
1 token of visible answer — is itself relevant evidence for why this
reasoning is captured once, here, rather than re-run at runtime.

Full verbatim response:

> The root cause of the contradiction is that `build_duath_operator_handoff`
> determines shipping decisions based on `angela_result` and `scope` flags
> independently of the deterministic `findings` list used by
> `build_package_quality_report`, allowing the handoff to declare "ship"
> even when `findings` are present and the official quality verdict is
> "HOLD".
>
> **Proposed Check:**
> Modify `build_duath_operator_handoff` to accept the `findings` dictionary
> from `build_package_quality_report` and enforce `ships = False` for all
> artifacts (Article HTML, Visual support, Interactive tool) if
> `len(findings) > 0`, overriding any `scope` or `angela_result` signals
> that indicate "ship".

**What was accepted:** the root-cause diagnosis is exactly right and
matches the independently-derived evidence in PROTOCOL.md's Hypothesis
section (two documents computed independently, never reconciled). The
donor's proposed check targets the SAME two functions and the SAME
mechanism (findings count / verdict vs. the handoff's ship claim) that
`check_package_consistency()` actually compares.

**What was NOT adopted as proposed, and why:** the donor's fix is a
**pipeline-side change** — it proposes editing
`build_duath_operator_handoff` itself (inside `~/pipeline/q2c_pipeline.py`,
private, out of scope: "NEVER modify ~/pipeline"). This repo's deliverable
is a Level-0 **external check** that compares the two documents' *existing*
output after the fact, without touching the pipeline that produces them —
a deliberately more conservative, reversible intervention (see
`capsule/ROLLOUT.md`'s shadow→advisory→blocking staging) than rewriting
the function that generates the handoff. The donor call was asked for "a
minimal deterministic check" and gave a correct one for a different
integration point than the one this issue's Level-0 rule occupies; its
diagnosis was kept, its implementation site was not.

## Rule design decisions — accepted, rejected, and why

These were arrived at through hand iteration against the real 35-case
corpus plus the synthetic adversarial set, informed by (but not copied
verbatim from) the donor call's proposal:

1. **Accepted: compare only the parsed VALUE of a Shipping Decision line,
   not the whole line's text.** An early version checked whether the
   substring "ship" appeared anywhere in the line. Rejected once the
   adversarial case `synthetic-adversarial-hold-prose-001` was written
   (`"- Article HTML: hold (ship once blockers fixed)"`) — a hold decision
   that mentions "ship" in prose must not be flagged. The final rule
   extracts `label: value` with `_SHIPPING_LINE_RE` and checks only
   whether `value.lower().startswith("ship")`.

2. **Accepted: treat a qualified verdict ("NEEDS_REVISION") as not a PASS
   claim, using an explicit disqualifying-word check, not just "does the
   line contain the substring PASS".** Rejected a naive `"PASS" in line`
   check early on, because `"Angela verdict: NEEDS_REVISION"` does not
   contain the substring "PASS" anyway in this corpus, but a value like
   "PASS WITH CONDITIONS" (not observed in this corpus, but plausible)
   would. The rule uses `\bpass\b` plus an explicit scan for
   `needs|revision|fail` and refuses to call it a pass if any of those
   appear.

3. **Rejected: abstain whenever the Shipping Decision section is absent,
   even if the Angela verdict line alone says PASS.** The label definition
   given for this experiment is explicit: CONTRADICTION fires on
   "Angela PASS **or** any ship line" — an OR, not an AND requiring both
   fields. So the rule only ABSTAINs when **both** fields are absent
   (`synthetic-adversarial-missing-section-001` has neither field at all);
   an Angela-PASS-only handoff against a HOLD report is still a BLOCK on
   its own.

4. **Rejected: flag the reverse case (a PASS report with an
   over-conservative, all-hold handoff).** This is explicitly out of scope
   per the owner's original plan
   (`docs/source-archive/2026-05-31-fukasawa-quality-orchestrator-plan.md`,
   "Duath/Angela PASS cannot override deterministic blockers" — a
   one-directional rule about *over*-authorization, not under-caution).
   Documented as a boundary in the function's docstring and pinned by
   `test_pass_report_is_out_of_scope_for_over_conservative_handoffs`.

5. **Rejected: a confidence score on the result, mirroring the pipeline's
   own `quality_finding()` shape (`confidence: {level, reason}`).** This
   function is a pure deterministic comparison — the same two inputs
   always produce the same output — so there is no probabilistic
   uncertainty to score. A confidence field would imply graduated trust
   that does not exist here. `process_capsule.yaml`'s `output_schema`
   states this explicitly ("not scored").

6. **Accepted: `handoff_text=None` and `quality_report=None` are the only
   vocabulary for "I/O failed" — the function does not distinguish missing
   from empty from unreadable.** Considered adding a richer input type
   (e.g. a tagged union of `Missing | Empty | Unreadable(error)`) to carry
   more diagnostic detail into the ABSTAIN reason. Rejected for Commit 2 as
   unnecessary complexity for a Level-0 rule whose only job is to decide
   BLOCK/CONSISTENT/ABSTAIN — the caller (whoever eventually does the file
   I/O, in a future Advisory-stage integration, per `ROLLOUT.md`) is
   better positioned to log the specific I/O error if that ever matters.

7. **Accepted: escalation target is always the literal string
   `"human operator"`, never an agent name.** Matches the task brief's
   "ABSTAIN → human operator" and `AGENTS.md`'s rule that routine workflows
   should not require Level 5 reasoning and non-deterministic steps must
   justify themselves — abstaining to an unnamed agent would just move the
   same undecided question somewhere else without resolving who is
   accountable for it.
