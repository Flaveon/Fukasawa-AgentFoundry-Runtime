# Phase 4 Distributable App Handoff

## Objective

Wrap the validated local runtime into a distributable tool while preserving file-based inspectability.

## Inputs

- Phase 1 runtime
- Phase 2 package generator
- Phase 3 eval/governance loop
- pilot workflow evidence

## Tasks

1. Choose first distribution target: CLI, FastAPI service, local web UI, desktop app, MCP server, or GPT Action backend.
2. Keep CLI as the baseline interface even if another UI is added.
3. Add project initialization command.
4. Add workflow editor or generator.
5. Add run history viewer.
6. Add validation and eval reports.
7. Add export/import package format.
8. Write installation and operator docs.

## Output

- distributable prototype
- installation guide
- operator guide
- sample project export
- release readiness checklist

## Review Gate

Human review required before any public or client-facing distribution.
