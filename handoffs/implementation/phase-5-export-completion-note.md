# Agent Completion Note — Phase 5: Cooperative Builder and Export

**Phase:** 5 of 9 — targets Gate E (second half).
**Branch:** `claude/phase-5-executor-export-e61158`, based on
`claude/phase-5-executor-export-f831c2` (which carries phases 1–4 plus
ADR-009/010).
**Implemented by:** `claude-opus-5` in the Codex implementation role.

## Scope completed

- **`src/foundry/workflow_export.py`** — the phase's one new source file.
  `build_cooperative_workflow` (assessments → `StepAssignment`s),
  `export_workflow` (`CooperativeWorkflow` → `WorkflowBrief`), the four
  published policy tables, three refusals, and `steps_kept_human`.
- **Export mapping section added to `docs/cooperation-classification-guide.md`**,
  as ADR-006 decision 5 directs.
- **`examples/workflows/substack-publication/cooperative-workflow.yaml`** and
  **`workflow-design-brief.yaml`** — the pilot's stage-5 artifacts.
- **`tests/test_workflow_export.py`** — 41 tests.

Also completed this session, out of phase but named as the entry condition:
**`docs/source-to-contract-map.md`**, the Phase 0 deliverable left unchecked in
`tasks/backlog.md`. See its own commit.

## Files changed

Created: `src/foundry/workflow_export.py`, `tests/test_workflow_export.py`,
`examples/workflows/substack-publication/cooperative-workflow.yaml`,
`examples/workflows/substack-publication/workflow-design-brief.yaml`, this
note. Modified: `docs/cooperation-classification-guide.md` (new section only).

**No FROZEN file was touched.** Verified against directive §3 by path filter,
not by inspection.

## Tests run and results

```
.venv/bin/python -m pytest -q
418 passed, 4 skipped      # 377 before + 41 new; 0 regressions
```

Baseline reproduced before any change: 377 passed, 4 skipped.

Each of the three safety properties was mutation-checked — the property was
deliberately broken and the suite re-run — to confirm the test named for it
actually fails:

| Mutation | Caught by |
|---|---|
| `effective_executor` → `recommended_executor` | `TestExportRespectsEffectiveExecutor` (3 tests) |
| gate refusal removed | `TestBoundedAutonomousAgentRequiresGate` |
| `NOT_READY_FOR_AUTOMATION` added to `_AGENT_OWNED` | `TestNotReadyNeverExportsToAnAgent` |
| transition dedupe removed | `TestExportStructure` (2 tests) |

A test that has never been observed failing is not evidence.

## The pilot's export

| Step | Effective executor | Depth | Agent |
|---|---|---|---|
| capture-idea | HUMAN_LED_AI_ASSISTED | GUIDED | — |
| scope-check | HUMAN_ONLY | CONSCIOUS | — |
| deep-research | HUMAN_LED_AI_ASSISTED | GUIDED | — |
| draft-article | HUMAN_ONLY | CONSCIOUS | — |
| **request-artwork** | **HUMAN_LED_AI_ASSISTED** *(overridden)* | GUIDED | — |
| review-and-approve | HUMAN_ONLY | CONSCIOUS | — |
| **publish-post** | **AGENT_PREPARED_HUMAN_APPROVED** | GUIDED → CONSCIOUS | publish-post-agent (L2) |
| archive-notes | DETERMINISTIC_AUTOMATION | ROUTINE | archive-notes-agent (L0) |

10 states, 13 transitions, 2 agent packages. Six of eight steps stayed with a
person, which is the correct outcome for this workflow rather than a shortfall.

`request-artwork` is the one to look at: the decision table recommended
`AGENT_EXECUTED_HUMAN_SUPERVISED`, the operator overrode it, and **no
`request-artwork-agent` exists in the export**. That is the phase-4 note's
warning discharged.

## Decisions made

1. **Gated classes export as two transitions with a state between them.**
   The runtime opens its review gate on CONSCIOUS-depth transitions, and
   `WorkflowBrief._check_agents_are_consistent` raises on a CONSCIOUS
   transition owned by an agent — so "a gated agent-owned step" is
   unrepresentable as one transition. Splitting it into the agent's work, a
   `<step>-pending-approval` state, and the human's decision keeps the frozen
   state machine and brief schema untouched, and makes the approval a durable
   ledger event rather than a field asserting one.

2. **"ROUTINE or GUIDED" resolved by definition, not preference.** GUIDED is
   "a human confirms the output", which is exactly `EVERY_OUTPUT_REVIEWED`, so
   `AGENT_EXECUTED_HUMAN_SUPERVISED` is GUIDED. `DETERMINISTIC_AUTOMATION` is
   ROUTINE because that is what the class means.

