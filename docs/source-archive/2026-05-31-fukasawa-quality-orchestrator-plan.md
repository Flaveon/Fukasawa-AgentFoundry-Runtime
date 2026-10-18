---
title: Fukasawa Quality Orchestrator Integration Plan
status: draft
date: 2026-05-31
origin: wiki/Standards/FukasawaGPT
---

# Fukasawa Quality Orchestrator Integration Plan

## Problem Frame

The Q2C pipeline can now block obvious junk, but blocking junk is not the same as generating quality. CPAX needs a repeatable quality operating system that turns every generated output into evidence for process improvement.

The FukasawaGPT standards pack defines the missing backbone: reduce unnecessary complexity, assign the least reasoning needed to each task, preserve observation versus inference, review non-conformance through a complexity-first lens, package stable processes into process capsules, and escalate only when lower layers cannot safely proceed.

The first proving ground is the whole Q2C publish package: article, HTML page, tool, visual support, handoff, deploy notes, failure log, and final ship/hold verdict.

## Source Review

Key source documents:

- `../wiki/Standards/FukasawaGPT/FukasawaGPT.md`: defines humane systems architecture, complexity budget, validate-before-scale phase gates, and quality doctrine.
- `../wiki/Standards/FukasawaGPT/Fukasawa_Task_Depth_Framework.md`: defines Level 0-5 reasoning layers, observation packets, process capsules, capability lift, and complexity-first non-conformance review.
- `../wiki/Standards/FukasawaGPT/Workflow_Design_Brief.md`: defines the Fukasawa-to-Agent-Foundry handoff format for Level 3+ agents.
- `../wiki/Standards/FukasawaGPT/Non_Conformance_Improvement_Opportunity.md`: defines the corrective-action template.

Current repo anchors:

- `q2c_pipeline.py`: pipeline runtime, agents, failure logs, deploy packaging, deterministic HTML checks.
- `docs/contracts/duath-packet.md`: current Duath output and QA contract.
- `docs/contracts/deploy-bundle.md`: deploy bundle contract.
- `docs/contracts/failure-log.md`: failure evidence contract.
- `docs/output-policy.md`: publish/share control policy.
- `docs/code-html-review-policy.md`: executable artifact review policy.
- `tests/test_contracts.py`: focused contract tests.

## Core Decision

Bootstrap with a high-reasoning Quality Orchestrator, then deliberately migrate stable work downward into lower-reasoning layers.

Early in the initiative, one big smart agent is acceptable because the task definition itself is still being discovered. The orchestrator needs enough reasoning capacity to observe failures, infer patterns, search for exemplars, improve prompts, and decide which checks can become rules.

The success condition is that the orchestrator becomes less expensive over time without making token minimization a worker-facing goal. Stable quality work should move from Level 4/5 reasoning into Level 0-2 rules, checks, triage packets, and process capsules. If the design works, token usage per publishable output should decrease while output quality and audience engagement improve.

Reasoning depth assignment:

- Level 0: deterministic checks for file existence, schema validity, placeholder links, pending-QC markers, empty files, missing bundle files, URL/tool mismatch, and failure-log presence.
- Level 1: bounded first-inference checks that identify suspected quality issues without claiming root cause.
- Level 2: local triage that classifies a failure as content, brand, tool, visual, packaging, source-truth, or workflow-definition failure.
- Level 3: domain quality agents that diagnose one package domain and propose corrective action.
- Level 4: Quality Orchestrator that runs the full loop, tracks state, collects evidence, decides retry/escalation, and writes the final report.
- Level 5: strategist or human escalation only after three failed improvement loops or when the workflow itself needs redesign.

Bootstrap rule:

- Use high-reasoning orchestration when the task definition is immature.
- Measure how much high-reasoning work was required.
- Convert repeated successful reasoning into deterministic checks, templates, process capsules, or lower-depth agents.
- Treat rising token cost without quality or engagement gain as a private governance signal, not a worker-facing penalty.

## Target Loop

Each package goes through this loop:

