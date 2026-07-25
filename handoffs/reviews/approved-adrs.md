# Approved ADRs — Phase Handoff 02 ruling

**Date:** 2026-07-25. **Reviewer:** `claude-fable-5` (see the provenance note
in `opus-architecture-review.md` — Phase Handoff 02 nominally assigns this to
Opus 4.8; it was not performed by Opus).
**Source:** `handoffs/implementation/adr-proposals/adr-00{1..7}`.

Status vocabulary: **APPROVED** = implement as written.
**APPROVED WITH REVISIONS** = implement with the amendment below; the
amendment is binding and overrides the proposal text.

| ADR | Subject | Status |
|---|---|---|
| 001 | Canonical schema ownership | **APPROVED WITH REVISIONS** |
| 002 | Schema versioning and migration | **APPROVED** (no change) |
| 003 | Validator rule registry | **APPROVED WITH REVISIONS** |
| 004 | Graph representation | **APPROVED** (no change) |
| 005 | Promotion state machine | **APPROVED WITH REVISIONS** |
| 006 | Cooperation policy engine | **APPROVED WITH REVISIONS** |
| 007 | Desktop / service boundary | **APPROVED WITH REVISIONS** |

---

## ADR-001 — Canonical schema ownership → APPROVED WITH REVISIONS

Pydantic v2 in `src/schemas/` as the single canonical source is correct and
matches the factual status quo. Amendments:

1. **The TypeScript obligation is void for this release** (defect D1). JSON
   Schema export ships as the *forward* generation seam, not as evidence of
   current cross-language agreement. Its release obligation is: exported
   artifacts exist, are golden-tested for stability, and are documented as
   the mandatory generation source for any future non-Python consumer.
2. `docs/schema-reference.md` must state explicitly that `specs/*.md` are
   superseded July-18 drafts and `docs/architecture.md` is aspirational —
   neither is a contract. Future agents have already been observed treating
   them as authoritative.
3. Doctrine rules enforced in Python validators (e.g. the CONSCIOUS-owner
   rule) are invisible in JSON Schema output. The schema reference must list
   them in prose beside the generated artifacts, or a generated consumer will
   silently accept data the runtime rejects.

## ADR-002 — Schema versioning and migration → APPROVED

No changes. This is the strongest ADR in the set and the freeze it imposes is
the most valuable single finding of the audit.

Emphasis for the implementer: the reason `GraphSpec` and `BundleManifest` are
frozen is that signatures are computed over `model_dump(mode="json")`, which
**includes defaulted fields** — so even an optional field with a default
changes the canonical bytes and invalidates every `.sig` in the field plus
every hash-pinned graph resume. The golden-hash contract test is not optional
polish; it is the tripwire. If a phase needs to touch either schema, that is a
**stop-and-escalate** condition, not a judgement call.

## ADR-003 — Validator rule registry → APPROVED WITH REVISIONS

Registry-of-plain-functions is right; no DSL. Amendments:

1. **"Blocking" is defined as blocking promotion to `ACCOUNTABLE`** — never
   blocking capture, save, or reload (defect D5). An implementation that
   refuses to persist a messy draft is a defect, not strictness. "Human
   workflow truth comes first" means capture is always permitted.
2. **The per-rule blocking table in the Codex directive is authoritative**
   (14 blocking, 2 non-blocking). Codex does not choose severities.
3. Rule IDs are **persisted forever** on findings and risk acceptances.
   `HW-001`…`HW-016` map 1:1 to master handoff §7's numbered list in order,
   and are never renumbered. Adding a rule takes the next free ID.
4. Findings that render user text must escape markup on output, following the
   existing `rich.markup.escape` precedent in `src/cli.py`.

## ADR-004 — Graph representation → APPROVED

No changes. Keeping two deliberately separate graph notions — the frozen,
signed, linear kernel `GraphSpec` versus the branching `WorkflowStep`
references — is correct, and doing reachability with a ~20-line BFS instead of
a graph dependency passes the project's own framework-adoption test
(`docs/dependencies.md`).

Emphasis: dangling references are **structural** (Pydantic validator);
reachability and dead-ends are **semantic** (rules HW-005/006/007). Do not
merge these two layers — one produces a load failure, the other a finding with
a location and remediation.

