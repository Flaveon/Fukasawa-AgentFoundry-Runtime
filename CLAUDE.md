# CLAUDE.md — Fukasawa-AgentFoundry-Runtime

## What This Project Is

You are building the Fukasawa-AgentFoundry Runtime: a local-first workflow governance layer for human-agent collaboration under ConcordiaPax. This is not a LangChain clone, a prompt manager, or a multi-agent swarm. It is structured accountability infrastructure for workflows that involve both human operators and AI agents.

The two source systems are FukasawaGPT (workflow architecture and complexity control) and Agent Foundry (agent package generation and deployment). This runtime is the executable layer that connects them.

Read README.md before writing any code. Everything you build must serve the product frame described there.

---

## First Task: Wire In the License

Before writing any code, create a LICENSE file in the repo root containing the full text of the GNU Affero General Public License v3.0 (AGPLv3). Fetch the canonical text from: [https://www.gnu.org/licenses/agpl-3.0.txt](https://www.gnu.org/licenses/agpl-3.0.txt)

Add the following SPDX header to every source file you create:

```python
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
```

---

## Tech Stack

Use Python 3.11+. Do not introduce frameworks that require infrastructure to run. This must execute locally with no cloud dependencies.

- **Pydantic v2** — schema validation for workflow briefs and process capsules  
- **SQLite** (via sqlite-utils) — durable run history and state ledger  
- **Typer** — CLI entry point  
- **PyYAML** — workflow brief input format  
- **Rich** — terminal output for human review gates

Install dependencies with: `pip install pydantic pyyaml typer sqlite-utils rich`

---

## Build Order

### Phase 0 — Schema and State Foundation

Build in this exact order. Do not skip ahead.

**Step 1: Workflow Brief Schema** Create `src/schemas/workflow_brief.py`. A WorkflowBrief must capture:

- `id` (str, unique slug)  
- `title` (str)  
- `owner` (str, the human responsible)  
- `task_depth` (enum: ROUTINE, GUIDED, CONSCIOUS — see note below)  
- `initial_state` (str)  
- `states` (list of valid state names)  
- `transitions` (list of Transition objects: from_state, to_state, owner, evidence_required)  
- `completion_criteria` (str, plain language definition of done)  
- `exception_path` (str, what happens when no condition matches)

Task depth classification:

- ROUTINE: decision has been made enough times to become a default. Safe to automate.  
- GUIDED: decision needs a consistent frame but not a rigid rule. Human confirms output.  
- CONSCIOUS: involves taste, ethics, responsibility, or meaning. Human owns entirely.

**Step 2: Process Capsule Schema** Create `src/schemas/process_capsule.py`. A ProcessCapsule is a single executable unit of work within a workflow:

- `id` (str)  
- `workflow_id` (str, foreign key to WorkflowBrief)  
- `state` (str, current state from the brief's state list)  
- `assigned_to` (str, human or agent identifier)  
- `inputs` (dict)  
- `outputs` (dict, populated on completion)  
- `evidence` (str, what was produced to satisfy transition requirements)  
- `status` (enum: PENDING, IN_PROGRESS, AWAITING_REVIEW, COMPLETE, NON_CONFORMANCE)  
- `created_at` (datetime)  
- `completed_at` (datetime, optional)  
- `non_conformance_note` (str, optional — populated when status is NON_CONFORMANCE)

**Step 3: State Machine** Create `src/runtime/state_machine.py`. Implement a WorkflowRuntime class that:

- Loads a WorkflowBrief from a YAML file  
- Creates ProcessCapsules and advances them through valid transitions  
- Enforces that transitions only occur when evidence_required is satisfied  
- Raises NonConformanceError when an attempted transition has no valid path  
- Logs every state change to the SQLite run ledger

**Step 4: Run Ledger** Create `src/runtime/ledger.py`. Every state transition must be recorded with: capsule_id, from_state, to_state, owner, evidence, timestamp, and whether it was a conforming or non-conforming event. This is the audit trail. It must be append-only. No record is ever deleted.

**Step 5: Human Review Gate** Create `src/runtime/review_gate.py`. When a capsule reaches a CONSCIOUS-depth transition, execution must pause and present the human operator with: current state, proposed next state, evidence provided, and the completion criteria. The operator types APPROVE, REJECT, or FLAG. REJECT sends the capsule to NON_CONFORMANCE. FLAG marks it for later review without blocking progress.

**Step 6: CLI Entry Point** Create `src/cli.py` with these commands:

- `fukasawa run <brief.yaml>` — start a workflow from a brief file  
- `fukasawa status <workflow_id>` — show current state of all capsules  
- `fukasawa history <workflow_id>` — print the full run ledger  
- `fukasawa review <capsule_id>` — open a human review gate for a specific capsule  
- `fukasawa nonconformance list` — show all capsules in NON_CONFORMANCE status

**Step 7: Example Workflow Brief** Create `examples/q2c-production-handoff.yaml` — a WorkflowBrief modeled on the Q2C content pipeline handoff. States should include: RESEARCH_COMPLETE, DRAFT_READY, EDITOR_REVIEW, APPROVED, PUBLISHED, FAILED. The owner of the EDITOR_REVIEW transition is always a human. The APPROVED to PUBLISHED transition requires evidence of a final filename and destination path.

---

## What Done Looks Like for Phase 0

`fukasawa run examples/q2c-production-handoff.yaml` executes without error, advances a capsule through at least two state transitions, pauses at the human review gate, records the full history to SQLite, and surfaces a non-conformance when a transition is attempted without evidence.

---

## Constraints

- No network calls during runtime execution. Schema fetches and license fetches happen once at setup.  
- No hardcoded agent names or model identifiers. Agents are strings in the brief YAML.  
- Every function has a docstring. Every schema field has a description. This code will be read by humans who are not developers.  
- If you are unsure whether a decision belongs in the schema or the runtime, put it in the schema. Schemas can be edited by non-developers. Runtime logic cannot.  
- When in doubt, stop and write a comment explaining what the next step requires rather than guessing. Guessing creates non-conformance.

---

## What Not to Build in Phase 0

Do not build: agent execution, model API calls, multi-agent routing, a web UI, authentication, or deployment packaging. Those are Phases 2 through 4\. Build the foundation correctly first.  
