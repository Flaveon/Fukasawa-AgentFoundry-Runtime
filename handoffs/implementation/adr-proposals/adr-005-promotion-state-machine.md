# ADR-005 — Promotion state machine (workflow maturity)

**Status:** Proposed (Gate A)

## Context

Master handoff §8 defines an 8-state workflow maturity ladder:
`OBSERVED → MAPPED → ACCOUNTABLE → COOPERATION_READY →
COOPERATIVE_DESIGN_APPROVED → RUNTIME_READY → DEPLOYED → VALIDATED`, with
hard invariants (no skipping OBSERVED→RUNTIME_READY; blocking findings gate
promotion; risk acceptance needs actor/timestamp/rationale; promotion
produces a traceable artifact; prior artifacts stay auditable).

The repo already contains TWO promotion-shaped mechanisms on DIFFERENT axes:
- **Agent-package maturity** (`draft → tested → validated`):
  `src/governance/maturity.py` — evidence-gated `assess()`/`promote()`,
  `PromotionRefusedError`, human `reviewed_by` required, audit via
  `RunLedger.record_promotion`.
- **Workflow-run states**: `src/runtime/state_machine.py` — brief-declared
  transitions, refusal recorded as non-conformance, append-only ledger.

## Decision

1. **New state machine, borrowed idiom:** `WorkflowMaturity` enum lives in
   `src/schemas/human_workflow.py`; the transition table + gates live in
   `src/governance/workflow_promotion.py`, copying the `maturity.py` shape
   (assess → report of criteria met/unmet; promote → refuses with
   `PromotionRefusedError`-style exception unless evidence allows; every
   promotion recorded to the ledger with actor + timestamp).
2. **It does not extend `maturity.py`** — package maturity and workflow
   maturity are different axes (a VALIDATED workflow may contain draft
   agent packages); conflating them would corrupt both evidence models.
3. **Promotion emits an artifact, never mutates in place:** promoting to
   `ACCOUNTABLE` writes a new `AccountableWorkflow` row referencing the
   source draft ID + rule/schema versions evaluated; the draft row is
   untouched (append-only doctrine, master handoff §8 "previous artifacts
   remain available").
4. **Gates:** promotion N→N+1 requires zero unaccepted blocking findings
   from the rule registry at the CURRENT rule versions; acceptances are
   first-class `RiskAcceptance` rows (actor, timestamp, rationale, finding
   + rule version). `DEPLOYED` and `VALIDATED` additionally require a human
   `reviewed_by` (mirroring `maturity.promote`).
5. **Transitions are total and explicit:** any request not in the table
   raises; there is no default-allow path (mirrors `advance()`'s
   no-valid-path refusal).

## Alternatives considered

- *Reuse the workflow-brief state machine to govern maturity*: briefs
  declare *runtime* states per workflow; maturity states are fixed product
  semantics — putting them in a brief would let YAML edit the governance
  ladder. Rejected.
- *A generic FSM library*: the existing hand-rolled idiom is proven and
  legible (product principle 7). Rejected.

## Consequences

- Three state machines coexist (run states, package maturity, workflow
  maturity), each small, each documented — accepted trade-off for axis
  purity; `docs/promotion-state-reference.md` maps all three side by side.
