# Project Brief

## Working Name

Fukasawa-AgentFoundry Runtime

## Goal

Develop FukasawaGPT and Agent Foundry into a standalone ConcordiaPax workflow scaffolding and governance runtime, with a path toward a distributable local-first tool.

## Problem

ConcordiaPax workflows already use structured handoffs, agent prompts, process capsules, and project directories. The problem is that much of the workflow state still lives in chat context, scattered markdown, agent memory, and operator recollection.

That creates recurring failures:

- agents lose the goal after context shifts
- handoffs omit artifact paths or next actions
- verification is reported but not tied to durable state
- agent roles drift above their intended reasoning level
- humans have to reconstruct what happened from logs
- workflow improvements are documented but not enforced

## Product Thesis

Fukasawa and Agent Foundry should become a runtime that makes workflow structure executable.

Fukasawa should decide what the workflow is, how deep each task should be, where reasoning is justified, and where complexity should be reduced.

Agent Foundry should turn validated workflow roles into agent packages with process capsules, contracts, simulations, evals, deployment modes, and maturity history.

The runtime should connect both through schemas, state transitions, human review gates, run logs, and evaluation records.

## Intended Users

- ConcordiaPax operator
- Codex/Claude/GPT agents working inside the C-Pax workspace
- future builders who need a portable agent-workflow governance tool
- local-first or homelab operators who distrust black-box automation

## Initial Use Cases

- Generate a workflow design brief from a messy operational goal.
- Validate that a workflow brief is complete before Agent Foundry builds agents.
- Generate agent packages with process capsules and evaluation files.
- Track a workflow run from trigger to handoff to human review.
- Capture non-conformance when an agent misses context, overreaches, or fails to produce verifiable outputs.
- Promote stable tasks downward into scripts, rules, validations, or lower-depth agents.
- Compare agent prompt/module versions against reviewed examples.

## Non-Goals

- Replace all agents with one master coordinator.
- Build a general-purpose LangChain clone.
- Make every workflow autonomous.
- Hide execution state inside chat transcripts.
- Require cloud services for the core runtime.
- Optimize prompts before reviewed examples and metrics exist.

## Success Criteria

- A real ConcordiaPax workflow can be represented as typed state and run through phase gates.
- Fukasawa outputs can be validated before Agent Foundry consumes them.
- Agent Foundry packages can be generated with consistent schemas, evals, simulations, and deployment metadata.
- Each run produces a durable trace that answers what happened, what changed, what passed, what failed, and what should happen next.
- Non-conformance records feed back into workflow simplification.
- The local runtime can later be wrapped as a CLI, service, or desktop/web app without rewriting the core contracts.