1. Define task quality standard.
2. Generate or collect output.
3. Measure against deterministic and judgment-based gates.
4. Decide `PASS`, `RETRY`, `HOLD`, or `ESCALATE`.
5. Record what went wrong using observation packets.
6. Diagnose why using complexity-first non-conformance review.
7. Select corrective action.
8. Execute corrective action.
9. Re-measure.
10. Log outcome and process learning.
11. Repeat up to three local loops.
12. Escalate to enterprise LLM retry if local loops fail.
13. Escalate to human if enterprise retry fails or quality standard is ambiguous.

## Implementation Units

### Unit 1: Quality Standard Loader

Purpose: Convert the CPAX Standards folder into task-specific quality packets.

Files:

- `q2c_pipeline.py`
- `docs/contracts/quality-orchestrator.md`
- `tests/test_contracts.py`

Design:

- Add a standards loading layer that can read known standards from the wiki path configured by environment.
- Keep the existing `Q2C_BRAND_KIT_PATH` behavior, but introduce a broader `Q2C_STANDARDS_ROOT` defaulting to `~/wiki/Standards`.
- Select standards by output domain:
  - Public brand and voice: `CPAX_Brand_Kit.md`
  - Workflow quality: `FukasawaGPT/FukasawaGPT.md`
  - Task depth and escalation: `FukasawaGPT/Fukasawa_Task_Depth_Framework.md`
  - Non-conformance review: `FukasawaGPT/Non_Conformance_Improvement_Opportunity.md`
  - Executable artifacts: `docs/code-html-review-policy.md`
  - External publish/share: `docs/output-policy.md`

Tests:

- Missing standards root falls back safely.
- Brand kit still loads from the existing path.
- Fukasawa standards packet includes task depth and non-conformance sections.
- Domain selection returns the expected standards for HTML/tool/package quality.

### Unit 2: Observation Packet and Quality Finding Schema

Purpose: Preserve observed evidence separately from inferred meaning.

Files:

- `q2c_pipeline.py`
- `docs/contracts/quality-orchestrator.md`
- `tests/test_contracts.py`

Design:

- Add a structured quality finding format with:
  - `check_id`
  - `artifact`
  - `level`
  - `observation`
  - `inference`
  - `confidence`
  - `missing_evidence`
  - `recommended_next_check`
  - `escalation_target`
- Use this schema for deterministic blockers and model-based QA findings.
- Store quality findings alongside `RUN_FAILURES`, but keep them separate from runtime failures.

Tests:

- Deterministic HTML blocker creates an observation packet, not only a string.
- Empty editor desk output records direct evidence and a bounded inference.
- Missing tool functionality records missing evidence instead of claiming final root cause.

### Unit 3: Whole-Package Quality Gate

Purpose: Evaluate the complete publish package, not individual HTML files only.

Files:

- `q2c_pipeline.py`
- `docs/contracts/deploy-bundle.md`
- `docs/contracts/quality-orchestrator.md`
- `tests/test_contracts.py`

Design:

- Add a package-level gate after deploy bundle staging.
- Required checks:
  - Final editorial exists and is non-empty.
  - Editor desk is non-empty or logged as a blocker.
  - Failure logs are present in the deploy package when failures occurred.
  - Files listed as publishable do not contain pending-QC markers.
  - Tool promises in article/deploy notes match an actual working tool artifact.
  - Visual support contains no placeholder images or dead CTAs.
  - Duath/Angela PASS cannot override deterministic blockers.
  - Delivery notes cannot recommend publish for held artifacts.
- Output a `quality-report.json` and `quality-report.md` in the deploy bundle.

Tests:

- A package with Angela PASS and placeholder HTML receives `HOLD`.
- A package with a missing tool but article tool promise receives `RETRY` or `HOLD`.
- A package with pending-QC HTML is excluded from publish list.
- A clean package can receive `PASS`.

### Unit 4: Corrective Action Planner

Purpose: Convert quality findings into a bounded retry plan.

Files:

- `q2c_pipeline.py`
- `docs/contracts/quality-orchestrator.md`
- `tests/test_contracts.py`

Design:

- Classify findings into corrective action classes:
  - Remove placeholder.
  - Regenerate artifact with stricter task definition.
  - Replace model judgment with deterministic rule.
  - Simplify scope.
  - Clarify input contract.
  - Move task downward to rule/checklist/script.
  - Escalate to specialist agent.
  - Escalate to enterprise LLM.
  - Escalate to human.
