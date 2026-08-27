# Migration Notes

What changes to stored data mean for existing installations, and the rules that
keep an upgrade from destroying history.

## The two rules

1. **Ledger DDL is additive only.** New tables and new columns are permitted.
   Dropping a table, dropping a column, or rewriting rows is not. The ledger is
   an audit trail, and an audit trail you can edit is a diary.
2. **Contracts evolve additively within a major version.** New fields must have
   defaults, so data written by an older build still loads. Removals, renames,
   and semantic changes bump `schema_version`.

## Upgrading an existing database

**No manual migration is required.** `RunLedger._ensure_schema()` creates any
table that does not yet exist on open, and leaves existing ones alone. An older
`fukasawa.db` opened by a newer build gains the new tables empty and keeps every
row it already had.

Tables added for the human & cooperative workflow lifecycle:

| Table | Holds | Mutability |
|---|---|---|
| `workflow_drafts` | observed workflow drafts, keyed by workflow and version | **editable** |
| `validation_reports` | the report a decision was made on | append-only |
| `risk_acceptances` | consciously accepted findings, with actor and rationale | append-only |
| `workflow_promotions` | every transition attempt, granted or refused | append-only |
| `accountable_workflows` | promoted artifacts, keyed by workflow, version **and maturity** | append-only |
| `cooperation_assessments` | per-step executor recommendations and human overrides | append-only |
| `cooperative_workflows` | built and approved executor assignments | append-only |

`cooperation_assessments` and `cooperative_workflows` use a **surrogate
`record_id`** rather than a natural key, and this is deliberate. `apply_override`
returns a copy carrying the *same* `assessment_id`, so an override is a later row
on top of the original rather than an edit of it; approving a cooperative
workflow likewise lands as a second row beside the unapproved build. Reads
collapse to the newest row per step (`load_cooperation_assessments`) or per
workflow (`load_cooperative_workflow`), while
`cooperation_assessment_history()` returns every row.

Keying either table naturally would have forced a choice between refusing the
override and overwriting the recommendation it replaced. Both are wrong: the
value of an override is that you can still see what it overruled.

`accountable_workflows` is keyed by maturity as well as version because a
workflow climbs several steps at the same draft version, and each step is its
own artifact that must stay readable. An earlier build of this branch keyed it
on version alone, which made the second promotion look like a duplicate of the
first; that build was never released, so no migration is required.

`workflow_drafts` is deliberately mutable: a draft is a working document people
edit as they learn more. Everything *derived* from a draft is immutable, because
those rows are the evidence a decision was made on.

Append-only tables are enforced by SQLite triggers, not by convention. Code
holding a direct database handle still cannot update or delete them.

## Contracts that gained fields

`EvalResult` gained optional fields for externally executed evaluations
(`execution_status`, `executed_by`, `executor_version`, `external_run_ref`,
`score`, `artifact_paths`, `non_conformance_candidates`,
`requires_human_review`). **No database change was needed**: `eval_results`
stores a `result_json` blob alongside its indexed columns, so the new fields
serialize into the blob and older rows load with defaults.

New contracts — `HumanWorkflowDraft`, `WorkflowStep`, `AccountableWorkflow`,
`WorkflowFinding`, `ValidationReport`, `RiskAcceptance`, `CooperationAssessment`,
`CooperativeWorkflow` — all carry `schema_version`, currently `"1"`.

## Unknown fields are rejected

The new workflow contracts set `extra="forbid"`. These are hand-written YAML
files, and a mistyped field name that is silently ignored is exactly the
invisible drift the runtime exists to catch. If you get "extra inputs are not
permitted", check the spelling against `schema-reference.md`.

The consequence for forward compatibility is deliberate: a build cannot load a
file written against a *newer* major version. That is why versions are bumped
rather than fields quietly added across a major boundary.

## The unversioned legacy contracts

`WorkflowBrief`, `ProcessCapsule`, and `GraphSpec` carry **no** `schema_version`
field. This is known debt, and it is not being retrofitted, because of the
constraint below.

## The constraint that governs any future change to signed contracts

Graph and bundle signatures are computed over `model_dump(mode="json")`, which
**includes defaulted fields**. Adding *any* field to `GraphSpec` or
`BundleManifest` — even optional, even with a default — changes the canonical
bytes. That would:

* invalidate every `.sig` sidecar already in the field,
* break hash-pinned resume of in-flight graph runs, and
* break verification of every `.fkz` bundle already distributed.

**These schemas are frozen.** `tests/test_workflow_contracts.py` pins the
fingerprints of the shipped example graphs, with a companion test proving the
pin moves when any field changes.

**If that golden test fails, do not update the expected hashes to make it
pass.** It means a frozen schema changed and signatures in the field have
already broken. Stop and escalate.

Before either schema can ever change, the signing payload itself must be
versioned — the likely shape is signing `payload | {"canon": "2"}` with a
verify-side fallback — which needs its own decision record at that time.

## Rolling back

Downgrading a build leaves the new tables in place and unused; nothing in older
code reads them, and nothing breaks. Rows written by the newer build remain, so
rolling forward again finds its history intact.
