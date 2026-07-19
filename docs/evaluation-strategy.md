# Evaluation Strategy

## Evaluation Goal

The runtime should evaluate workflow quality, not just model output quality.

The key question is:

Can another agent or human continue the work without reconstructing missing context?

## Default Checks

### Handoff Completeness

Pass conditions:

- objective is present
- artifact paths are present
- current state is present
- next action is executable
- blocker status is explicit
- verification evidence is linked or summarized

### Observation Discipline

Pass conditions:

- observations are separated from inferences
- confidence is stated
- missing evidence is stated
- unsupported claims are absent

### Depth Compliance

Pass conditions:

- agent stays within declared depth level
- low-level tasks do not redesign workflow
- coordinator does not perform every task
- strategist is not required for routine execution

### Escalation Correctness

Pass conditions:

- ambiguity triggers escalation
- blocked state is durable
- requested checks are concrete
- escalation target is named

### Complexity Reduction

Pass conditions:

- repeated failures trigger non-conformance review
- corrective action considers removing or simplifying steps before adding controls
- process changes are tied to evidence

## Eval Case Format

```yaml
case_id:
name:
workflow:
input_artifacts:
expected_outputs:
  required_fields:
  forbidden_claims:
  expected_escalation:
  expected_depth:
scoring:
  handoff_completeness:
  observation_discipline:
  depth_compliance:
  escalation_correctness:
  complexity_reduction:
notes:
```

## Promotion Criteria

A process can move from `draft` to `tested` when:

- it has at least three passing eval cases
- its output schema is stable
- expected escalation behavior is documented
- a human has reviewed the first real output

A process can move from `tested` to `validated` when:

- it has repeated real-world successful runs
- non-conformance events are low or resolved
- a lower-depth implementation is considered and either adopted or rejected with rationale
- another agent can consume its handoff without extra prompting

## DSPy Fit

DSPy becomes useful after this evaluation layer exists. Its role would be to optimize prompt modules against these metrics, not to define the workflow architecture.

Candidate DSPy modules:

- handoff summarizer
- non-conformance classifier
- task-depth classifier
- process capsule drafter
- workflow brief reviewer

Do not optimize until the baseline prompt and manual review examples exist.
