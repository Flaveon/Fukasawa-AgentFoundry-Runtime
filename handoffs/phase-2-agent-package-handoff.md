# Phase 2 Agent Package Handoff

## Objective

Build the Agent Foundry package generator on top of validated Fukasawa workflow briefs.

## Inputs

- approved workflow brief
- Phase 1 schema validators
- `../agent_foundry_gpt_builder_brief_v_1 (1).md`
- `specs/process-capsule-schema.md`

## Tasks

1. Create agent package templates.
2. Generate `SKILL.md`, `SOUL.md`, `CONTRACT.md`, `process_capsule.yaml`, `evals.yaml`, `simulations.yaml`, `learning_log.md`, `permissions.json`, and `README.md`.
3. Inject C-Pax path profile when target workspace uses numbered directories.
4. Validate generated package files.
5. Emit a build report and review checklist.
6. Add package-generation tests.

## Output

- generated package prototype
- package validation command
- sample package from pilot workflow
- build report

## Review Gate

Human review required before package promotion from `draft` to `tested`.
