# Architecture

## System Shape

The runtime has four layers.

## 1. Contract Layer

The contract layer defines the durable objects that move through the system.

Core objects:

- `WorkflowDesignBrief`
- `TaskDepthAssessment`
- `ProcessCapsule`
- `ObservationPacket`
- `AgentPackageManifest`
- `RuntimeState`
- `RunTrace`
- `HumanGate`
- `EvaluationCase`
- `EvaluationResult`
- `NonConformanceRecord`
- `PromotionDecision`

This layer should be plain schemas first: JSON Schema or Pydantic models. Markdown remains the human-readable presentation, but the runtime should validate structured data.

## 2. Runtime Layer

The runtime layer owns state transitions.

Responsibilities:

- create a workflow run
- validate input contracts
- execute or dispatch nodes
- persist state after every transition
- pause for human review gates
- resume after approval, correction, or rejection
- record non-conformance
- produce final handoffs

Initial storage should be file-backed JSON plus SQLite or DuckDB for queryable history. Do not require a server for Phase 1.

## 3. Agent Package Layer

The agent package layer turns an approved workflow brief into agent definitions.

Generated package shape:

```text
agent-name/
|-- SKILL.md
|-- SOUL.md
|-- CONTRACT.md
|-- process_capsule.yaml
|-- evals.yaml
|-- simulations.yaml
|-- learning_log.md
|-- permissions.json
`-- README.md
```

Every package must declare:

- depth level
- maturity
- owner
- input schema
- output schema
- allowed tools
- forbidden behavior
- escalation target
- evaluation checks
- deployment method

## 4. Adapter Layer

Adapters connect the runtime to tools without making those tools the architecture.

Initial adapters:

- filesystem adapter
- shell/Codex adapter
- OpenAI API adapter
- local model adapter
- DuckDB adapter
- git adapter
- human review adapter

Possible later adapters:

- LangGraph adapter for complex state graphs
- DSPy adapter for prompt/module optimization
- Qdrant adapter for vector-backed retrieval
- MCP adapter for tool exposure
- n8n adapter for automation

## Workflow Lifecycle

```text
intake
  -> workflow_design_brief
  -> schema_validation
  -> complexity_gate
  -> agent_foundry_package
  -> simulation
  -> evaluation
  -> human_review
  -> deployment
  -> run_trace
  -> non_conformance_or_promotion
```

## Runtime State Model

State should be explicit and resumable.

Minimum state:

```yaml
run_id:
workflow_id:
phase:
status: pending | running | blocked | human_review | complete | failed
current_node:
inputs:
outputs:
artifact_paths:
completed_checks:
blocked_reason:
human_gate:
trace_path:
next_action:
```

## Why Not Make LangChain The Core

LangChain is useful for integrations, but Fukasawa's value is workflow design, governance, and capability depth. Making LangChain the center would invert the product around generic chains and tools.

Use LangChain components only when a concrete adapter saves work.

## Why Not Make DSPy The Core

DSPy is useful for improving LLM modules after examples and metrics exist. It does not replace Fukasawa's complexity budget, handoff doctrine, process capsule standard, or agent maturity model.

Use DSPy later for specific prompt/module optimization experiments.

## Why LangGraph May Be Useful Later

LangGraph maps well to the orchestration kernel: durable state, resumable nodes, human gates, retries, and long-running workflows.

The runtime should first define its own state and node semantics. Then LangGraph can be used as an optional execution backend if it reduces code without hiding governance state.
