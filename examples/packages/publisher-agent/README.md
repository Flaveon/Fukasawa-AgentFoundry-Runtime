# Agent Package — publisher-agent

Generated from approved workflow brief `q2c-production-handoff` (Q2C Production Handoff) by the Fukasawa-AgentFoundry runtime.

This package is self-contained: every behavior, boundary, and
expectation is declared in the files below. If something is not
written here, the agent does not do it.

| File | Purpose |
|---|---|
| SKILL.md | Role, responsibilities, workflow position, depth level |
| SOUL.md | Behavioral identity and communication principles |
| CONTRACT.md | Boundaries, permissions, escalation, failure handling |
| process_capsule.yaml | Transfer contract — inputs, steps, output schema |
| evals.yaml | The three mandatory checks (schema, escalation, scope) |
| simulations.yaml | Dry-run scenarios producing Observation Packets |
| learning_log.md | Failures and improvements, NC Opportunity format |
| permissions.json | Machine-readable path and tool grants |
| manifest.json | Package metadata for `fukasawa package validate` |

## Status

- maturity: **draft** — promotion to `tested` requires passing
  evals and human review; `candidate_skill.md` is created on the
  first proposed improvement.
- depth level: **0**
- deployment method: **file_package**
- workspace profile: **c-pax**
- escalation target: **flaveon**

## Deployment

Definition layer is this file package. Inject SKILL.md + SOUL.md +
CONTRACT.md as the system prompt; process_capsule.yaml declares the
I/O contract. Upgrade path per doctrine: manual run (draft) ->
CLI wrapper (tested) -> cron/file-watcher (validated) -> orchestrated.

## Validation

```bash
fukasawa package validate <path-to>/publisher-agent
```
