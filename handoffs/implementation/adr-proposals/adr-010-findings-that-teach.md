# ADR-010 — Findings that teach: doctrine fields on rules and findings

**Status:** Proposed (post-release; extends ADR-003, non-breaking)
**Raised:** 2026-08-07, operator-directed.
**Depends on:** `adr-003-validator-rule-registry.md`. This adds fields to the
registry and the finding contract it defines; it changes no rule logic.

## Context

The product does two things at once: it builds workflows, and it trains the
person building them. The training happens almost entirely at the moment of
refusal — a blocked promotion, a failed validation, a step the table will not
automate. That moment is the product's main teaching surface, and it is
currently used to deliver instructions only.

`WorkflowFinding` (`src/schemas/findings.py`) carries `message` — what is
wrong — and `remediation` — what to do about it. Both are good, and both are
mechanical. Neither says **why the rule exists**, so an operator learns the
runtime's preferences by accumulation rather than by understanding, and cannot
tell a rule that protects them from a rule that merely inconveniences them.

Principle 9 makes this concrete. "Reduction Beats Control — when failure
occurs, first ask whether the workflow is too complex" is doctrine, it is
correct, and it appears in no failure message anywhere in the runtime. The one
moment where it would change someone's behavior is the one moment it is
absent.

## Decision

**Add three fields to the `Rule` dataclass
(`src/governance/workflow_rules.py`) and to `WorkflowFinding`
(`src/schemas/findings.py`). Add no new type.**

| Field | Contents |
|---|---|
| `why` | The doctrine reason the rule exists, in plain language |
| `principle` | The product principle applied, e.g. "Principle 3 — Contracts Before Autonomy" |
| `reduction_prompt` | The principle-9 question, asked *before* the remediation is offered |

`reduction_prompt` is the field that separates training from error reporting.
Every blocking finding asks whether the workflow is too complex before it
tells anyone how to satisfy the rule.

**A registry test asserts all three are non-empty for every blocking rule.**
Teaching becomes a build-breaking invariant rather than an intention. This is
the whole point of the proposal: a `why` that is merely encouraged is the
field that ships empty two phases later.

**The derived rule catalog gains the fields.** ADR-003 §4 already generates
the catalog from the registry so docs cannot drift; with these fields that
document becomes the operator's doctrine reference rather than a lookup table.

## Scope limits

* **No rule logic changes.** Detection, severity, and blocking behavior are
  untouched. This is presentation and provenance only.
* **Non-blocking findings need only `why`.** Requiring a reduction prompt on
  an advisory nit would produce filler, and filler is what the completeness
  test exists to prevent.
* **String-based validators stay as they are**, consistent with ADR-003 §5,
  which already backlogs migrating `validate_package` to typed findings. If
  that migration happens, it inherits these fields.

## Compatibility

* **R1 / ADR-002 does not apply.** The signature-canonicalization tripwire is
  scoped to `GraphSpec` and `BundleManifest`; `WorkflowFinding` is neither
  signed nor hash-pinned. Confirmed against the risk register before writing
  this.
* The fields are additive and defaulted, so existing findings deserialize
  unchanged. `WorkflowFinding.schema_version` and `ValidationReport` follow
  normal ADR-002 versioning discipline for an additive change.
* No file frozen by directive §3 is involved. `src/schemas/findings.py` and
  `src/governance/workflow_rules.py` are owned by the validator phase, which
  should own this change too.

## Alternatives considered

* **A separate teaching document keyed by `rule_id`.** Rejected: it is the
  drift ADR-003 §4 deliberately designed the derived catalog to prevent. Two
  sources, one of which is not executed, diverge.
* **Fold the reasoning into `remediation`.** Rejected: unstructured prose
  cannot be tested for presence, cannot be rendered differently by weight in a
  UI, and mixes the instruction with the justification so a reader in a hurry
  loses both.
* **Leave it to the docs.** Rejected on the observation that opened this: the
  operator is not reading `product-principles.md` at the moment they are
  blocked. Doctrine that is not at the point of failure is doctrine that is
  not applied.

## Consequences

* The rule catalog becomes a teaching artifact, generated from code.
* Writing a new rule costs more: an author must state why it exists and what
  simplification would remove the need for it. That cost is the feature —
  a rule whose author cannot articulate a reason is a rule worth questioning.
* Refusal text becomes reviewable as content. Whether a `why` actually teaches
  is a judgment a human should make, and having the field makes that
  reviewable at all.
