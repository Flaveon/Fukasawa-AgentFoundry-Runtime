# Build Report — Q2C Production Handoff

- brief: `q2c-production-handoff` (status: approved)
- generated: 2026-07-23T03:07:10+00:00
- workspace profile: c-pax
- packages: 2

## Packages

- `examples/packages/writer-agent` — depth 2, deploys as file_package, escalates to flaveon, maturity draft
- `examples/packages/publisher-agent` — depth 0, deploys as file_package, escalates to flaveon, maturity draft

## Review Checklist (human, before any promotion)

- [ ] SKILL.md responsibilities match what the workflow actually needs
- [ ] Depth levels are the lowest that work — not the most impressive
- [ ] Escalation targets are correct and reachable
- [ ] CONTRACT.md forbidden list covers the failure modes you fear
- [ ] permissions.json paths are the only paths each agent touches
- [ ] evals.yaml three mandatory checks are intact
- [ ] No agent owns a CONSCIOUS decision

Promotion from draft to tested requires passing evals AND this
checklist signed off by a human. The generator cannot promote.
