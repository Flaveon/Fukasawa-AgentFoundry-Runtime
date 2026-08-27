# ADR-009 — Task complexity characterization by model and agent variation

**Status:** Proposed (post-release; extends ADR-008, does not affect the
current release boundary)
**Raised:** 2026-08-07, operator-directed.
**Depends on:** `adr-008-outcome-evaluation.md` and
`../outcome-evaluation-integration.md`. This reuses that harness unchanged and
adds a second axis to it.

**Provenance — this restates founding doctrine, it does not invent it.** The
source input `FukasawaGPT/# FukasawaGPT.md` §"Complexity Budget System"
(dated May 2026, listed in `README.md` under Source Inputs) already takes
**available hardware**, **RAM/VRAM limitations**, and **desired autonomy
level** as *inputs*, and emits **recommended workflow depth**, **automation
recommendations**, and **escalation path** as *outputs*. Model capability as a
constraint on workflow depth is original Fukasawa doctrine. It was never
carried into this repository, because the repo was commissioned to package an
existing generator and the philosophy behind that generator was never
transcribed. This ADR is recovery, not invention.

## Context

ADR-008 holds the model **constant** and varies the workflow configuration, so
the delta measures our intervention. That is the right experiment for the
question it asks: did Fukasawa improve the work?

It leaves a different question unasked. Nothing in the runtime measures
whether a *task* is well-scoped. Product principle 9 — "Reduction Beats
Control: when failure occurs, first ask whether the workflow is too complex" —
is asserted in `docs/product-principles.md`, repeated in the cooperation
guide, and surfaced nowhere as a measurement. It is a prompt to a human, and
an unfalsifiable one.

The operator's framing: *"If we need enterprise models to run this, then it's
too complex."* A step that passes only when a frontier model is behind it is
not a step awaiting better models. It is a step doing too much.

There is a matching failure on the agent side. Organizations assign a role,
attach a title, and assume competence follows; the holder either invents a
method or reconstructs their predecessor's. When the work succeeds, the
success belongs to the individual rather than the process, and nothing
transferable was built. An agent package whose task passes only with that
exact package has the same defect: the `CONTRACT.md` under-specifies the work
and the agent is silently carrying process nobody wrote down.

## Decision

**Add two swap axes to the ADR-008 harness. Both produce advisory findings
about the *step*, never about the model or the agent.**

### Axis 1 — model swap

Hold tasks, grader, and runner constant. Vary the model across declared
capability tiers. The **lowest tier that reliably passes is the step's
complexity score.**

A step that passes only at the highest declared tier emits an advisory
finding: the step is over-complex. **The sanctioned response is to reduce,
decompose, or sharpen the step** — not to adopt a larger model.

### Axis 2 — agent swap

Hold tasks, grader, and model constant. Vary the agent package. A step that
passes with only one package emits an advisory finding: its contract
under-specifies the work, and observed success is capability-derived rather
than process-derived.

### The axes stay separate

They are independent and must not be collapsed into one "stress score". A step
can be simple but under-specified (passes on a small model, fails the agent
swap) or complex but well-specified. Different diagnoses, different remedies.

## Relationship to ADR-008's binding constraints

This is the part that needs care, because a careless reading looks like a
contradiction.

* **ADR-008 §3, "never used to select a model", is preserved.** That
  constraint forbids using grades to *choose what model to run*. Here the
  model is the instrument, not the subject: the artifact produced is a
  property of the **step**, recorded against the workflow. No model is ranked,
  promoted, or selected, and "pick a bigger model" remains explicitly out of
  scope. If a future change proposes acting on these results by upgrading a
  model, that requires its own ADR and contradicts this one.
* **ADR-008 §1, peer tool, is preserved.** No import, no `pyproject.toml`
  entry, artifacts referenced by path.
* **ADR-008 §2, evidence never a gate, is inherited and matters more here.**
  These verdicts are derived from LLM outputs, so DoD §9.3 / §2.2 forbid them
  being load-bearing in an authoritative decision. They are advisory findings
  for a human, never blocking, and never an input to promotion.

## Implementation constraints worth stating now

* **Attribution is the blocking gap.** Outcome records must name the model
  endpoint and the agent package that produced them, or a matrix is
  uninterpretable. Today `EvalResult` (`src/schemas/eval_case.py`) carries
  neither field.
* **Tier declaration has no home yet.** `ModelEndpointRegistry`
  (`src/kernel/models.py`) has no tier concept, and `src/kernel/*` is FROZEN
  per the implementation directive §3. Tiers should therefore be declared in
  the endpoint **config file** rather than in kernel code, or the work waits
  for an explicit unfreeze. This ADR does not authorize touching a frozen file.
* Tier ordering is a declared property of the operator's own endpoints, not a
  published ranking of vendors' models.

## Alternatives considered

* **A single combined stress score.** Rejected: it averages two unrelated
  diagnoses into a number that names neither problem.
* **Static complexity heuristics** (step length, number of outputs, branching).
  Rejected: cheap, but unfalsifiable in exactly the way principle 9 already
  is. The value here is that a claim about complexity can be *wrong*.
* **Gating promotion on the complexity score.** Rejected under ADR-008 §2 and
  DoD §9.3 — an LLM-derived verdict must not be authoritative.

## Consequences

* Principle 9 gets its first falsifiable form. Everywhere else in the runtime
  reduction is a question put to a human; here it is a measurement with a
  verdict a human can dispute.
* The cooperation assessment gains a natural evidence source. Today
  `determinism` and `judgment_load` are declared by a person from
  introspection; a model-swap result is observed evidence about the same
  properties. Wiring that in is a separate ADR — the classification table must
  stay deterministic and model-free (§9.3).
* Phase 6 (prompt/module optimization) gains the per-module metrics its
  precondition names.
* `docs/evaluation-strategy.md` would name a third measurement: process
  conformance (built), outcome quality (ADR-008), and task complexity (here).