- Prefer reduction before addition, following Fukasawa non-conformance doctrine.
- Emit a per-loop `corrective-action.json` that lists intended changes, target artifacts, and measurement criteria.

Tests:

- Placeholder link maps to remove/replace CTA, not broad rewrite.
- Fake calculator maps to regenerate tool or remove tool promise.
- Repeated blank model output maps to model escalation after local retries.
- Ambiguous standard maps to human escalation, not infinite model retries.

### Unit 5: Three-Loop Retry State Machine

Purpose: Automate improvement without hiding repeated failure.

Files:

- `q2c_pipeline.py`
- `docs/contracts/quality-orchestrator.md`
- `tests/test_contracts.py`

Design:

- Add explicit loop state:
  - `loop_index`
  - `attempt_target`
  - `quality_before`
  - `corrective_action`
  - `quality_after`
  - `delta`
  - `decision`
- Run up to three local corrective loops.
- Stop early when the package passes.
- Escalate to enterprise LLM after three failed loops when the quality standard is clear but local execution fails.
- Escalate to human when the standard is unclear, the artifact is high-risk, or enterprise retry fails.

Tests:

- Passing after loop 1 stops further loops.
- Three failed loops trigger enterprise escalation.
- Enterprise failure triggers human escalation.
- Each loop writes measurement evidence.

### Unit 6: Non-Conformance Improvement Log

Purpose: Make every failure a process improvement opportunity.

Files:

- `q2c_pipeline.py`
- `docs/contracts/failure-log.md`
- `docs/contracts/quality-orchestrator.md`
- `tests/test_contracts.py`

Design:

- Add a durable `non-conformance.md` or `non-conformance.json` artifact per run when quality gates fail.
- Use the Fukasawa template:
  - event summary
  - expected outcome
  - actual outcome
  - complexity-first review
  - simplification opportunities
  - root cause finding
  - corrective action
  - preventive action
  - process update needed
  - verification
- Include this in the deploy package and production handoff.

Tests:

- Failed package writes non-conformance artifact.
- Artifact records complexity-first review.
- Preventive action is present and specific.
- Clean package does not create a false non-conformance.

### Unit 7: Capability Lift and Process Capsules

Purpose: Turn repeated successful corrections into lower-level reusable process.

Files:

- `docs/contracts/quality-orchestrator.md`
- `docs/process-capsules/`
- `q2c_pipeline.py`
- `tests/test_contracts.py`

Design:

- Introduce process capsule files for stable checks and corrections.
- Start with capsules for:
  - HTML publishability gate.
  - Tool reality check.
  - Deploy notes publish/hold reconciliation.
  - Failure log inclusion.
- Mark capsules `draft`, `tested`, or `validated`.
- Promote a correction downward only after evidence shows it is stable.

Tests:

- Process capsule files validate required fields.
- Validated capsules can be listed in the quality report.
- Draft capsules are not treated as authoritative gates unless explicitly configured.

## Escalation Policy

Local retry:

- Use local deterministic corrections and local model agents first.
- Maximum three local loops.

Enterprise LLM retry:

- Trigger when local loops fail but the standard is clear.
- Enterprise prompt must include:
  - original task definition
  - standards packet
  - quality findings
  - non-conformance summary
  - corrective-action history
  - explicit artifact target

Human escalation:

- Trigger when:
  - enterprise retry fails
  - quality standard is ambiguous
  - legal/medical/financial risk appears
  - external factual claims need current verification
  - publication decision remains contested

## Measurement

### KPI Interpretation

KPIs are indicators for leadership attention, not binary commands for worker behavior.

The quality system should not read a metric as "if high, do X; if low, do Y" without context. A KPI should show where responsible parties should focus investigation, investment, simplification, or capability-building.

For this reason, `engagement_per_token` should not be used as a static efficiency target. It should show whether the organization is spending reasoning in the right places. A temporary rise in token use is acceptable, and sometimes desirable, when the orchestrator is exploring a topic, learning a better task definition, finding exemplars, or increasing engagement. The question is not "how do we spend the fewest tokens?" The question is "where should reasoning be spent to create more valuable output?"

