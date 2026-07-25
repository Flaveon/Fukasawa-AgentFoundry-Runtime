# Agent Completion Note — Phase Handoff 02 Architecture Review

**Performed by `claude-fable-5`, not Opus 4.8.** The session model was
switched to `claude-fable-5` before this phase ran. Deliverable filenames
follow the specified paths so the pipeline resolves them; attribution is
corrected inside each document. Master handoff §19 Gate G ("selected critical
diffs reviewed by Opus") is **not** satisfied by this phase.

## Scope completed

- Challenged the Fable architecture audit; answered all 12 Phase Handoff 02
  review questions — `opus-architecture-review.md`.
- Ruled on all 7 ADRs: 2 approved unchanged, 5 approved with binding
  revisions — `approved-adrs.md`.
- Produced the Codex directive with all 8 required sections, including the
  authoritative per-rule blocking table — `codex-implementation-directive.md`.
- Reviewed schema ownership, promotion invariants, migration/back-compat,
  security/permissions/auditability, and overengineering.
- No production code written; no source file touched.

## Files changed

Created only: `handoffs/reviews/opus-architecture-review.md`,
`approved-adrs.md`, `codex-implementation-directive.md`,
`opus-completion-note.md`.

## Tests run and results

`.venv/bin/python -m pytest -q` on `feature/human-cooperative-workflow-runtime`:
**113 passed, 4 skipped** — baseline intact (docs-only change). Both Oldowan
examples re-validated on this branch: brief (6 states, 5 transitions, 2 gates)
and graph (5 nodes, 1 human gate).

## Decisions made

Eight defects found; rulings summarized:

- **D1 (blocking):** the DoD's cross-language clauses are NOT APPLICABLE —
  no TypeScript exists and §9.2 is self-voiding. Substituted JSON Schema
  export + golden tests; **Gate B reworded**. Needs operator ratification.
- **D2 (blocking):** the pilot was sequenced last, leaving the design
  unvalidated and starving Gate C of realistic fixtures. Split it across
  phases; `observed-workflow.yaml` moves to phase 1.
- **D3:** constrained `AccountableWorkflow` so it is not a second
  `WorkflowBrief` — reuse `WorkflowStep`, no states/transitions vocabulary,
  flatten only at export. Considered and rejected the cheaper
  envelope-around-`WorkflowBrief` design, with reasons recorded.
- **D4:** enforce promotion gates only through `RUNTIME_READY`; `DEPLOYED`/
  `VALIDATED` delegate to existing run/eval evidence.
- **D5:** defined "blocking" as blocking *promotion*, never capture; fixed the
  per-rule table (14 blocking, 2 non-blocking).
- **D6:** actor attribution is self-attested, not authenticated; ship with the
  ceiling documented, backlog Ed25519-signed acceptances.
- **D7:** corrected ADR-007 — the domain modules are the authoritative service
  layer, `src/gui/services.py` is an adapter. This fixed a real ordering bug
  where phase 6 (CLI) would have depended on a phase-7 file.
- **D8:** baseline artifact is recorded and committed in phase 1, not phase 8.

## Assumptions

- The master handoff v1.0 governs; where its §3/§9.2 assert TypeScript, the
  repository inspection wins (its own §3 instructs agents to inspect rather
  than assume).
- Operator confirmation "Python-only today, TS possible later" still holds.
- Phase 1 may begin before D1 is ratified because no phase-1 file depends on
  it; only Gate B evaluation is blocked.

## Known limitations

- **This is a self-review.** The same model authored the audit under review.
  D2/D3/D7 overturn that model's own earlier design, which is the evidence it
  was performed adversarially — but an independent reviewer would still be
  worth more, and Gate G explicitly wants Opus.
- No diffs were reviewed (none exist yet); this is design-only review.
- Line/path citations were verified at `0ac4b2e` and will drift as code lands.
- The per-rule blocking table is a judgement call on 16 heuristically-defined
  rules; expect Gate C tuning, particularly HW-008, HW-013, HW-014.
- Cost: no bulk code, single-pass authoring, no repository re-discovery. I
  cannot meter spend from inside the session, so the Fable budget cap is
  honored by scope discipline rather than a measured counter.

## New risks or defects

- **Gate A cannot close** on two operator decisions: ratify the D1 DoD
  amendment, and accept or reject the reviewer substitution.
- New risk (not in the register): the cooperation **safety floors** are the
  single safety-critical mechanism of the release and live in one function.
  They need their own dedicated test, called out in the directive §5.
- Confirmed-standing risk: the pending cross-repo gitleaks task should land on
  this repo **before** the pilot merges — the pilot describes a real
  publication workflow (risk R11).

## Recommended next action

Operator: ratify or reject the D1 DoD amendment and the reviewer
substitution. Then Codex begins **phase 1 (contracts)** per
`codex-implementation-directive.md` §2, starting with
`artifacts/test-baseline.txt` before any feature work (§15.1).

If a genuine Opus review is wanted, switch the session model and re-run Phase
Handoff 02 against these same inputs; this document set is then superseded
rather than amended, so the provenance stays clean.

## Exact starting point for next agent

Branch `feature/human-cooperative-workflow-runtime` @ head (this commit).
Read: `codex-implementation-directive.md` in full → §4 blocking table →
`approved-adrs.md` for the 5 binding revisions → ADR-002 for the freeze.
Baseline: 113 passed, 4 skipped. First file to create:
`artifacts/test-baseline.txt`. First code: `src/schemas/human_workflow.py`.
Do not touch any file listed FROZEN in directive §3.
