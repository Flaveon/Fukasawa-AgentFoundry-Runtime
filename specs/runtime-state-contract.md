# Runtime State Contract

## Purpose

`RuntimeState` is the durable record of where a workflow run stands. It prevents state from living only in chat history.

## Draft Schema

```yaml
runtime_state:
  schema_version: 0.1
  run_id:
  workflow_id:
  workflow_name:
  created_at:
  updated_at:
  operator:
  status: pending | running | blocked | human_review | complete | failed
  phase:
  current_node:
  depth_level:
  inputs:
    artifacts:
      - path:
        kind:
        required: true | false
  outputs:
    artifacts:
      - path:
        kind:
        produced_by:
  completed_checks:
    - check:
      result: pass | fail | skipped
      evidence:
  human_gate:
    required: true | false
    reason:
    status: pending | approved | rejected | not_required
    reviewer:
    reviewed_at:
  blocked_reason:
  next_action:
  trace_path:
  non_conformance_path:
```

## Rules

- Every node transition updates `updated_at`.
- Every produced artifact must have a path.
- A blocked run must include `blocked_reason` and `next_action`.
- A human review state must include `human_gate.reason`.
- Completion requires at least one verification check.