Quality reports visible to workers and operators should include:

- deterministic blocker count
- unresolved finding count
- loop count to pass
- number of fallbacks used
- package-level verdict
- artifact-specific verdicts
- manual changes required after run
- recurring non-conformance categories
- process capsules promoted

Internal governance metrics should include:

- engagement per token
- token cost per package
- token cost per passed package
- token cost per artifact class
- token cost per corrective loop
- enterprise/local token mix
- orchestrator/worker token mix
- engagement trend by topic class
- engagement delta after quality loops

Primary internal KPI:

```text
engagement_per_token = meaningful_engagement / total_generation_and_quality_tokens
```

Meaningful engagement may start with available proxies such as publish decision, manual reuse, website click-through, Substack engagement, reader replies, tool use, or operator rating. The exact engagement source can mature over time, but the denominator must include the quality loop, not just initial generation.

This KPI is private. It should be used by owners or governance review, not exposed to worker agents as a success target. If workers can see or optimize for it, they will learn to look efficient instead of becoming useful. Worker-facing goals should remain concrete: meet the quality standard, provide evidence, reduce unresolved blockers, preserve truthfulness, and improve the task definition.

Metric quality matters. Governance should strengthen metrics by:

- tracking which engagement signals are strongest versus weak proxies
- separating short-term engagement from durable value
- comparing topics by class instead of flattening all runs into one average
- recording whether extra reasoning changed the output in a way humans can identify
- correlating quality-loop actions with engagement outcomes
- preserving enough context to explain why a costly run was worth it or wasteful

Avoid detached vanity metrics. Every metric must connect to publish readiness, operator burden, failure recurrence, process simplification, engagement, capability growth, or private token-allocation governance.

## Private Mission Control Telemetry

Mission Control should display leadership-only telemetry for:

- engagement per token
- enterprise/local token mix
- orchestrator/worker token mix
- token spend by artifact and loop
- quality verdicts and non-conformance categories
- engagement records by topic, artifact, and channel
- capability-lift signals showing which work migrated from orchestrator reasoning to worker agents, deterministic checks, or process capsules

This panel is for owners and governance review only. It should not be presented to worker agents as an optimization target.

## Token Efficiency Hypothesis

The orchestrator begins expensive because quality standards are still being discovered.

Over time, token usage should decrease because:

- recurring defects become deterministic checks
- stable corrections become process capsules
- known-good task definitions reduce retry loops
- lower-depth shards handle bounded checks
- enterprise LLM escalation becomes rarer
- humans intervene on fewer routine quality failures

The desired pattern is steady modulation, not a race to a low static enterprise baseline.

Healthy evolution should look like:

- enterprise/orchestrator token use rises when exploring ambiguous or high-upside topics
- local worker token use rises as process capsules and task definitions mature
- deterministic checks absorb repeated known failures
- enterprise retries become more targeted, not necessarily zero
- engagement records improve when extra reasoning is spent well
- low-value loops are removed when extra reasoning does not improve engagement or quality

If private token usage rises without better engagement, the workflow may have accumulated complexity debt and should trigger a Fukasawa non-conformance review. The corrective action should not be "use fewer tokens" as an instruction to workers. It should be to simplify the workflow, clarify task definitions, move stable work downward, improve metric quality, or remove low-value loops.

## Sequencing

1. Document the `quality-orchestrator` contract.
2. Add standards loading and standards packet selection.
3. Add quality finding schema and deterministic observation packets.
4. Add whole-package quality report.
5. Add corrective-action planner.
6. Add three-loop retry state.
7. Add non-conformance artifact generation.
8. Add process capsule validation and promotion tracking.
9. Update Mission Control to display package quality state and non-conformance summaries.

## Rollout Gate

The first version should not auto-publish or auto-delete anything. It should:

- measure
- report
- retry only within safe generated artifacts
- hold when uncertain
- preserve all failure evidence
- produce a better task definition for the next loop

Automation can expand only after the quality reports show stable improvement and reduced human cleanup.

Expansion should also require private evidence that quality is getting cheaper, not just stricter: fewer tokens per accepted package, fewer tokens per corrective loop, or higher engagement per token. These are governance checks, not worker incentives.
