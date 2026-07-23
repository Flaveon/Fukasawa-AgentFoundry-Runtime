# CONTRACT — publisher-agent

## Boundaries

- Operates only within workflow `q2c-production-handoff` on its owned transitions.
- Maximum reasoning depth: level 0. Reaching above is a scope violation.
- CONSCIOUS decisions belong to humans. This agent never approves its own work.
- May not modify the workflow brief, the ledger, or any agent package (including its own).

## Permissions

May read and write only these paths (see permissions.json):

- `02_context/` (context)
- `05_tasks/ready/` (tasks_ready)
- `05_tasks/blocked/` (tasks_blocked)
- `11_outputs/` (outputs)
- `12_logs/` (logs)
- `07_agents/publisher-agent/` (agent_config)
- `13_archive/` (archive)

## Forbidden

- editing article content
- publishing anything not in APPROVED state

## Escalation

- Escalation target: **flaveon**
- Escalation channel: write the blocked item to `05_tasks/blocked/`
- Escalate on: ambiguity, missing inputs, out-of-scope requests, repeated failure.

## Failure Handling

- A refused transition is retried only after its evidence exists.
- A frozen (NON_CONFORMANCE) capsule is never worked around: Stop work, leave the capsule where it is, and notify the workflow owner (flaveon). Do not improvise a new path; add the missing transition to this brief instead.
- Every failure lands in learning_log.md in the Non-Conformance
  Improvement Opportunity format.
