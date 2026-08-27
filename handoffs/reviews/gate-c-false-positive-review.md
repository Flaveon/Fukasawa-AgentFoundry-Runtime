# Gate C — validator false-positive review

**Date:** 2026-08-21
**Reviewer:** `claude-opus-5`, phase 8.
**Closes:** the last open item on Gate C (§19), and risk **R9** in
`handoffs/implementation/risk-register.md`.
**Rule set version:** 1, all 16 rules.

## Why this was still open

Phase 2 implemented the rules and left the review explicitly unfinished:

> **The Gate C false-positive review is started, not finished.** The evidence
> so far is one clean fixture reporting zero plus 80 tests. A real review needs
> more genuine workflows than the two fixtures and the pilot.
> — `phase-2-validator-completion-note.md`

That is the correct standard. One clean fixture proves the rules are quiet on
the workflow they were **tuned against**, which is close to no evidence at all.
R9's concern is trust: rules that flag noise on real workflows teach operators
to skip the report, and a skipped report is worse than no report.

## Method

Three new workflows were written in domains deliberately unlike the expense-
approval fixture and unlike the Substack pilot, by someone writing as a
practitioner in that domain rather than writing to satisfy the rules. Writing
to the rules is how a false-positive review talks itself out of finding
anything.

| Fixture | Domain | Shapes it exercises |
|---|---|---|
| `incident-response.yaml` | on-call / SRE | a mitigation **cycle** (`mitigate ↔ verify-recovery`), branch on severity, gate mid-graph, exception routing back into an earlier step |
| `hiring-loop.yaml` | recruiting | **two terminal steps** (offer / decline), sensitive data throughout, a rejection that legitimately *ends* the workflow, an exception looping back one step |
| `board-assembly.yaml` | hardware manufacturing | **three consecutive steps by one actor**, a **machine as actor**, a rework loop, a failure with `next_step: null`, a gate with `on_approve: null`, two terminal steps |

The shapes were chosen as the classic traps: a legitimate terminal step reading
as a dead end (HW-007), same-actor steps reading as a handoff (HW-008), a cycle
reading as unreachability (HW-006), a null next-step reading as an unhandled
failure (HW-011).

Then the two heuristic rules — HW-013 and HW-014, the pair R9 names — were
probed directly at the function level with prose containing their trigger words
in legitimate, checkable sentences.

## Result 1 — the structural rules are clean

**All three workflows report zero findings.** Every trap above stayed silent
correctly:

- a terminal step that produces a verifiable output is not a dead end;
- consecutive steps by one actor raise no handoff finding, because no work
  crosses an actor boundary;
- a cycle does not confuse reachability;
- `next_step: null` on an exception path is accepted as "this failure ends the
  work", which is a real outcome — scrapping a panel is not an unhandled
  failure.

Twelve of the sixteen rules are structural or reference-based and, on this
evidence, are not a false-positive risk. HW-004 and HW-007 in particular were
deliberately narrowed in phase 2 and the narrowing holds up: neither fired on
any of the three.

All three are now committed under `tests/fixtures/workflows/` and asserted by
`TestBaselineIsClean::test_every_clean_fixture_reports_nothing`, which
**discovers** fixtures by glob rather than listing them, so the next one added
is guarded automatically. A companion test fails if the guard set ever drops
below four domains.

## Result 2 — a real defect in HW-014, fixed

The ambiguous-term scan anchored its word boundary on the **leading edge only**:

```python
re.search(rf"\b{re.escape(t)}", low)      # before
re.search(rf"\b{re.escape(t)}\b", low)    # after
```

So an ambiguous term matched as a **prefix of a longer, entirely precise word**.
Confirmed cases, all of which were reported as vague:

| Exit condition | Matched on | Should be |
|---|---|---|
| "…the **goods** receipt matches the packing list" | `good` | silent |
| "…the **cleanroom** gowning checklist is fully signed" | `clean` | silent |
| "…the **cleaning** log has an entry for this shift" | `clean` | silent |
| "…**completeness** is confirmed against the manifest" | `complete` | silent |
| "…**doneness** is measured at 74 degrees core" | `done` | silent |
| "…the **okra** crate count matches the delivery note" | `ok` | silent |
| "…the mesh is **finely** ground to under 200 microns" | `fine` | silent |
| "…**goodwill** is recorded on the ledger at the agreed sum" | `good` | silent |

