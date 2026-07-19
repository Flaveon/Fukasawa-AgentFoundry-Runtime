# Agent Instructions

## Project Role

This project turns FukasawaGPT and Agent Foundry into a ConcordiaPax workflow scaffolding and governance runtime. Agents working here must preserve the product distinction:

- Fukasawa designs workflow architecture, task depth, complexity budget, and escalation rules.
- Agent Foundry generates, tests, evaluates, packages, and promotes agents.
- The runtime enforces state, schemas, handoffs, evaluation, and audit history.

## Source Order

Read these first:

1. `README.md`
2. `brief/project-brief.md`
3. `roadmap.md`
4. `docs/product-principles.md`
5. `docs/architecture.md`

Then read source doctrine from:

1. `../FukasawaGPT/# FukasawaGPT.md`
2. `../FukasawaGPT/Fukasawa_Task_Depth_Framework.md`
3. `../FukasawaGPT/Workflow_Design_Brief.md`
4. `../agent_foundry_gpt_builder_brief_v_1 (1).md`

## Working Rules

- Do not replace Fukasawa with LangChain, LangGraph, DSPy, CrewAI, AutoGen, or another generic wrapper.
- Borrow external framework ideas only when they expose a concrete missing runtime primitive.
- Prefer local-first, inspectable formats: Markdown, YAML, JSON, Python, SQLite, DuckDB.
- Treat schemas and run state as product features, not implementation details.
- Keep human review gates explicit.
- Do not allow routine workflows to require Level 5 reasoning.
- Convert repeated decisions into lower-level rules, scripts, or validations.
- Record non-conformance when handoffs drift, ownership is unclear, outputs are unverifiable, or too much context is required.

## Output Standards

Every implementation handoff should include:

- objective
- current phase
- source artifacts
- files changed or expected
- accepted inputs
- produced outputs
- state transitions
- evaluation checks
- human review gate
- known blockers
- next action

Every runtime design proposal should answer:

- What reasoning depth is required?
- What can be deterministic?
- What state is persisted?
- What schema validates the output?
- What evidence promotes this process?
- What failure mode creates non-conformance?

## Anti-Patterns

- Do not create one large agent that performs every role.
- Do not add orchestration because orchestration is fashionable.
- Do not hide workflow state inside chat history.
- Do not treat a prose handoff as sufficient when a typed state object is needed.
- Do not optimize prompts before there are examples and metrics.
- Do not build a distributable app before the local runtime proves useful on real ConcordiaPax workflows.
