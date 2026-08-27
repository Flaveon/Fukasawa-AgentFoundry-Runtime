# Phases 1–7 reviewed against `handoffs/handoff-master.md`

**Date:** 2026-08-21
**Reviewer:** `claude-opus-5`, operator-directed.
**Branch:** `claude/handoff-master-verification-37e5d2`, from
`claude/phase-7-desktop` @ `6b33657`.
**Baseline at start:** 559 passed (xvfb) / 544 passed + 15 skipped (no display).

## Why this review exists

`handoffs/handoff-master.md` was **untracked** in the main checkout until
2026-08-20. Every phase before this one was therefore built against derived
documents — `architecture-audit.md`, `file-change-map.md`, the ADRs, the Codex
directive — each a lossy summary of it. Phase 7 discovered the cost when it
finally read §16 directly: its reconstruction of that section scored **8 of 15**
and had guessed two items outright wrong.

That raised the obvious question about everything earlier. §5 (domain objects),
§7 (the sixteen validator rules), §8 (the promotion state machine), §15 (test
strategy) and §19 (release gates A–E) governed phases 1 through 6 and none had
been read against what was built.

**The short answer: they hold.** §5, §7 and §8 are faithful, in two cases more
faithful than the derived documents were. The gaps are in §15 and §19, they are
about *evidence* rather than *behaviour*, and one of them was hiding a defect
that ships.

---

## §5 — Target domain objects: **compliant**

All six objects exist, in `src/schemas/human_workflow.py`,
`src/schemas/findings.py` and `src/schemas/cooperation.py`. Every minimum
concept the section names is present as a described field.

| §5 | Object | Concepts required | Present | Notes |
|---|---|---|---|---|
| 5.1 | `HumanWorkflowDraft` | 16 | 16 | "status" is `maturity`; "transitions" are `WorkflowStep.next_steps` |
| 5.2 | `WorkflowStep` | 12 | 12 | "evidence requirements" live on `StepOutput.evidence_requirement` |
| 5.3 | `WorkflowFinding` | 10 | 10 | |
| 5.4 | `AccountableWorkflow` | 8 | 8 | "states" are the steps; "handoffs" are the step graph |
| 5.5 | `CooperationAssessment` | 11 | 11 | |
| 5.6 | `CooperativeWorkflow` | 12 | 12 | |

**Two representational deviations, both deliberate and both documented** in the
module docstring and architecture review D3:

1. `AccountableWorkflow` introduces no `states`/`transitions` vocabulary. Each
   step *is* a state the work can be in; flattening into named states happens
   at export. Flattening earlier would destroy the per-step attributes —
   decision authority, reversibility, data sensitivity — that cooperation
   assessment reads next.
2. `AccountableWorkflow` reuses `WorkflowStep` rather than re-modelling the
   work. Promotion resolves accountability; it does not reshape structure.

§5's own preamble sanctions this: *"Final names may adapt to repository
conventions, but semantics must remain stable."* They do.

Worth recording as a strength rather than a finding: every contract sets
`extra="forbid"`. These are hand-written YAML files, and a mistyped field name
that is silently ignored is precisely the invisible drift this product exists
to catch.

## §7 — Initial validator rule set: **compliant**

All sixteen rules are implemented in `src/governance/workflow_rules.py`, and
`HW-001`…`HW-016` map **1:1 and in order** to §7's numbered list. Each carries
the nine required attributes: stable id, description, severity, blocking
policy, detection logic, affected location, remediation, unit tests, fixture
coverage.

Blocking policy matches the directive's authoritative table exactly. HW-013 and
HW-014 are the non-blocking heuristic pair, correctly so — they carry real
false-positive risk.

Every rule has a dedicated test class with positive and negative fixtures
(`TestHW001…` through `TestHW016…`), satisfying DoD §2.2.

Two observations, neither a defect:

* §7's "do not hide multiple unrelated defects inside one generic finding" is
  honoured — finding ids are derived from rule plus location, so one rule firing
  in three places produces three findings.
* HW-002 and HW-007 each cover two conditions, but so do §7's own items 2 and 7.
  The rules match the specification rather than exceeding it.

## §8 — Promotion state machine: **compliant**

