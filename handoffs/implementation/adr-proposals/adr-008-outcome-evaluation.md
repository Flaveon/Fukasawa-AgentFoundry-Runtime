# ADR-008 — Outcome evaluation: measuring whether workflow optimization works

**Status:** Proposed (post-release; does not affect the current release boundary)
**Raised:** 2026-08-06, operator-directed.
**Implementation design:** `../outcome-evaluation-integration.md` — the
contract pipeline (compile → execute → normalize → govern), merged from the
operator's integration handoff. This ADR holds the *why* and the binding
constraints; that document holds the *how*.

## Context

The runtime evaluates workflow quality through five governance checks
(`src/schemas/eval_case.py`): handoff completeness, observation discipline,
depth compliance, escalation correctness, complexity reduction. Every one of
them measures **process conformance** — did the work move correctly, with
evidence, at the right depth, escalating properly.

None of them measures **outcome**: whether the optimized workflow actually
produced better work than what it replaced.

This is a gap in a capability the project already committed to, not a new idea:

* `docs/evaluation-strategy.md:5` — "The runtime should evaluate workflow
  quality, **not just** model output quality." Both halves are required;
  output evaluation is insufficient alone, not excluded.
* `brief/project-brief.md`, initial use cases — "Compare agent prompt/module
  versions against reviewed examples." Never built.
* `docs/evaluation-strategy.md:98` — "DSPy becomes useful after this
  evaluation layer exists. Its role would be to optimize prompt modules
  against these metrics." The metrics do not exist yet.
* `registry/prompt-module-registry.yaml` — a Phase 6 placeholder for exactly
  this comparison, unused by any code path.

So the outcome half has to be built regardless. The question is build or adopt.

## Decision

**Adopt `smevals` (https://github.com/prime-radiant-inc/smevals, MIT) as an
external peer tool for the outcome half, rather than building an equivalent.**

**The measurement is of our intervention, not of models.** The model is held
**constant as the control variable**; the **workflow configuration is the
variable under test**:

| Arm | Model | Workflow configuration |
|---|---|---|
| baseline | fixed | unoptimized — the process as observed, or a naive prompt |
| treatment | fixed | Fukasawa-optimized — the exported brief and generated agent packages |

Same tasks, same grader, one difference. The delta is evidence about whether
mapping → validating → repairing → cooperating → exporting actually improved
the work. **A smevals grade is never a reason to change a model.** Model
selection is explicitly out of scope for this decision.

The fit is mechanical, not merely thematic: smevals' `Config` binds a `runner`
(*"a reusable CLI program executing the model call"*) alongside the model, so
two Configs sharing a model and differing only in runner isolate the Fukasawa
effect exactly.

## Why adopt rather than build

Against the External Framework Adoption Test in `docs/dependencies.md`:

* **Missing primitive?** Yes — a task/grade harness with immutable run records.
* **Less code locally?** No. This is a real subsystem, and it exists, MIT-licensed.
* **File-based inspectability?** Yes — directories of YAML, `run.yaml`,
  `output.txt`, `grades/`.
* **Makes state easier to see?** Yes. *"Runs are immutable"* and grading
  *"only ever adds files under grades/"* — independently the same append-only
  discipline as our ledger.
* **Lock-in?** Minimal, by the constraint below.
* **Rollback path?** Delete the eval directories. Nothing in the runtime
  depends on them.

## Constraints (binding if this is adopted)

1. **Peer tool, not a dependency.** No import, no vendoring, no entry in
   `pyproject.toml`. The runtime never calls smevals and never fails if it is
   absent. Artifacts are referenced by path.
2. **Evidence, never a gate.** Grades inform humans. If a future ADR ever
   proposes gating promotion on them, it must gate on **deterministic
   checkers only** — smevals supports LLM-judge graders, and DoD §2.2 requires
   that no LLM be load-bearing in an authoritative decision.
3. **Never used to select a model.** Per the decision above.
4. **Vocabulary is disambiguated in docs.** We already use `runs` and
   `eval_results` ledger tables and ship an `evals.yaml` in every agent
   package. smevals uses `Run`, `Eval`, and `runs/` for different things. Two
   meanings of "run" in one operator's head is a documentation failure before
   it is a technical one. Proposed convention: always qualify — "workflow run"
   vs "smevals run", "governance eval" vs "outcome eval".

## Consequences

* `docs/evaluation-strategy.md` should name the two halves explicitly —
  process conformance (built here) and outcome quality (measured by smevals) —
  and state that a claim of "the workflow optimization worked" requires both.
* Product principle 5, "Evidence Promotes Capability," gets a second evidence
  type. Today promotion evidence is entirely process conformance; outcome
  evidence would be a genuine strengthening, and a separate ADR.
* Phase 6 becomes reachable: its precondition was reviewed examples and
  metrics, which this produces.

## Effect on the current release: none

The release proves map → validate → repair → cooperate → export. Outcome
measurement is downstream of all five. Confirmed against the phases in flight:

* **Phase 3 (persistence) — no schema change required.** Evidence references
  in `RuntimeState` are already opaque strings: `CompletedCheck.evidence` and
  `OutputArtifact.path`/`kind`. An outcome grade can be recorded as
  `kind="outcome_grade"` with a path to `grade.yaml` without touching the
  contracts.
* **Phase 5 (export) — one thing to keep in view.** The export *is* the
  intervention, so it is also the treatment arm of any future experiment. It
  should stay deterministic and carry enough provenance
  (`PromotionLineage`: source workflow id, version, rule set version, schema
  version) to name precisely what was under test. It already does.

Nothing here is a reason to alter the release plan.