## ADR-005 — Promotion state machine → APPROVED WITH REVISIONS

New state machine borrowing the `maturity.py` idiom is correct; not extending
package maturity is correct (different axes). Amendments:

1. **`AccountableWorkflow` is constrained** (defect D3): it **reuses
   `WorkflowStep`**, introduces **no** `states`/`transitions` vocabulary, and
   flattening to `WorkflowBrief` happens **only** in
   `src/foundry/workflow_export.py`. Record in the ADR why the cheaper
   "envelope around WorkflowBrief" option was rejected — premature flattening
   destroys the per-step attributes (decision authority, reversibility, data
   sensitivity) that cooperation assessment consumes next.
2. **Gate enforcement stops at `RUNTIME_READY`** (defect D4). All 8 enum
   values exist; `DEPLOYED` and `VALIDATED` are recorded states whose entry
   criteria delegate to existing run/eval evidence plus a human `reviewed_by`.
   No new deployment machinery — building it would breach §4.
3. Actor attribution on acceptances and promotions is **self-attested, not
   authenticated** (defect D6). Ship it; document the ceiling; backlog the
   Ed25519-signed-acceptance upgrade that `src/security/signing.py` already
   makes cheap.

## ADR-006 — Cooperation policy engine → APPROVED WITH REVISIONS

Scoping "engine" to a deterministic decision table rather than a framework is
correct and directly serves §4. Amendments:

1. **Safety floors are one-directional and this must be enforced in code, not
   convention:** an override may always move a step toward human control;
   it may never move a floored step toward greater autonomy. This is the
   safety-critical line of the release — it needs its own test.
2. The decision table must be **published in
   `docs/cooperation-classification-guide.md` in full**, including the exact
   attribute thresholds. "Explainable" means a human can predict the output
   before running it; a table hidden in code does not satisfy question 8.
3. `NOT_READY_FOR_AUTOMATION` **blocks agent export of that step** (it stays
   human) rather than exporting a disabled agent.
   `BOUNDED_AUTONOMOUS_AGENT` exports **only** with an explicit approval gate.
4. The export mapping must not widen permissions beyond what the executor
   class authorizes; assert it in tests.

## ADR-007 — Desktop / service boundary → APPROVED WITH REVISIONS

The thin-client goal is right; the ADR named the wrong thing as "the
services," producing a phase-ordering bug. Amendments (defect D7):

1. **The authoritative service layer is the domain modules** —
   `src/governance/workflow_rules.py`, `workflow_promotion.py`,
   `cooperation.py`, `src/foundry/workflow_export.py`. Both the CLI and the
   GUI call *those*.
2. **`src/gui/services.py` is a GUI-facing adapter containing no decisions.**
   It may shape data for display and turn refusals into renderable results;
   it may not evaluate a rule, decide a promotion, or classify an executor.
   This matches the repo today (`src/cli.py` and `src/gui/services.py` both
   import domain modules directly — verified).
3. **The CLI must never import from `src/gui/`.** Add a test asserting this,
   and asserting no rule/promotion/classification logic lives under
   `src/gui/`. That test is the mechanical enforcement of §16's "must not
   implement a second validator."
4. Long operations run on worker threads started by views; domain modules and
   the adapter stay synchronous and thread-agnostic. No async framework.

---

## Gate A status

| Gate A criterion | Status |
|---|---|
| Fable audit complete within budget | ✅ complete; no bulk code written |
| Opus review complete | ⚠️ **performed by `claude-fable-5`, not Opus** — operator must accept the substitution or re-run |
| Canonical schema strategy selected | ✅ Pydantic canonical, JSON Schema generated (ADR-001) |
| ADRs accepted | ✅ all 7 approved, 5 with binding revisions |
| No unresolved architecture blocker | ⚠️ **one remains: D1** — the DoD's cross-language clause needs an operator amendment |

**Gate A is not closed.** Two items need the operator, not an architect:
accept or reject the reviewer substitution, and ratify the D1 DoD amendment.
Implementation of phase 1 (contracts) may begin at the operator's discretion
without waiting, because no phase-1 file depends on either decision — but
Gate B cannot be evaluated until D1 is ratified, since D1 rewrites Gate B's
wording.
