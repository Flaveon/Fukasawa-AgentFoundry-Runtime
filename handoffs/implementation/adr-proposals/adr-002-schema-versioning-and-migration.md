# ADR-002 — Schema versioning and migration

**Status:** Proposed (Gate A)

## Context

Versioning today is partial: `RuntimeState.schema_version`
(`src/schemas/runtime_state.py:128`) and `BundleManifest.format_version`
(`src/schemas/bundle.py:75`) exist; `WorkflowBrief`, `ProcessCapsule`, and
`GraphSpec` carry no version. No loader yet branches on a version — there
has never been a migration. The master DoD (§2.2) requires persisted data to
be "versioned and migration-aware."

**The sharp edge:** graph and bundle signatures/fingerprints are computed
over `model_dump(mode="json")` (`src/kernel/kernel.py:graph_fingerprint`,
`_require_trusted`; `src/runtime/bundle.py` manifest signing). Because
Pydantic includes defaulted fields in the dump, *adding any field — even
optional with a default — changes the canonical bytes*, which invalidates
every existing `.sig` sidecar, breaks hash-pinned graph-run resume, and
breaks `.fkz` verification. Versioning policy and signing canonicalization
are therefore one decision, not two.

## Decision

1. **Every NEW contract carries `schema_version: str = "1"` from birth**
   (`human_workflow.py`, `findings.py`, `cooperation.py` models).
2. **Additive-only evolution within a major version:** new fields must have
   defaults; removals/renames/semantic changes bump the major version.
3. **Migration happens at load boundaries, nowhere else:** loader functions
   (ledger `load_*`, YAML `load_*`) inspect `schema_version` and apply
   upgrade shims returning current-version models. Persisted rows keep the
   version they were written with (append-only doctrine).
4. **Existing signed contracts are FROZEN this release:** `GraphSpec` and
   `BundleManifest` gain no fields (risk R1). Before they ever change, the
   signing payload must be versioned — recommended future form:
   `sign(payload | {"canon": "2"})` with verify-side fallback, decided in a
   dedicated ADR at that time. A golden-hash contract test
   (`tests/test_workflow_contracts.py`) pins today's fingerprints so an
   accidental change fails CI loudly.
5. **Ledger DDL is additive-only** (`RunLedger._ensure_schema` idiom); new
   tables carry a `schema_version` column.

## Alternatives considered

- *Global runtime-wide version*: one bump would force-touch every artifact
  and re-sign everything; too coupled. Rejected.
- *Retrofit `schema_version` onto WorkflowBrief/GraphSpec now*: breaks R1
  immediately for zero release value. Deferred.

## Consequences

- "Migration-aware" is satisfied by convention + shims, without a migration
  framework dependency.
- The unversioned legacy trio (brief/capsule/graph) is documented debt in
  `docs/migration-notes.md`.
