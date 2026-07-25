# ADR-003 — Validator rule registry

**Status:** Proposed (Gate A)

## Context

Validation logic is currently dispersed across three idioms: structural
Pydantic validators inside models (e.g. `WorkflowBrief.
_check_states_are_consistent`), bare-string finding lists
(`src/foundry/validator.py:validate_package` → `list[str]`;
`GraphSpec.validate_against_brief` → `list[str]`), and eval-time checks
(`src/governance/checks.py`, declared per-case via `EvalCase.scoring`).
None of these produce findings with stable IDs, severity, location, or
remediation — which master handoff §7 requires for all 16 launch rules, and
DoD §2.2 requires for error reporting generally ("workflow object, step,
field, rule, severity, remediation").

## Decision

1. **One registry module, plain Python:** `src/governance/workflow_rules.py`
   holds a `RULES: dict[str, Rule]` where each `Rule` is a small dataclass:
   `rule_id` (stable, `HW-001`…`HW-016` mapping master handoff §7 order),
   `version`, `description`, `severity`, `blocking`, `detect(draft) ->
   list[WorkflowFinding]`, `remediation`. No DSL, no plugin loader, no
   external config — a rule is a reviewed Python function (deterministic,
   no LLM, per §9.3).
2. **Findings are typed:** `WorkflowFinding` (`src/schemas/findings.py`)
   carries workflow/step/field location, rule ID + version, severity,
   deterministic message, remediation, blocking flag, and acceptance state.
   One defect per finding (§7: no bundling unrelated defects).
3. **Division of labor is explicit:** Pydantic model validators keep
   rejecting *structurally malformed* data (can't-even-load); the registry
   evaluates *well-formed but deficient* workflows. The registry never
   duplicates a structural check.
4. **The rule catalog doc is derived from the registry** (IDs, severities,
   detection descriptions), so docs cannot drift from code.
5. **Existing string-based validators are left as-is this release** —
   migrating `validate_package` to typed findings is backlogged, not
   required by the DoD.

## Alternatives considered

- *Rules as YAML/JSON config*: detection logic still needs code; splitting
  declaration from logic doubles the drift surface. Rejected.
- *Extending `EvalCase`/`checks.py`*: evals score *runs after the fact*;
  workflow validation scores *artifacts before promotion* — different axis,
  different lifecycle. Rejected.
- *Renaming to avoid `registry/` collision*: the existing
  `registry/prompt-module-registry.yaml` (Phase 6 placeholder) is unrelated;
  docs must disambiguate ("validator rule registry" vs "prompt module
  registry").

## Consequences

- Adding a rule = one dataclass entry + tests (contributor guide, §18).
- Rule versions persist on findings, so accepted risks survive rule
  evolution auditable (§8: "schema and rule versions are persisted").
