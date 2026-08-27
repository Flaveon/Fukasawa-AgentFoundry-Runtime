# ADR-004 — Graph representation for workflow steps

**Status:** Proposed (Gate A)

## Context

Two graph-shaped things must not be confused:

1. **The kernel's `GraphSpec`** (`src/schemas/graph.py`) — a *linear*
   execution chain (`next` pointers, first node is entry, `None` ends) with
   shape validation (`_check_graph_shape`: unique IDs, resolvable `next`,
   no self-loops) and a brief-fit walk (`validate_against_brief`). It is
   signed, fingerprinted, and FROZEN this release (risk R1).
2. **The new `WorkflowStep` graph** (master handoff §5.2) — observed human
   workflows with branching ("next step or terminal state", decision
   authority, exception paths). Validator rules HW-005 (dangling next),
   HW-006 (unreachable step), HW-007 (dead end) require real reachability
   analysis over it.

## Decision

1. **`WorkflowStep` uses explicit reference lists, not a framework:** each
   step declares `next: list[StepRef]` (empty = terminal) plus
   `exception_paths: list[StepRef]`; references are step IDs validated at
   model level (dangling refs are *structural*, caught by a Pydantic
   validator mirroring `_check_graph_shape`) while reachability/dead-end
   analysis is *semantic*, implemented as rules HW-006/HW-007 in the
   registry via simple BFS from the trigger step.
2. **The kernel `GraphSpec` is untouched.** Accountable workflows export to
   `WorkflowBrief` (states + transitions), which the existing kernel and
   state machine already execute. If a cooperative workflow later needs
   branched *execution*, that is a kernel ADR of its own — not this release.
3. **No visual node-canvas editor** (master handoff §4 non-goal); the
   desktop guided step editor edits the list/reference structure directly.

## Alternatives considered

- *Reuse `GraphSpec` for observed workflows*: forces human-truth capture
  into an execution schema with adapters/retries it doesn't have, and any
  field addition breaks signing (R1). Rejected.
- *Adjacency-matrix or networkx dependency*: BFS over dict-of-lists is ~20
  lines; a graph library adds a dependency for nothing (docs/dependencies.md
  adoption test fails). Rejected.

## Consequences

- Two deliberately different graph schemas, each documented with its
  purpose; the export mapping (steps → states/transitions) is the bridge
  and gets its own tests (`tests/test_workflow_export.py`).