3. **`AgentSpec.depth_level` derived from the executor class** (0 / 2 / 2 / 3),
   never 4 or 5. ADR-006 names `escalation_target`, `forbidden` and `fallback`
   but not `depth_level`, which `AgentSpec` requires. Deriving it keeps the
   value deterministic and testable rather than hand-entered per workflow.
   Level 4 coordinates a whole workflow, which is this runtime's job; Level 5
   is redesign-only and the generator refuses it.

4. **`HUMAN_LED_AI_ASSISTED` declares no agent** — contrary to a first reading
   of the mapping. That class means the human owns the transition, and
   `_build_capsule` (frozen) refuses an agent that owns no transitions. The
   assistance is recorded in `allowed_tools`, which is what it is.

5. **One transition per state pair.** The runtime resolves a move by the first
   match, so a second transition on the same pair is unreachable and its owner
   and evidence requirement are silently dead. A declared recovery path landing
   on a state the step already reaches keeps the declared edge.

6. **Declared exception paths become transitions.** A rehearsed recovery that
   the runtime treats as a non-conformance is worse than no recovery at all.
   The pilot's gate rejection loop (`review-and-approve → draft-article`) works
   because of this.

7. **`human_owner` is the step's declared actor, not a workflow default.** The
   accountable workflow already says who is accountable for each step (HW-003
   makes it blocking); substituting a guess would overwrite a statement with an
   inference.

8. **`required_tools` and `runtime_requirements` are carried, never inferred** —
   inherited from phase 4 decision 7 for the same reason.

## Assumptions

- Exception-path transitions are GUIDED and carry no evidence requirement of
  their own, on the reasoning that the exception is often *that* the evidence
  could not be produced. Where a recovery collides with a declared path the
  declared edge wins, so the recovery inherits its evidence requirement — the
  conservative direction, but a real narrowing (see limitations).
- The terminal state is named `complete`, uniquified if a step already owns
  that name. `AccountableWorkflow` has no notion of a terminal state and the
  runtime needs one, or the last step reads as a dead end.

## Known limitations

- **A recovery landing on a declared path inherits that path's evidence
  requirement.** A brief has exactly one edge per state pair, so this is the
  only shape expressible without changing `state_machine.py` (FROZEN). It asks
  for more evidence, never less, and `_handle_missing_evidence` leaves the run
  retryable — but an operator taking a recovery must still state evidence for a
  step that by hypothesis did not produce it. Worth revisiting if a real
  workflow hits it.
- **No CLI surface** until phase 6. `fukasawa export` is phase 6's to add;
  `src/cli.py` is phase 6's file.
- **Cooperative workflows are not persisted.** Same gap phase 4 recorded for
  assessments: the file map gives phase 5 no ledger table, and `ledger.py`
  belongs to phase 3. The artifacts are written to YAML instead.
- **`approved_at` is not set** by the builder even when `approved_by` is. The
  timestamp belongs to the act of approving, which happens in a UI or CLI that
  does not exist yet; setting it here would date the build, not the decision.
- **Agent names are derived** as `<step_id>-agent`. If a workflow declares a
  human actor literally named `x-agent` for a step whose id is `x`, the brief
  validator will refuse the export with a confusing message. Not seen in
  practice; not defended against.

## New risks or defects

- Nothing new for the register.
- **For phase 6:** the CLI's export command must surface `steps_kept_human`.
  An operator who exports a workflow and sees only "2 packages generated"
  learns nothing about the six steps that stayed with them, and that silence is
  the failure mode this product exists to prevent.
- **For phase 7:** the desktop must not re-derive the export mapping. It is a
  classification decision, and directive §6.3 forbids classification logic under
  `src/gui/`.

## A naming collision this phase had to work around

The pilot artifact the directive names `workflow-design-brief.yaml` is a
runtime `WorkflowBrief` — states, transitions, owners, evidence. It is **not**
the *Workflow Design Brief* of `FukasawaGPT/Workflow_Design_Brief.md`, which is
a complexity-and-depth design specification containing no states at all. Two
different artifacts, one name.

The artifact header says so explicitly and points at
`docs/source-to-contract-map.md` §3, which dates the divergence. Naming the
file anything else would have deviated from the directive; naming it this and
saying nothing would have entrenched the collision.

## Recommended next action

Phase 6 (CLI): `src/cli.py`, all §17 commands, `--json`, stable exit codes, no
stack traces on user error. The export surface it needs is
`build_cooperative_workflow`, `export_workflow`, `steps_kept_human`, and
`ExportRefusedError` — whose messages are already written to be read by an
operator rather than a developer.

## Exact starting point for next agent

Branch `claude/phase-5-executor-export-e61158` @ head.
Read: `docs/cooperation-classification-guide.md` §"Export mapping" → this note
→ directive §17 (CLI commands).
Import surface: `build_cooperative_workflow`, `export_workflow`,
`steps_kept_human`, `ExportRefusedError`; plus phase 4's `assess_workflow`,
`apply_override`, and phase 3's `promote(..., assessments=...)`.
Current suite: **418 passed, 4 skipped**. Do not touch any file listed FROZEN
in directive §3.