`src/governance/workflow_promotion.py`. All eight maturity states exist in
`WorkflowMaturity` from the first release, so adding gates later is not a
breaking schema change.

| §8 requirement | Status | Where |
|---|---|---|
| No direct `OBSERVED` → `RUNTIME_READY` | met | `is_valid_transition` admits exactly one step forward |
| Transitions explicit, persisted, tested | met | `PROMOTION_PATH`, ledger tables, `tests/test_workflow_promotion.py` |
| Blocking findings prevent promotion | met | `unresolved_blocking` gates `promote` |
| Non-blocking accepted only with actor, timestamp, rationale | met | `RiskAcceptance`, all three mandatory |
| Promotion produces a traceable artifact, not a silent mutation | met | `AccountableWorkflow` + `PromotionLineage`; source draft untouched |
| Previous artifacts remain available | met | append-only ledger |
| Schema and rule versions persisted | met | `PromotionLineage.rule_set_version` / `.schema_version` |

The release enforces gates through `RUNTIME_READY` and delegates `DEPLOYED` and
`VALIDATED` to existing run-ledger and evaluation evidence — architecture review
D4, and consistent with §4's non-goal of new deployment machinery.

One thing the implementation does that §8 does not require and should have:
**refusals are recorded too.** A declined promotion and its reason are part of
the history. Keeping only successes would make the record an advertisement
rather than an audit.

## §15 — Test strategy: **compliant with two gaps**

| §15 | Area | Status |
|---|---|---|
| 15.1 | Baseline gate | met — `artifacts/test-baseline.txt` committed; no Node version to record (D1) |
| 15.2 | Contract tests | met, **except generated TS type compatibility** — see D1 below |
| 15.3 | Validator tests | met — per rule: id, location, severity, policy, remediation, no duplicate, no false positive |
| 15.4 | State tests | met, **except old-version load behaviour** — gap 1 |
| 15.5 | Cooperation tests | met — all nine named cases, plus the floored-override test the directive added |
| 15.6 | Integration tests | met — `TestParity` proves CLI and desktop reach the same answers through the same functions |
| 15.7 | Packaging tests | **was absent** — gap 2, and it was hiding a live defect |

### D1 — the TypeScript obligation, and why it is not a gap

§3 states the runtime is "Mixed Python and TypeScript". **It is not.** There are
zero `.ts` files, no `package.json`, no `tsconfig.json` — verified again today.
§2.2's cross-language fixtures, §9.2's TS responsibilities, §15.2's generated TS
types and Gate B's "Python/TS agreement verified" all rest on a false premise
about this repository.

This was found at Gate A, recorded as defect D1 in `opus-architecture-review.md`,
and resolved: §9.2 is self-resolving because it says *"Use TypeScript where the
current project already uses it"* — and it does not. ADR-001 made the Pydantic
models canonical and `src/schemas/export_jsonschema.py` the single generation
seam for any future TS consumer.

**This is a documented deviation from the master handoff, not drift.** It is
called out here because a reader comparing the handoff to the repository will
hit it, and should find the ruling rather than re-derive it. It is the one place
where the master handoff is factually wrong about its own subject.

### Gap 1 — old-version load behaviour is untested

§15.4 requires a test for loading data written by a previous schema version.
`docs/migration-notes.md` exists and `schema_version` is persisted on every
contract, but nothing exercises the read path against a v0/older payload. Low
risk today — there is only one schema version — and it becomes the thing that
matters the moment there are two. **Phase 9, before the version bumps.**

### Gap 2 — packaging tests, and the defect they were not there to catch

§15.7 asks for seven packaging checks, starting with "module import from clean
environment". None existed. Building a wheel and looking inside it found this:

> **`src/gui/services/` was entirely absent from the built distribution.**

`pyproject.toml` listed its packages by hand. Phase 7 split
`src/gui/services.py` into a package. The list was never updated. A
`pip install .` therefore produced a working CLI and a GUI that cannot import
its own service layer.

It was invisible to everything that looks: 559 tests passed, because they run
from the source tree where the directory is simply there; CI stayed green,
because it builds through a PyInstaller spec rather than through setuptools.

