# ADR-001 — Canonical schema ownership

**Status:** Proposed (Gate A — needs Opus/operator approval)

## Context

Contracts currently live in three shapes: Pydantic v2 models in
`src/schemas/` (validated everywhere the runtime loads data), July-18
markdown drafts in `specs/` (superseded where they conflict, per the
operator ruling recorded in `HANDOFF.md`), and aspirational object lists in
`docs/architecture.md`. The master handoff (§9.2) demands one canonical
schema source with any secondary representation generated or verified, never
hand-written twice. The repository is Python-only today (verified: no `.ts`,
no `package.json`), but a TypeScript consumer is plausible later.

## Decision

1. **The Pydantic v2 models in `src/schemas/` are the single canonical
   contract source.** New §5 domain objects follow the same house style
   (typed fields, `description=` on every field, model validators for
   doctrine rules).
2. **JSON Schema is the generated interchange representation.** A helper
   (`src/schemas/export_jsonschema.py`, phase 1) emits
   `model_json_schema()` output for every public contract; phase 6 exposes
   it as `fukasawa schema dump`. Any future TypeScript consumer generates
   types from these artifacts and verifies them with fixture tests — no
   hand-written parallel definitions, ever.
3. **`specs/*.md` are historical inputs.** They are not updated to track
   the models; `docs/schema-reference.md` (generated from the models'
   field descriptions where practical) becomes the human-readable reference.

## Alternatives considered

- *JSON Schema as canonical, Pydantic generated*: inverts the direction the
  codebase already validates in; loses model validators (e.g. the
  CONSCIOUS-owner doctrine rule in `workflow_brief.py`) which cannot be
  expressed in JSON Schema. Rejected.
- *Dual hand-maintained Python+TS*: explicitly forbidden by master handoff §9.2.

## Consequences

- Cross-language drift (risk R2) is reduced to "regenerate from JSON Schema".
- Doctrine rules that live in Python validators are NOT visible in the JSON
  Schema export; the schema-reference doc must list them explicitly.
