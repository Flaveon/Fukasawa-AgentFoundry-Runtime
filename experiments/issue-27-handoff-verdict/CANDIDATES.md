# Issue #27 — Candidate Rule Variants and the Donor-Diagnosis Call

**Corrected provenance claim (post-review — see PROTOCOL.md Amendment 3,
H2):** an earlier version of this file said this document "records the
reasoning that produced `src/governance/package_consistency.py`" and that
the rule's design was "informed by (but not copied verbatim from) the
donor call's proposal." That is not supported by the actual timeline and
is corrected here rather than left standing.

**What actually happened, in order:** `src/governance/package_consistency.py`
and all seven design decisions below were written by the implementing
agent BEFORE the donor-diagnosis call produced any answer. PROTOCOL.md's
own Disclosure (on Commit 1) says the rule was drafted in the working tree
before 08:06:48 on 2026-10-17. The donor call's first attempt
(`results/v1/donor-diagnosis-run1.json`, 240s timeout) **timed out with no
answer at all**. Its only successful attempt
(`results/v1/donor-diagnosis-run2.json`, 600s timeout, PROTOCOL.md
Amendment 1) did not return until **08:15:29** that same morning — after
the rule existed. There is no accepted design decision among the seven
below that traces to the donor's output; none of them changed, or could
have changed, as a result of that call.

**The donor call also did not independently discover its own answer.** Its
prompt (`baseline.py::DONOR_PROMPT`, reproduced in
`results/v1/donor-diagnosis-run2.json`) hands the model exactly the real
run_ids where "the quality report said HOLD but the operator handoff's
Shipping Decision said ship / Angela verdict said PASS for the same run" —
the model was told the shape of the contradiction and asked to diagnose
it. Its answer agreeing with a diagnosis it was given is not the same
claim as "a model found this independently."

**Conclusion, stated plainly: issue #27 checklist item 4 ("generate a
candidate agent/rule from higher-depth reasoning, using the existing model
adapters") is NOT demonstrated by this branch.** No new donor call was run
to try to retroactively manufacture that traceability — doing so after
seeing this finding would only repeat the same problem (a model confirming
an answer it has already effectively been given) while appearing to fix
it. The donor call stands as what it actually was: a confirmation call
made after the fact, kept below for its own, separate value (see "What
remains true" below) — not as this rule's origin story.

## Donor-diagnosis call (a confirmation made after the rule was written, not its origin)

Run 1 (`results/v1/donor-diagnosis-run1.json`, timeout 240s) timed out
without an answer — the model's hidden chain-of-thought exceeded that
budget, the same failure mode documented in PROTOCOL.md for Baseline B
generally. Run 2 (`results/v1/donor-diagnosis-run2.json`, PROTOCOL.md
Amendment 1, same prompt, timeout raised to 600s) succeeded, **after the
rule already existed**: 372.1s wall time, 750 prompt tokens, **5706
completion tokens of hidden reasoning** before a 676-character final
answer.

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

**What remains true despite the corrected provenance:** the diagnosis is
*correct* — it matches the independently-derived evidence in PROTOCOL.md's
Hypothesis section (two documents computed independently, never
reconciled) — and its proposed check targets the same two functions and
the same mechanism (findings count / verdict vs. the handoff's ship claim)
that `check_package_consistency()` compares. It is evidence the diagnosis
is right, corroborating what the implementing agent had already written
down; it is not evidence about where the rule came from.

**Why the donor's proposed fix was not adopted as written, independent of
the provenance question:** the donor's fix is a **pipeline-side change** —
it proposes editing `build_duath_operator_handoff` itself (inside
`~/pipeline/q2c_pipeline.py`, private, out of scope: "NEVER modify
~/pipeline"). This repo's deliverable is a Level-0 **external check** that
compares the two documents' *existing* output after the fact, without
touching the pipeline that produces them — a deliberately more
conservative, reversible intervention (see `capsule/ROLLOUT.md`'s
shadow→advisory→blocking staging) than rewriting the function that
generates the handoff.

## Rule design decisions — accepted, rejected, and why

These were arrived at through hand iteration by the implementing agent
against the real 35-case corpus plus a synthetic adversarial set, **before
the donor call returned any answer** (see the corrected provenance note
above). "M1" in PROTOCOL.md's Amendment 3 also applies here: "the real
35-case corpus" is the same corpus that includes every `held-out` case, so
none of this hand iteration was validated against anything the rule had
not already seen:

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

## v2 rewrite (post-review, H1: fail CLOSED) — new decisions

v1's items 1-7 above describe hand-tuned string matching ("value starts
with ship", "value contains PASS minus a qualifier"). The independent
review (PROTOCOL.md Amendment 3) found this fails OPEN: anything it could
not confidently parse was read as "not ship" and returned CONSISTENT. v2
replaces the matching entirely with an allowlist — every field is either a
recognized shape+value, or unparseable, and unparseable is always
ABSTAIN. New decisions made during that rewrite:

8. **Accepted: NFKC-normalize before matching, then apply the allowlist to
   the normalized text.** A non-breaking space between "Angela" and
   "verdict", or a fullwidth Latin "ｓｈｉｐ", both NFKC-normalize to plain
   ASCII — these are cosmetic width/whitespace conventions, not disguises,
   and recognizing them (`angela_nbsp` → BLOCK, `fullwidth_ship` → BLOCK in
   `tests/test_package_consistency.py::ADVERSARIAL_CASES`) is the correct,
   safe direction: it still catches a real "ship" claim. A genuine
   homoglyph (Cyrillic "Ѕ" in "Ѕhip", Cyrillic "Р" in "РASS") is NOT a
   compatibility variant of a Latin letter — NFKC does not touch it, so it
   still fails the allowlist and ABSTAINs, as it should.

9. **Accepted: a blank line that SPLITS a Shipping Decision section's
   bullets into more than one paragraph aborts to ABSTAIN; a blank line
   immediately after the header, before a single clean paragraph of
   bullets, does not.** The distinction is whether content could be
   silently lost: `blank_after_header` (nothing after the one blank line
   but the bullets themselves) resolves normally; `blank_between_bullets`
   (a real "ship" bullet sits after the blank line) would silently drop
   that bullet if only the first paragraph were read, so it ABSTAINs
   instead of guessing.

10. **Accepted: a clean, resolved BLOCK signal takes priority over an
    ABSTAIN from an unrelated, separately-garbled field.** If Angela's
    line is undecorated and says PASS, that is acted on even if the
    Shipping Decision section elsewhere is malformed (and vice versa for a
    clean "ship" bullet with a garbled Angela line) — see
    `test_block_takes_priority_over_an_unrelated_abstain_worthy_field`.
    Burying an already-unambiguous "ship this" claim under an ABSTAIN
    because some OTHER part of the page is noisy would be a worse outcome
    than surfacing both: a missed escape that was already in hand is worse
    than an incomplete-but-actionable alert.

11. **Rejected (reverted from an earlier version of this file): claiming
    "informed by the donor call's proposal".** See the corrected
    provenance section above (H2) — nothing here traces to donor output.

12. **Accepted: `synthetic-adversarial-hold-prose-001`'s expected outcome
    changes from CONSISTENT (v1) to ABSTAIN (v2).** v1 cleverly read
    "hold (ship once blockers fixed)" as "value starts with hold, so it's
    fine" — exactly the kind of clever-but-brittle matching that caused
    H1. v2's exact-match allowlist does not treat a decorated/suffixed
    value as the clean token it resembles; it ABSTAINs. This is a
    deliberate behavior change, not a bug: it is stricter, and strictness
    in the ABSTAIN direction is the entire point of the rewrite.