**Fixed in this branch.** `pyproject.toml` now discovers packages
(`[tool.setuptools.packages.find] include = ["src*"]`), and
`tests/test_packaging.py` holds the property — one cheap guard aimed at the
hand-written-list style, and one that builds a real wheel and reads its
manifest.

Both guards were verified by mutation: reverting `pyproject.toml` and confirming
each fails, then restoring and confirming each passes. The wheel test needed two
corrections found that way — it passed against the broken config twice before it
was right, once because pip served a cached wheel and once because a gitignored
`*.egg-info/SOURCES.txt` left by an earlier in-place build was supplying the
missing package to setuptools. Both are recorded in the test.

The remaining §15.7 items — desktop startup from a bundle, writable data
directory, PyInstaller hidden imports — stay with phase 9, which owns packaging.

## §19 — Release gates: A–E met, F now met, G open

| Gate | Status | Evidence / what remains |
|---|---|---|
| **A** — Architecture approved | **met** | Audit within budget, review complete, ADR-001 selects the canonical schema, ADRs accepted. Provenance note: the "Opus" review was performed by `claude-fable-5` and says so. |
| **B** — Contracts stable | **met** | Schemas versioned; golden JSON Schema tests; migrations documented; contract tests green. Python/TS agreement is void per D1. |
| **C** — Validator complete | **met, one item open** | 16 rules, all tests green, reports actionable. **The false-positive review is not formally closed** — HW-013 and HW-014 are the heuristics that carry the risk, they are non-blocking by design, and `TestSparseCapture` covers the honest-incomplete-draft case. Phase 8 owes the written review. |
| **D** — Accountable promotion complete | **met** | State machine enforced, audit trail persisted, blocking and accepted-risk behaviour tested. |
| **E** — Cooperation builder complete | **met** | Every step classified, human authority and fallback preserved, approved workflow generated, export works end to end. |
| **F** — Interfaces complete | **met as of this branch** | CLI lifecycle works (all §17 commands). CustomTkinter lifecycle now covers §16 items 1–15. Parity asserted by `TestParity`. |
| **G** — Release verified | **open** | Suite green with no regression. **Remaining: Jules verification, Opus critical-diff review, five §18 documents, the pilot README, packaging verification.** Phases 8 and 9. |

## §10 and §18 — what is missing, and whose phase owns it

Neither is drift; both are scheduled work not yet due.

**§10 pilot** — seven of the eight required artifacts exist under
`examples/workflows/substack-publication/`. `README.md` is missing; the
directive assigns it to phase 8. (There is an extra `repaired-workflow.yaml`,
which is the fixture the tests run against and a useful teaching artifact — the
same workflow after its blocking findings were resolved.)

**§18 documentation** — eight of thirteen deliverables exist. Missing:
`lifecycle-overview.md`, `pilot-walkthrough.md`, `release-notes.md`, the two
contributor guides (adding a validator rule; adding executor classification
policy), and `packaging-guide.md`. Phases 8 and 9.

---

## Findings, in priority order

1. **`src/gui/services/` was missing from the built wheel.** Live, shipping,
   invisible to the suite and to CI. **Fixed here**, with two mutation-verified
   guards.
2. **`src/runtime/state_machine.py`'s refusal path had lost its local
   guarantee.** See `jules-state-machine-refactor-verdict.md`. **Fixed here.**
3. **The GUI import-law guard listed its subjects by hand.** Adding a view file
   silently escaped the R3 guard. Now discovered by glob — three new view
   modules landed in this branch and are covered automatically.
4. **Old-version load behaviour is untested** (§15.4). Phase 9.
5. **The Gate C false-positive review is not written down.** Phase 8.
6. **The master handoff's §3 is factually wrong about this repository** (no
   TypeScript). Resolved at Gate A as D1; noted so it is not re-litigated.

## What did not need fixing

The three sections most likely to have drifted — §5, §7, §8 — had not. Phases 1
through 4 were built from derived documents and still landed on the
specification, in two places with reasoning better than the derived documents
carried. §16 was the outlier, not the pattern.

The lesson worth keeping is narrower than "derived documents are dangerous":
**§16 was a numbered list of fifteen items, and numbered lists are exactly what
a prose summary loses.** §5, §7 and §8 are also lists, but each item carries
enough semantic weight to survive summarising. "Guided step editor" does not.
