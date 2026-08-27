# ADR-006 — Cooperation policy engine (scoped to assessment)

**Status:** Proposed (Gate A)

## Context

Before the master handoff arrived, "cooperation policy engine" had NO
referent in this repository. The master handoff gives it one, and a bounded
one: a per-step `CooperationAssessment` (§5.5) recommending an
`ExecutorClass` (§6, seven values), reviewed and overridable by a human,
compiled into an approved `CooperativeWorkflow` (§5.6). Non-goals (§4)
explicitly exclude a generic multi-agent framework, autonomous swarms, and
org-wide role management.

Existing doctrine already encodes the two hardest policy decisions:
- CONSCIOUS-depth transitions cannot be agent-owned
  (`WorkflowBrief._check_agents_are_consistent`) — the ancestor of
  `HUMAN_ONLY`.
- ROUTINE workflows cannot require Level-5 agents (same validator) — the
  ancestor of automation-readiness ceilings.

## Decision

1. **"Engine" = one deterministic function set, not a framework:**
   `src/governance/cooperation.py` exposes
   `assess_step(step) -> CooperationAssessment` scoring the §5.5 factors
   (human-judgment requirement, repeatability, determinism, risk,
   reversibility, data sensitivity) from declared step attributes via a
   published decision table — no LLM in the authoritative path (§9.3).
2. **All seven §6 executor classes exist in the enum from day one** (schema
   stability requirement); the desktop may surface five (§6 note).
3. **Safety floors are hard rules, not scores:** irreversible or
   sensitive-data steps floor at `AGENT_PREPARED_HUMAN_APPROVED` or above
   (toward human); steps with undefined decision authority are
   `NOT_READY_FOR_AUTOMATION`. Floors can make a recommendation *more*
   human, never more autonomous.
4. **Human override is final but audited:** overrides require rationale and
   are stored on the assessment (actor, timestamp). An override toward more
   autonomy on a floored step is refused — the floor is doctrine, mirroring
   the CONSCIOUS-owner validator.
5. **Export mapping to the existing runtime:** `HUMAN_ONLY` →
   CONSCIOUS-depth human-owned transition; `HUMAN_LED_AI_ASSISTED` /
   `AGENT_PREPARED_HUMAN_APPROVED` → GUIDED with human gate;
   `AGENT_EXECUTED_HUMAN_SUPERVISED` / `DETERMINISTIC_AUTOMATION` → ROUTINE
   or GUIDED agent-owned transitions with `AgentSpec` (escalation_target,
   forbidden, fallback recorded); `BOUNDED_AUTONOMOUS_AGENT` exports only
   with an explicit approval gate; `NOT_READY_FOR_AUTOMATION` blocks export
   of that step to an agent (stays human). Table lives in
   `src/foundry/workflow_export.py` and `docs/cooperation-classification-guide.md`.

## Alternatives considered

- *A rules/policy DSL or pluggable policy packs*: no requirement demands
  it; §4 forbids the framework ambition. Rejected — revisit only with ≥2
  real organizations' divergent policies in hand.
- *LLM-recommended classifications as the default path*: §9.3 permits AI
  *suggestions* but they must never alter authoritative state; optional,
  clearly separated, out of release-critical path. Deferred.

## Consequences

- The "engine" is ~one module + one schema module + tests; the word
  "policy" in docs always points at the published decision table, keeping
  the feature auditable by non-developers.
