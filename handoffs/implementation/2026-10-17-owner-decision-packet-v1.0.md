# Owner decision packet — 2026-10-17

Decisions this run could prepare but must not make. Each item says what is
true now (with the code or record that shows it), the options, and a
recommendation. Nothing here has been implemented on the strength of a
recommendation alone.

Answer by number. "Recommended" is a suggestion, not a default that applies
if you say nothing.

---

## 1. "Check again" overwrites the standing look permission

**What is true now.** `check_node` (`src/gui/services/nodes.py:481`) looks at
one recorded computer by going through `scan()` at one-named-computer reach.
`scan()` records the permission it acts under before it reaches out
(`src/gui/services/nodes.py:377`, `ScanConsent.granted(scope, actor)`). So a
person whose standing answer was "just this computer", who then presses
**Check again** on a recorded machine, now has "one named computer" as their
standing answer. Nobody asked them. The terminal's typed-in check does the
same. Recorded as open in `handoffs/phase-10a-node-and-capability-handoff.md`
(Task 8 note) and the phase 10a completion note; never ruled on.

**Your earlier rulings that bear on it** (same handoff, "Using a recorded
computer does NOT need its own permission"): the four-rung consent exists for
*discovery* — reaching machines nobody named. "Unattended reaching needs
permission; directed use is already permitted." Registering a computer is the
authorisation to use it.

**Options.**
- **A. A check on a recorded computer does not write the permission at all.**
  It is directed use of a computer you registered, so by your rule it needs
  none and should leave your standing answer alone. *Recommended* — it is the
  reading your own rule gives.
- B. Keep today's behaviour (consistent: every reach records the reach it took).
- C. Write the permission only when the standing answer is "don't look".

Scope if A: `check_node` and the CLI typed-in check stop calling
`set_consent`; one test per front end that the standing answer is unchanged
after a check. No new prompt.

## 2. Phase 10b — a step that no recorded computer can run

**What is true now.** Phase 10a records computers and what they can run;
nothing connects a workflow step to a computer
(`tasks/backlog.md`, "Capabilities are not connected to cooperation
assessment"). `CooperationAssessment.required_tools` and
`StepAssignment.runtime_requirements` are free strings nothing checks.

**The question.** When no recorded computer can run a step, what happens?
- A. **Advisory warning only.** The workflow promotes; the warning is shown at
  assessment and export. Safest first step, nothing blocks. *Recommended for
  the first cut.*
- B. Lowers the step's automation readiness (it becomes a person's step until a
  capable computer is recorded).
- C. Blocks promotion past *assessed*.

Constraints carried in any option: steps keep naming endpoints, never
addresses; capabilities stay local and never enter an exported brief; a
workflow with zero recorded computers still works with every step assigned to
a person. Also needed: your earlier wish that a workflow can be created with no
computer recorded and bound at activation ("workflow placeholders"), which
touches the workflow schema and wants its own spec section.

Not started. It needs your answer and its own design document.

## 3. Your LAN addresses in public history; the example hostname

**What is true now.** Commit `93e4d64` (Phase 5B) put real private-range
addresses in the default endpoint config; `9d49d56` removed them. The current
tree is clean (`tests/test_hardening.py::test_no_private_address_is_published`
scans every tracked file), but the history still has them. Separately, one of
your machines' hostnames is also the name of an example workflow and appears
in several tracked files; running the forbidden-name test with your hostnames
finds only that one, and it predates this run.

**Options.**
- A. Leave history as is; accept that those addresses are public. Private-range
  addresses are not reachable from outside your network; the exposure is
  layout information. *Recommended* unless the addresses are still in use for
  anything you consider sensitive.
- B. Rewrite history (force-push). Breaks every clone and fork, every PR link to
  an old SHA, and is not fully effective once the history was public.
- For the hostname: A. leave it; B. rename the example workflow (a broad
  rename across examples, tests and docs).

No history rewrite or rename has been done.

## 4. HW-013 / HW-014 phrase policy

**What is true now.** `handoffs/reviews/gate-c-false-positive-review.md`
records known false positives in the human-memory phrase list (`undocumented`,
`remembers` fire on machines) and that HW-013 matches literal English phrases
only. Removing a phrase also loses real true positives — a trade-off, not a
bug. Both rules are advisory (non-blocking).

**Options.** A. Keep as is (recorded trade-off). B. Drop `undocumented` and/or
`remembers`. C. Require a human subject near the phrase (a rule change, needs
its own tests across the four guard domains).

No change made; it is detection policy, which is yours.

## 5. Network sweep, more inference engines, a specialist model

Roadmap items. Not prerequisites for issue #27 and not started. Listed so
their absence is a decision, not an omission.

## 6. The pilot asks for approval after the irreversible step

**What is true now.** In the exported Substack pilot brief, the agent's
transition `publish-post → publish-post-pending-approval` (GUIDED) requires the
evidence "live post URL". The CONSCIOUS human decision comes only at
`pending-approval → archive-notes`. So as written, the post is live before the
person approves it; an earlier human go/no-go step mitigates but does not fix
the ordering. Found by the independent release verification (C5, finding F3).

**Options.** A. Move the human approval before publishing (approval evidence =
the final draft and destination; publishing then requires that approval).
*Recommended* — it is what "agent prepares, human approves" means.
B. Keep the order and rename the state so it does not claim pending approval.

This is the pilot's workflow content, which is yours; not changed.

## 7. Two names for one computer (host case, localhost vs 127.0.0.1)

**What is true now.** `Box.LAN` and `box.lan`, or `localhost` and
`127.0.0.1`, are recorded as two computers. Lower-casing host names is
standard and safe; treating `localhost` as `127.0.0.1` is a judgment (they can
differ on IPv6-only setups). **Options.** A. Lower-case host names only.
*Recommended.* B. Also fold `localhost` into `127.0.0.1`. C. Leave as is.

## 8. Issue #27 — decisions the reconciliation needs

`docs/issue-27-intent-reconciliation-v1.0.md` §4 lists nine. In short:
(1) the Q2C pipeline stays the producer and checker, this runtime records
diagnosis, evaluation and migration — yes/no; (2) complexity budget 1A/1B/1C;
(3) non-conformance diagnosis 2A/2B/2C, and keep corrective and preventive
classes as two lists — yes/no; (4) downward migration 3A/3B/3C; (5) lift the
ObservationPacket draft status with optional added fields — yes/no; (6) the
three-loop retry stays pipeline policy — yes/no; (7) record cost by a wrapper
outside the frozen kernel — yes/no; (8) add the missing regression tests to the
private pipeline — yes/no; (9) "transfer capsule" vs "work capsule" naming in
docs only — yes/no. Recommendations are in the document.

Plus: **#27 cannot close without you.** Its checklist requires your decisions
on divergences, your review of the candidate rule, and your approval of a
gated promotion. The shadow evaluation prepares the evidence; it does not
promote anything.

## 9. Things found in the private Q2C pipeline (not changed — different repository)

- The pipeline's only deterministic release gate (`quality-report.json`) has
  not produced output since 2026-07-03, while daily packages kept being made:
  about 70% of packages since then had no deterministic check at all.
- Of the 35 runs that do have a gate result, all 35 were HOLD, and 24 of their
  operator handoffs said "Angela verdict: PASS" and "ship" anyway — the handoff
  derives its shipping decision from deployment scope, not from the gate.
  This is the defect #27's first case targets.
- The pipeline discards model token usage, and nothing records wall time or
  human edit time, so cost baselines do not exist and are reported as unknown.

## 10. Gate G

Gate G's two open items were Jules's independent verification pass and review
of three Jules commits. This run supplied independent technical evidence for
both (Claude Opus reviewers — not Jules, not you): the three commits were found
behaviour-preserving, and the release checklist was re-run end to end. The
findings those passes raised are fixed on open PRs. **Whether that evidence
satisfies Gate G, or Jules's pass is still required, is your decision.**

## 11. Merging

This run prepared PRs, ran independent reviews and confirmed CI, but merging
was refused by the session's permission policy ("merge without review"). Each
PR lists its reviews; merging is yours.

## 12. Paused runs from before the brief-pinning fix

**What is true now (on `fix/gate-g-review-findings`).** A paused run now
continues only under the brief it started with. Runs started before the fix
carry no record of which brief that was, so they are refused — the safe
default — and the refusal says how to start a fresh run; the old run stays in
the ledger as history. **Question:** should there also be an explicit,
recorded override ("continue under the current brief", with who decided and
why, written to the append-only ledger, like accepting a risk)? *Recommended:*
no, unless you have paused runs you need to finish — a fresh run loses
nothing the ledger needs, and every override is one more way round a guard.
