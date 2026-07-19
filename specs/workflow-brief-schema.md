# Workflow Brief Schema

## Purpose

The workflow brief is the Fukasawa-owned bridge from intent to buildable workflow.

## Required Fields

```yaml
brief_name:
date:
designed_by: FukasawaGPT
status: draft | reviewed | approved

workflow_intent:
  goal:
  trigger:
  outcome_definition:

complexity_budget:
  user_skill_level: beginner | builder | lab_operator
  available_hardware:
  maintenance_tolerance: low | medium | high
  desired_autonomy: low | medium | high

depth_recommendation:
  coordinator_level:
  shard_levels:
  reasoning:

agents_required:
  - agent_name:
    depth_level:
    responsibilities:
    inputs:
    outputs:
    escalation_target:

handoff_checklist:
  workflow_intent_unambiguous:
  depth_levels_assigned:
  escalation_paths_defined:
  output_schemas_specified:
  complexity_budget_evaluated:
  no_level_5_for_routine_execution:
  process_capsules_identified:
```

## Validation Rules

- `status: approved` is required before Level 3+ agent builds.
- Every agent must have one escalation target.
- Every output must name a schema or artifact type.
- `coordinator_level` cannot exceed 4 unless the workflow is explicitly marked redesign-only.
- Routine execution cannot depend on Level 5.
