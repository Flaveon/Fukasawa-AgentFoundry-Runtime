# Fukasawa-AgentFoundry Runtime

## Purpose

This project defines the path from FukasawaGPT and Agent Foundry as GPT knowledge packs into a standalone ConcordiaPax workflow scaffolding and governance runtime.

The runtime should help a human operator design, validate, run, review, and improve agent-supported workflows without turning every process into a generic agent framework. Fukasawa owns workflow architecture and complexity control. Agent Foundry owns agent package generation, simulations, maturity tracking, and deployment packaging.

## Product Frame

The product is not a LangChain clone, a prompt manager, or a black-box multi-agent swarm.

The product is a local-first workflow governance layer with:

- typed workflow briefs
- task-depth classification
- process capsules
- executable handoff contracts
- human review gates
- non-conformance review
- agent package generation
- simulation and eval loops
- durable run history
- optional adapters for external tools

## Source Inputs

- `../FukasawaGPT/# FukasawaGPT.md`
- `../FukasawaGPT/Fukasawa_Task_Depth_Framework.md`
- `../FukasawaGPT/Workflow_Design_Brief.md`
- `../FukasawaGPT/# Non-Conformance Improvement Opportunit.md`
- `../agent_foundry_gpt_builder_brief_v_1 (1).md`
- `../Project_Directory_Standard.md`

## Key Distinction

Fukasawa and Agent Foundry already contain the design method. The missing layer is executable infrastructure:

- state machine
- schema validation
- trace ledger
- adapter boundary
- prompt/module registry
- workflow node library
- eval harness
- resumable run model
- distributable app shell

LangGraph and DSPy are useful comparison points, but not governing architecture. Borrow the runtime ideas, not the worldview.

## Directory Map

```text
Fukasawa-AgentFoundry-Runtime/
|-- README.md
|-- AGENTS.md
|-- roadmap.md
|-- brief/
|   `-- project-brief.md
|-- docs/
|   |-- architecture.md
|   |-- dependencies.md
|   |-- evaluation-strategy.md
|   `-- product-principles.md
|-- handoffs/
|   |-- phase-0-discovery-handoff.md
|   |-- phase-1-schema-runtime-handoff.md
|   |-- phase-2-agent-package-handoff.md
|   |-- phase-3-eval-governance-handoff.md
|   `-- phase-4-distributable-app-handoff.md
|-- specs/
|   |-- runtime-state-contract.md
|   |-- workflow-brief-schema.md
|   `-- process-capsule-schema.md
`-- tasks/
    `-- backlog.md
```

## Current Status

Status: planning package

Next action: review `roadmap.md`, then start Phase 0 discovery against one real workflow such as Oldowan cataloging or Q2C production handoff.
