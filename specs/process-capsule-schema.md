# Process Capsule Schema

## Purpose

The process capsule is the transfer contract for a task, shard, or agent capability.

## Draft Schema

```yaml
task_name:
owner_agent:
maturity: draft | tested | validated
depth_level: 0 | 1 | 2 | 3 | 4 | 5

inputs:
  - name:
    type:
    required: true | false
    source:

steps:
  - name:
    depth_level:
    action:
    deterministic: true | false

known_failures:
  - failure:
    signal:
    response:

escalation_rules:
  - condition:
    target:
    requested_checks:

output_schema:
  status:
  evidence:
  confidence:
  recommended_next_step:

evals:
  required_cases:
  promotion_threshold:
```

## Validation Rules

- `maturity: validated` requires eval evidence.
- Any non-deterministic step must declare why reasoning is needed.
- Escalation rules are required for Level 1+.
- Output schema must include status, evidence, confidence, and recommended next step.
