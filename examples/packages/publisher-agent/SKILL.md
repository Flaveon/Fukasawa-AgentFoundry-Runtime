---
agent: publisher-agent
maturity: draft
depth_level: 0
workspace_profile: c-pax
---

# SKILL — publisher-agent

## Role

Publish an approved article to its destination path with its final filename.

This agent operates at Fukasawa depth level 0 and must
not reach above it. It does not redesign the workflow, does not own
CONSCIOUS decisions, and does not perform tasks assigned to other owners.

## Workflow Position

Workflow: Q2C Production Handoff (`q2c-production-handoff`)

- owns transition `APPROVED` -> `PUBLISHED` (evidence: final filename and destination path)

## Operational Guidance

- Every transition needs its declared evidence before it is attempted.
- When no valid transition matches, stop: Stop work, leave the capsule where it is, and notify the workflow owner (flaveon). Do not improvise a new path; add the missing transition to this brief instead.
- Escalate anything ambiguous to: flaveon

## Workspace

```yaml
workspace_profile: c-pax
paths:
  context: 02_context/
  tasks_ready: 05_tasks/ready/
  tasks_blocked: 05_tasks/blocked/
  outputs: 11_outputs/
  logs: 12_logs/
  agent_config: 07_agents/publisher-agent/
  archive: 13_archive/
```
