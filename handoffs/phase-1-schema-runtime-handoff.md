# Phase 1 Schema Runtime Handoff

## Objective

Implement the first local validation and state runtime.

## Inputs

- `specs/runtime-state-contract.md`
- `specs/workflow-brief-schema.md`
- `specs/process-capsule-schema.md`
- Phase 0 contract map

## Tasks

1. Choose schema implementation: Pydantic or JSON Schema.
2. Create runtime package structure.
3. Implement validators for workflow briefs, process capsules, observation packets, and runtime state.
4. Implement a file-backed run ledger.
5. Add CLI commands:
   - validate brief
   - validate capsule
   - create run
   - show run
   - block run
   - complete run
6. Add focused tests for required fields, invalid state transitions, and missing handoff artifacts.

## Output

- runtime source directory
- schema files
- validation CLI
- test suite
- first run ledger sample

## Review Gate

Human review required before any generated agent package depends on these schemas.