This is not a policy question. The rule's own docstring says a term is ambiguous
when the text "states no more than 'done when it feels done'" — `goods receipt`
states a great deal more, and the match was simply wrong by the rule's stated
intent.

**Fixed**, with eight parametrized regression cases plus one test that the terms
still fire as whole words, so the fix cannot buy silence by breaking detection.
Verified by mutation: reverting the boundary makes six of the nine fail.

The committed pilot artifacts are byte-identical before and after — the pilot
happened to contain no substring collisions, which is exactly why this survived
to phase 8.

## Result 3 — the residual, measured and accepted

What remains cannot be fixed by a deterministic keyword scan, and this section
exists so that the next person to see one of these findings knows it was
examined rather than missed.

### HW-014 — perception terms that are also ordinary words

`PERCEPTION_TERMS` are **never** rescued by an accompanying criterion, by
design: no amount of grammar turns "looks fine" into something checkable. But
three of those terms have precise non-perceptual senses:

| Legitimate text | Fires on | Why it is not fixable here |
|---|---|---|
| "…the panel has been wiped **clean** with IPA and dried" | `clean` | physical state vs. aesthetic judgement — same word |
| "…the **quality** inspection report QA-114 is attached" | `quality` | part of a proper noun |
| "…the last **good** self-check is under 24h old" | `good` | "known-working" vs. "seems fine" |

Distinguishing these needs to know what the sentence is *about*, which is
semantics. The alternatives were considered and rejected:

- **Drop the terms.** Loses the true positives, which are the common case —
  "done when it looks clean" is exactly what this rule is for.
- **Add negative context patterns** ("clean with", "quality report"). An
  unbounded list of exceptions, each one a guess, and it makes the rule
  unpredictable — which breaks the property the rule catalog promises: that a
  human can predict what fires before running it.
- **Use a model.** Forbidden in any authoritative path (directive §6.5), and
  correctly so.

**Accepted.** HW-014 is non-blocking, its finding names the exact term it
matched, and the operator can accept it in one action with a reason recorded.
That is the designed handling for a rule that is right most of the time.

### HW-013 — memory phrases about machines

Two entries in `MEMORY_PHRASES` attach to non-human subjects:

| Legitimate text | Fires on |
|---|---|
| "The test rig **remembers** the last calibration until power-cycled" | `remembers` |
| "The cache **remembers** the previous response for sixty seconds" | `remembers` |
| "The API returns an **undocumented** field that the parser ignores" | `undocumented` |
| "**Undocumented** behaviour in the vendor firmware causes the retry" | `undocumented` |

`undocumented` is the loosest: it is a bare adjective that attaches to anything,
while every other phrase in the list names a *human* relationship to knowledge
("in their head", "tribal knowledge", "nobody wrote", "just knows").

**Not changed, deliberately.** Removing `undocumented` would also drop a real
true positive — "the threshold is undocumented" *is* a memory dependency — and
narrowing a published rule's detection policy is a different kind of decision
from fixing a boundary bug. The rule catalog is a contract, and this belongs to
whoever owns rule policy, not to a review pass. **Recorded as a backlog item.**

Note that HW-013's primary path is not the prose scan at all: it reads
`unwritten_rules` directly, which is where honest capture puts this information.
The prose scan is a secondary net, and a secondary net with some slack in it is
the right trade for a non-blocking rule.

## Verdict

**Gate C closes.**

| Criterion (§19 Gate C) | Status |
|---|---|
| Initial rule set implemented | met — 16 rules, 1:1 with §7 |
| All rule tests green | met — 94 passed, 1 skipped in `test_workflow_rules.py` |
| Reports are actionable | met — every finding carries rule, location, field, severity, remediation |
| **False-positive review complete** | **met — this document** |

One defect found and fixed, one residual measured and accepted with reasons, and
the guard set went from one clean workflow to four across four domains.

## Follow-ups recorded, not done

1. **`MEMORY_PHRASES` contains `undocumented`, which fires on software rather
   than people.** A policy decision for whoever owns the rule set. → backlog.
2. **HW-013's phrase list is English and literal**, carried forward from phase 2
   — it matches "it's all in Dave's head" but not "Dave is the only one who
   knows". Unchanged by this review. → backlog.
3. **The guard fixtures are hand-written.** Master handoff §11.4 assigns
   adversarial fixture generation to Grok Build; that pass has still not
   happened and would be a cheap strengthening of what this review started.
