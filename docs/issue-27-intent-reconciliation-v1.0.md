<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Copyright (C) 2026 ConcordiaPax LLC -->

# Issue #27 — Intent Reconciliation v1.0

Date: 2026-10-17
Status: **reading, not a decision.** This document changes no behaviour and approves nothing. It records where the code stands against the original plan and lists the decisions only the owner can make.
Milestone: M0 (source reconciliation), per `docs/fukasawa-north-star-v1.0.md`.

---

## 1. Purpose and precedence

### Purpose

The 2026-05-31 *Fukasawa Quality Orchestrator Integration Plan* is now archived
word for word at `docs/source-archive/2026-05-31-fukasawa-quality-orchestrator-plan.md`.
Its provenance and hash are in `docs/source-archive/PROVENANCE.md`. This document takes
every part of that plan (its seven implementation units, the acceptance
examples under each one, its escalation, measurement, telemetry and rollout
sections) and answers four questions about each:

1. What did the plan intend?
2. What in this repository carries it today, if anything? Every carrier was checked by reading the code.
3. How faithful is that carrier?
4. What would close the gap, how would we prove it, and does the owner need to decide anything?

It builds on `docs/source-to-contract-map.md` (called "the map" below). The map
traces the four Fukasawa doctrine documents. This document traces the
plan. Where both cover the same ground, this document cites the map's row
and does not repeat it.

### Precedence

This order applies whenever sources disagree. It restates `docs/fukasawa-north-star-v1.0.md`, "Authoritative source hierarchy":

| Source | What it governs |
|---|---|
| Owner-approved, dated intent: the North Star (2026-10-13), plus the plan and doctrine it names as product-intent sources | **Direction**: what the product is meant to become |
| Approved contracts and ADRs: ADR-001 to ADR-007 as ruled in `handoffs/reviews/approved-adrs.md` | **Safe current behaviour**: how implemented code may change without breaking things |
| Code and tests | **Current behaviour**: what works today. Not authority to redefine scope. |

Two consequences follow:

- **Discrepancies are recorded, not silently resolved.** No row below changes code, and no row is "closed" by rewording a document.
- **ADR-008, ADR-009 and ADR-010 are proposals, not approvals.** Where this document says `DEFERRED`, it means a proposed ADR names a recovery path. It does not mean that path is authorised.

A note on the plan's own status. Its front matter says `status: draft`, and
`PROVENANCE.md` confirms it "was never marked approved". The plan has
authority because the owner-approved North Star names it as a product-intent
source. It is not an accepted contract. Its specific numbers, such as "three
local loops", are pilot policy. The North Star says so explicitly about the
loop count.

### Where each unit lives

The plan was written for the **Q2C content pipeline**, a separate private
repository. Every unit lists `q2c_pipeline.py` as its file. The North Star
later lifted the plan's loop into this runtime's product intent. So each row
below is classified with one rule:

- If the row describes **generic Fukasawa behaviour** (observation discipline, non-conformance diagnosis, capability lift, measurement, safe rollout), it gets a verdict about **this runtime**.
- If the row describes something **specific to the Q2C publish package** (HTML placeholder checks, the Angela/Duath agents, deploy bundles, `quality-report.json`, the Mission Control panel), it is `OUT_OF_REPO`. For those rows, the carrier column reports what the private pipeline actually has. That was checked read-only against commit `c49a5cb` (the commit that added this plan). Pipeline citations are written `pipeline:q2c_pipeline.py:LINE` at that commit. The pipeline's working copy has uncommitted changes on top of `c49a5cb`. Where those matter, the row says "uncommitted".

### Verdicts

| Verdict | Means |
|---|---|
| `CARRIED` | This runtime carries it with the plan's meaning intact. |
| `WEAKENED` | This runtime carries it, but it says materially less than the plan. |
| `DROPPED` | Nothing in this runtime carries it, and no proposal names a path back. |
| `DEFERRED` | Nothing carries it yet, but a **proposed** (unapproved) ADR names a path. |
| `OUT_OF_REPO` | It belongs to the Q2C pipeline. The carrier column says what the pipeline has. |

The "Decision" column points to the numbered questions in section 4.

---

## 2. Trace table

Line numbers refer to the archived plan. Quotes are verbatim and 25 words or fewer.

### 2.1 Framing and core decision

| ID | Source passage | Intended behaviour | Current carrier | Verdict | Risk | Proposed resolution | Test that would prove it | Decision |
|---|---|---|---|---|---|---|---|---|
| F1 | L14: "reduce unnecessary complexity, assign the least reasoning needed to each task" | Before validating or automating, weigh the workflow against a complexity budget: operator skill, hardware, time, maintenance tolerance and more. | None. Map §1, "Complexity Budget System" row, and Losses §3. `src/schemas/workflow_brief.py:93-140` has no budget block. ADR-009 covers only the hardware/model slice. | `DEFERRED` | Workflows get judged only on accountability holes, never on whether they are too heavy for the person running them. | Section 3, priority 1. | A workflow with no budget declared shows an advisory finding naming the missing inputs. A workflow with a declared budget shows the budget and the reasoning in its validation report. | Y: Q2 |
| F2 | L39: "Bootstrap with a high-reasoning Quality Orchestrator, then deliberately migrate stable work downward into lower-reasoning layers." | One capable orchestrator learns the task first. Then its stable work is moved down into cheaper layers. | This runtime deliberately has no model in any authoritative path (`README.md`, intro). Pipeline: no orchestrator agent exists. The package report is built by plain code (`pipeline:q2c_pipeline.py:4431`). | `OUT_OF_REPO` | If no orchestrator learns anything, there is nothing to migrate downward. The capability-lift half (U7.2) has no input. | Keep any model-based orchestrator in the pipeline. This runtime records its findings and governs migrations (priority 3). | Not applicable here. | Y: Q1 |
| F3 | L48: "Level 1: bounded first-inference checks that identify suspected quality issues without claiming root cause." | Each quality task gets a reasoning level from 0 to 5, and each level has its own output shape. | `src/schemas/agent_spec.py:57` (`depth_level` 0-5). `src/schemas/workflow_brief.py:35` (`TaskDepth`). The Level 5 refusal is at `workflow_brief.py:167-190`. Map §2 marks the per-level output requirements `DROPPED`. | `WEAKENED` | A Level 1 checker can emit a root-cause claim and pass. Nothing ties output shape to declared level. | No new work proposed here. The map already records it. Revisit after priority 2. | An agent declared Level 1 that emits a root-cause field fails a depth-compliance check. | N |
| F4 | L57: "Measure how much high-reasoning work was required." | Record how much expensive reasoning each task actually consumed, so the stable parts can be moved down. | None. `src/nodes/summary.py` reports hardware speed, not usage. ADR-009 proposes a model-swap measurement. | `DEFERRED` | "This step needs less reasoning" stays a guess. It can never be shown wrong. | Part of priority 3. For #27, record the reasoning calls per run for the one case only (Q7). | The baseline run and the candidate run of the #27 case each show a count of model calls and their token totals. | Y: Q7 |
| F5 | L68: "Decide `PASS`, `RETRY`, `HOLD`, or `ESCALATE`." | Every measured package ends with one of four verdicts. | Runtime: `src/runtime/review_gate.py:29-34` (APPROVE/REJECT/FLAG) and `src/schemas/eval_case.py:38-43` (pass/fail/skipped). There is no RETRY or ESCALATE verdict. Pipeline: only PASS or HOLD (`pipeline:q2c_pipeline.py:4497`). | `WEAKENED` | Without RETRY and ESCALATE, an automatic retry or escalation can never be recorded as a decision. | Keep the vocabulary in the pipeline (Q1). The runtime needs no new verdict until a loop exists. | Not applicable until Q1 is answered. | Y: Q1 |

### 2.2 Unit 1 — Quality standard loader (L81-108)

| ID | Source passage | Intended behaviour | Current carrier | Verdict | Risk | Proposed resolution | Test that would prove it | Decision |
|---|---|---|---|---|---|---|---|---|
| U1 | L83: "Convert the CPAX Standards folder into task-specific quality packets." | Load the doctrine documents relevant to the kind of output being checked. | Pipeline: `load_quality_standards_packet` at `pipeline:q2c_pipeline.py:1071`. The configurable root is at `:117`. Runtime: deliberately none. The North Star calls the doctrine "not runtime dependencies". | `OUT_OF_REPO` | Each document is cut off at 5,000 characters (`:1109`), so later doctrine sections may never reach the checker. | Pipeline-side question. Note it for the pipeline owner. | A packet built from a long doctrine file still contains its final section. | N |
| U1.a | L105: "Missing standards root falls back safely." | A missing standards root never crashes the run. | Pipeline: missing files are skipped (`:1098`). No test covers a missing root. | `OUT_OF_REPO` | A silent skip means a packet can be empty and nobody notices. | Pipeline test. The report should also state "no standards loaded" (it already renders "None loaded."). | Point the loader at a missing root: it returns an empty source list, and the report says so. | N |
| U1.b | L106: "Brand kit still loads from the existing path." | The old brand-kit setting keeps working. | Pipeline: `BRAND_KIT_PATH` kept (`:116`). No dedicated test. | `OUT_OF_REPO` | Low. | Pipeline test. | With the brand-kit variable set, the brand domain packet includes it. | N |
| U1.c | L107: "Fukasawa standards packet includes task depth and non-conformance sections." | The package packet always includes both doctrine documents. | Pipeline: test `test_fukasawa_standards_packet_loads_from_standards_root` (`pipeline:tests/test_contracts.py:255`). | `OUT_OF_REPO` | Low. | None. | Already exists. | N |
| U1.d | L108: "Domain selection returns the expected standards for HTML/tool/package quality." | Each output domain gets its own standards set. | Pipeline: the domains are `package`, `html` and `brand` (`:1075-1092`). There is **no `tool` domain**, and no domain-selection test. | `OUT_OF_REPO` | Tool artifacts get checked against package standards, not tool standards. | Pipeline question. | Asking for the `tool` domain returns the executable-artifact review policy. | N |

### 2.3 Unit 2 — Observation packet and quality finding schema (L110-139)

| ID | Source passage | Intended behaviour | Current carrier | Verdict | Risk | Proposed resolution | Test that would prove it | Decision |
|---|---|---|---|---|---|---|---|---|
| U2 | L112: "Preserve observed evidence separately from inferred meaning." Fields at L123-131. | Each finding records check, artifact, level, observation, inference, confidence, missing evidence, next check and escalation target. | `src/schemas/observation_packet.py:39-91` carries observation, inference, confidence, missing evidence, artifacts and next step. It has **no** `check_id`, `level` or `escalation_target`. Confidence is a bare low/medium/high, with no reason (the doctrine shape is `confidence{level,reason}`). The file is marked draft (`:17`). The only writer is the CLI run loop (`src/cli.py:287`). | `WEAKENED` | **This disagrees with the map**, whose §2 row says "Structure matches" (`CARRIED`). The map compared against the doctrine's packet. Measured against this plan and the doctrine's `escalation{next_layer,requested_checks}`, three fields are missing. Recorded here, not resolved. | Add the missing fields as optional, defaulted additions when the draft status is reviewed. `ObservationPacket` is not in the exported JSON Schema list (`src/schemas/export_jsonschema.py:51-61`), so no published contract changes. | An observation with an escalation target round-trips through the ledger and appears in `history`. Old rows still load. | Y: Q5 |
| U2.1 | L133: "Store quality findings alongside `RUN_FAILURES`, but keep them separate from runtime failures." | Quality findings and crashes are recorded separately. | Pipeline: findings live in the quality report, and failures in `RUN_FAILURES` (`:37`, `:724`). Runtime analogue: `ExecutionStatus` keeps "harness broke" apart from "work failed" (`src/schemas/eval_case.py:46-62`). | `OUT_OF_REPO` | Low. | None. | Already exists in both repos, in different forms. | N |
| U2.a | L137: "Deterministic HTML blocker creates an observation packet, not only a string." | Each HTML blocker becomes its own structured finding. | Pipeline: the blockers are joined into one string per file (`build_file_inventory`, `:4384`), then wrapped as a single `artifact_release_hold` finding. The individual blockers stay strings. | `OUT_OF_REPO` | You cannot count which blocker kind recurs, and recurrence is the input to capability lift. | Pipeline: one finding per blocker. | A file with two placeholder links and a pending-QC marker yields three findings with distinct check ids. | N |
| U2.b | L138: "Empty editor desk output records direct evidence and a bounded inference." | A blank editor report becomes a finding with separate observation and inference. | Pipeline: `editor_desk_nonempty` finding. Asserted by `pipeline:tests/test_contracts.py:272`. | `OUT_OF_REPO` | Low. | None. | Already exists. | N |
| U2.c | L139: "Missing tool functionality records missing evidence instead of claiming final root cause." | The finding says what is unknown instead of guessing a cause. | Pipeline: `quality_finding` **always** writes `missing_evidence: []` and `level: 1` (`:4409-4421`). The runtime's packet requires missing evidence (`observation_packet.py:77-83`), but the pipeline does not use it. | `OUT_OF_REPO` | Every pipeline finding claims nothing is missing, which is the exact failure this unit exists to prevent. | Pipeline: pass the missing evidence through. | A tool-candidate finding lists "no evidence the tool computes a result". | N |

### 2.4 Unit 3 — Whole-package quality gate (L141-171)

| ID | Source passage | Intended behaviour | Current carrier | Verdict | Risk | Proposed resolution | Test that would prove it | Decision |
|---|---|---|---|---|---|---|---|---|
| U3 | L143: "Evaluate the complete publish package, not individual HTML files only." | A gate runs after the deploy bundle is staged and judges the whole package. | Pipeline: `build_package_quality_report` (`:4431`), written into the bundle at `:4715`. Runtime analogue for workflows: promotion refuses unresolved blocking findings (`src/governance/workflow_promotion.py:292-300`). | `OUT_OF_REPO` | Low for the gate itself. The sub-rows carry the risk. | None. | `pipeline:tests/test_contracts.py:343` | N |
| U3.1 | L156-158: "Final editorial exists and is non-empty." / "Editor desk is non-empty or logged as a blocker." / "Failure logs are present…" | Three presence checks. | Pipeline: `final_editorial_nonempty`, `editor_desk_nonempty` and `run_failures_present` findings. The failure-log copy is tested at `tests/test_contracts.py:190`. | `OUT_OF_REPO` | Low. | None. | Already exists. | N |
| U3.2 | L159: "Files listed as publishable do not contain pending-QC markers." | A pending-QC file is never listed as publishable. | Pipeline: `html_release_blockers` (`:1309`). Tested at `tests/test_contracts.py:222`. | `OUT_OF_REPO` | Low. | None. | Already exists. | N |
| U3.3 | L160: "Tool promises in article/deploy notes match an actual working tool artifact." | If the article promises a tool, a working tool must exist. | Pipeline: a file *named* as a tool must contain inputs and a script (`:1324-1326`). Nothing checks the **article text** for a tool promise when no tool file exists. | `OUT_OF_REPO` | An article can promise a calculator that is not there, and the package can still PASS. | Pipeline: add a promise-versus-inventory check. | See U3.b. | N |
| U3.4 | L161: "Visual support contains no placeholder images or dead CTAs." | No placeholder images and no `href="#"` links. | Pipeline: `:1317-1320`, tested at `tests/test_contracts.py:206`. | `OUT_OF_REPO` | Low. | None. | Already exists. | N |
| U3.5 | L162: "Duath/Angela PASS cannot override deterministic blockers." Also the source guide's lead example: "Angela PASS must never override a placeholder blocker". | Model judgment can never clear a rule-based blocker. | **General rule, runtime:** a blocking finding cannot be waived (`src/governance/workflow_promotion.py:153-157`, tested at `tests/test_workflow_cli.py:696`). Eval scores are advisory only (`src/schemas/eval_case.py:199-206`). **Q2C instance, pipeline:** the package verdict takes no Angela input at all (`:4431` signature), so the rule holds by construction. But **no test includes an Angela PASS**. | `CARRIED` | A later edit that passes Angela's verdict into the report could break the rule silently. Nothing would fail. | Pipeline: add the explicit regression test. Runtime: none. | A package with Angela `pass_fail: PASS` and a placeholder-link HTML file gets `HOLD`. This is the mutation check: feeding the verdict in must turn the test red. | Y: Q8 |
| U3.6 | L163: "Delivery notes cannot recommend publish for held artifacts." Source guide: "publish notes cannot authorize held artifacts". | Generated deploy notes never list a held file as publishable. | Pipeline: the *fallback* notes exclude held files (`fallback_local_deploy_notes`, `:4555`, tested at `:222`). **Model-written notes are not checked** against the hold list. | `OUT_OF_REPO` | The normal path, model-written notes, can still recommend publishing a held file. | Pipeline: reconcile any notes against the inventory after they are generated. | Model-written notes naming a held file produce a blocking finding. | Y: Q8 |
| U3.7 | L164: "Output a `quality-report.json` and `quality-report.md` in the deploy bundle." | Two report files in the bundle. | Pipeline: `:4715` onward, tested at `tests/test_contracts.py:343`. | `OUT_OF_REPO` | Low. | None. | Already exists. | N |
| U3.a | L168: "A package with Angela PASS and placeholder HTML receives `HOLD`." | Acceptance example. | Pipeline: no test with an Angela PASS. The closest is `:272` (pending-QC only). | `OUT_OF_REPO` | See U3.5. | See U3.5. | See U3.5. | Y: Q8 |
| U3.b | L169: "A package with a missing tool but article tool promise receives `RETRY` or `HOLD`." Source guide: "a claimed tool needs working code". | Acceptance example. | Pipeline: absent. There is no RETRY verdict and no promise check. | `OUT_OF_REPO` | See U3.3. | See U3.3. | An article saying "use the calculator below", with no tool file, gets HOLD. | Y: Q8 |
| U3.c | L170: "A package with pending-QC HTML is excluded from publish list." | Acceptance example. | Pipeline: `tests/test_contracts.py:222`. | `OUT_OF_REPO` | Low. | None. | Already exists. | N |
| U3.d | L171: "A clean package can receive `PASS`." | Acceptance example: the gate is not stuck on HOLD. | Pipeline: the code can return PASS (`:4497`), but **no test proves it**. Both bundle tests assert HOLD (`:343`, `:378`). | `OUT_OF_REPO` | A gate that always says HOLD is indistinguishable from a gate that works. | Pipeline: add a clean-package fixture. | A clean package with a non-empty editor report and no failures gets PASS. | Y: Q8 |

### 2.5 Unit 4 — Corrective action planner (L173-203)

| ID | Source passage | Intended behaviour | Current carrier | Verdict | Risk | Proposed resolution | Test that would prove it | Decision |
|---|---|---|---|---|---|---|---|---|
| U4 | L175: "Convert quality findings into a bounded retry plan." Nine action classes at L186-194. | Each finding maps to one corrective-action class from a closed list. | Runtime: `NonConformanceRecord.resolution_note` is free text (`src/schemas/non_conformance.py:167-170`). ADR-010 (proposed) types `remediation` on validator findings only. Pipeline at `c49a5cb`: none. The working copy has uncommitted free-text corrective actions (`synthesize_quality_response`). | `DEFERRED` | **Two different nine-item lists.** The plan's corrective classes (L186-194) are not the doctrine's preventive actions (NCIO §8). The plan's list includes three kinds of escalation; §8 has none. Nothing records which list governs. | Section 3, priority 2. Keep the two lists apart: the plan's list for the *immediate fix*, §8 for *preventing recurrence*. | A resolved non-conformance names one corrective class and one preventive class, each from its own closed list. | Y: Q3 |
| U4.1 | L195: "Prefer reduction before addition, following Fukasawa non-conformance doctrine." | Removing or simplifying is chosen before adding process. | Prose only: the help text and docstring of `nonconformance resolve` (`src/cli.py:2082-2097`). The `learning_log.md` template keeps 6 of the 9 §8 actions (map §4, §8 row). The template's generator is FROZEN. | `WEAKENED` | The preference cannot be counted, so it cannot be enforced or audited. | Priority 2: an ordered, closed preventive-action list. Choosing "add process" requires a stated reason why reduction was not enough. | Resolving with "add process" and no reason is refused. Resolving with "remove step" is accepted. | Y: Q3 |
| U4.2 | L196: "Emit a per-loop `corrective-action.json` that lists intended changes, target artifacts, and measurement criteria." | One file per loop. | Pipeline: absent. | `OUT_OF_REPO` | No record of what each retry tried. | Pipeline question, tied to Q1. | Not applicable here. | Y: Q1 |
| U4.a | L200: "Placeholder link maps to remove/replace CTA, not broad rewrite." | Acceptance example: the smallest fix wins. | Pipeline: absent at `c49a5cb`. | `OUT_OF_REPO` | Retries regenerate whole articles for a one-link defect. That costs more and risks new defects. | **A strong candidate for the #27 first case.** It is repeatable, deterministic and cheap to measure. | A placeholder-link finding yields the action "replace link", targeting that one file. | Y: Q1 |
| U4.b | L201: "Fake calculator maps to regenerate tool or remove tool promise." | Acceptance example. | Pipeline: absent. | `OUT_OF_REPO` | See U3.3. | Pipeline. | A fake-tool finding yields one of exactly two actions. | N |
| U4.c | L202: "Repeated blank model output maps to model escalation after local retries." | Acceptance example. | Pipeline: absent. Angela gets one revision pass (`qa_needs_revision`, `:2123`). There is no escalation. | `OUT_OF_REPO` | Blank output gets accepted through a fallback with no escalation on record. | Pipeline, tied to Q6. | Not applicable here. | Y: Q6 |
| U4.d | L203: "Ambiguous standard maps to human escalation, not infinite model retries." Source guide: "ambiguity escalates to humans". | When the standard is unclear, a person decides. Do not keep retrying. | Runtime, partial: unknown step facts push the executor choice toward a human (`src/governance/cooperation.py:99`, the `NOT_READY_FOR_AUTOMATION` class at `src/schemas/cooperation.py:59-70`). The ambiguous-terms rule HW-014 is advisory, not blocking (`src/governance/workflow_rules.py:1012-1022`). Nothing detects that a **quality standard** is ambiguous. | `WEAKENED` | Unclear criteria can pass validation with only a warning. | No runtime change proposed for #27. If the #27 case hits an unclear standard, record a non-conformance and escalate by hand. | A workflow whose completion criterion is "looks good" cannot be exported without a human-owned gate. | N |

### 2.6 Unit 5 — Three-loop retry state (L205-235)

| ID | Source passage | Intended behaviour | Current carrier | Verdict | Risk | Proposed resolution | Test that would prove it | Decision |
|---|---|---|---|---|---|---|---|---|
| U5 | L225: "Run up to three local corrective loops." Loop fields at L218-224. | A recorded loop state (index, target, quality before and after, change, decision), capped at three. | Runtime: `RetryPolicy` retries *adapter crashes* only, with no before/after record (`src/schemas/graph.py:39-47`, FROZEN; `src/kernel/kernel.py:209-222`, FROZEN). Missing evidence is retryable by hand (`src/runtime/state_machine.py:159`). Pipeline: one Angela revision pass (`:2123`). There are no loop records. | `OUT_OF_REPO` | The North Star calls three loops "a Q2C pilot policy, not a universal retry rule". If it were built into the runtime, it would become universal. | Keep it in the pipeline (Q6). | Not applicable here. | Y: Q6 |
| U5.a | L232: "Passing after loop 1 stops further loops." | Acceptance example. | Pipeline: absent. | `OUT_OF_REPO` | n/a | Pipeline. | n/a | Y: Q6 |
| U5.b | L233: "Three failed loops trigger enterprise escalation." | Acceptance example. | Pipeline: absent. | `OUT_OF_REPO` | n/a | Pipeline. | n/a | Y: Q6 |
| U5.c | L234: "Enterprise failure triggers human escalation." | Acceptance example. | Pipeline: absent. | `OUT_OF_REPO` | n/a | Pipeline. | n/a | Y: Q6 |
| U5.d | L235: "Each loop writes measurement evidence." | Every attempt records quality before and after. That record is the evidence that a correction worked. | None. ADR-008 (proposed) defines a baseline-versus-treatment comparison. Runtime eval results can reference external evidence (`src/schemas/eval_case.py:191-210`). | `DEFERRED` | Without before/after records, "the fix worked" cannot be shown. The North Star's first-milestone definition of done requires that evidence. | Priority 3. For the #27 case, run the same eval cases on baseline and candidate, and record both result sets. | Two eval result sets for the same cases, one per arm, both in the ledger and both cited by the migration record. | Y: Q4 |

### 2.7 Unit 6 — Non-conformance improvement log (L237-269)

| ID | Source passage | Intended behaviour | Current carrier | Verdict | Risk | Proposed resolution | Test that would prove it | Decision |
|---|---|---|---|---|---|---|---|---|
| U6 | L239: "Make every failure a process improvement opportunity." Ten-section template at L252-261. | A durable record with all ten doctrine sections: summary, expected, actual, complexity-first review, simplification, root cause, corrective, preventive, process update, verification. | `src/schemas/non_conformance.py:137-170`: `kind`, `note` and `resolution_note`. Map Losses §1 and §4 trace each section. | `WEAKENED` | This is the map's "single largest doctrinal loss". | Section 3, priority 2. | Section 3, priority 2. | Y: Q3 |
| U6.1 | L262: "Include this in the deploy package and production handoff." | The record travels with the package. | Pipeline: absent. | `OUT_OF_REPO` | n/a | Pipeline. | n/a | N |
| U6.a | L266: "Failed package writes non-conformance artifact." | Every failure produces a record. | Runtime: records are written automatically only for state-machine breaches (`src/runtime/state_machine.py:491-508`). Failed evals produce *candidates* only (`src/schemas/eval_case.py:211-217`), by design. Humans capture the rest (`src/cli.py:2052`). | `WEAKENED` | This is a deliberate narrowing: a failed check is evidence, not a breach. It is right for evals, but it means quality failures depend on someone remembering to capture them. | No change. Record it as chosen. For #27, capture the defect by hand. | n/a | N |
| U6.b | L267: "Artifact records complexity-first review." Doctrine (NCIO §4): "Assume excess complexity is the root cause until disproven." | Every record states which complexity signals were present, and a root-cause verdict: confirmed, contributing, or ruled out. | None. Map §4, rows §4 and §6. | `DROPPED` | Product principle 9 says "first ask", which assigns no burden of proof. The doctrine's three-way verdict is the only mechanism that does. | Priority 2. | A record cannot be resolved without a root-cause verdict and evidence. | Y: Q3 |
| U6.c | L268: "Preventive action is present and specific." | A preventive action from the closed §8 list, plus a named process update (§9) and a verification plan (§10). | None on the runtime path. ADR-010 proposes the §8 list for validator findings only (map Losses §1). | `DROPPED` | The loop that NCIO exists to close stays open. Nothing links a failure to the workflow file it should change. | Priority 2. | Resolving requires a §8 action, a named target (workflow, contract or checklist), and a "how we will know" statement. | Y: Q3 |
| U6.d | L269: "Clean package does not create a false non-conformance." | No records without a breach. | Runtime: records are created only on refusal paths (`state_machine.py:491-508`). Eval failures file no records (`tests/test_smevals_adapter.py:459`). | `CARRIED` | Low. | None. | Already exists. | N |

### 2.8 Unit 7 — Capability lift and process capsules (L271-297)

| ID | Source passage | Intended behaviour | Current carrier | Verdict | Risk | Proposed resolution | Test that would prove it | Decision |
|---|---|---|---|---|---|---|---|---|
| U7 | L290: "Mark capsules `draft`, `tested`, or `validated`." | Transferable capsules for stable checks, with a maturity marker. | `AgentCapsuleContract` (`src/schemas/agent_package.py:110-166`) with the `Maturity` draft/tested/validated ladder (`:30-39`). Promotion is gated by evidence (`src/governance/maturity.py:102-190`). **The name collides** with the runtime's `ProcessCapsule`, a unit of work in progress (`src/schemas/process_capsule.py:41-87`). See map Losses §2. | `CARRIED` | Sentences like "promote the capsule" are ambiguous. The North Star asks for the two to be told apart without a destructive migration. | Naming decision only (Q9). No code rename. | n/a | Y: Q9 |
| U7.1 | L285-289: starter capsules: "HTML publishability gate", "Tool reality check", "Deploy notes publish/hold reconciliation", "Failure log inclusion". | Four Q2C capsules. | Pipeline: absent. There is no `docs/process-capsules/`. | `OUT_OF_REPO` | n/a | The first one could be the #27 case's output (priority 3). | n/a | Y: Q1 |
| U7.2 | L291: "Promote a correction downward only after evidence shows it is stable." Doctrine: "Standardized tasks should migrate downward. Reliable agents should move upward." | Move a task from reasoning to a rule, checklist or script, with evidence, and free up the agent that used to do it. | None. Maturity moves **up** only. The one downward hook is a **free-text** `--rationale` required for tested→validated (`src/governance/maturity.py:303-307`). Any wording satisfies it. Map §2, "Capability Lift" row. | `DROPPED` | This is the half of capability lift that raises the base intelligence of the organisation, and the half the North Star says is absent. | Section 3, priority 3. | Section 3, priority 3. | Y: Q4 |
| U7.a | L295: "Process capsule files validate required fields." | Acceptance example. | `AgentCapsuleContract` validators (`agent_package.py:146-166`) and `src/foundry/validator.py`. | `CARRIED` | Low. | None. | Already exists. | N |
| U7.b | L296: "Validated capsules can be listed in the quality report." | Acceptance example. | Pipeline: absent. | `OUT_OF_REPO` | n/a | Pipeline. | n/a | N |
| U7.c | L297: "Draft capsules are not treated as authoritative gates unless explicitly configured." | Acceptance example: only proven capsules gate work. | Runtime: generated packages always start as draft (`agent_package.py:122-125`), and promotion needs a named human (`maturity.py:292-296`). But no capsule acts as a gate at **any** maturity, so the rule holds only because nothing is ever a gate. | `WEAKENED` | Once a capsule becomes a rule (priority 3), the "unless explicitly configured" switch will be needed and does not exist. | Part of priority 3: a migration can only go live from an approved state. | A draft-status migrated rule runs in shadow mode only. Its findings are recorded and block nothing. | Y: Q4 |

### 2.9 Escalation, measurement, telemetry and rollout (L299-446)

| ID | Source passage | Intended behaviour | Current carrier | Verdict | Risk | Proposed resolution | Test that would prove it | Decision |
|---|---|---|---|---|---|---|---|---|
| E1 | L308: "Trigger when local loops fail but the standard is clear." Required prompt contents at L310-315. | Enterprise retry with a full context packet. | Pipeline: absent. The words appear in uncommitted corrective-action text only. Runtime: no model tiers (ADR-009 notes the `src/kernel/*` freeze). | `OUT_OF_REPO` | n/a | Tied to Q6. | n/a | Y: Q6 |
| E2 | L319-324: human escalation when "quality standard is ambiguous", "legal/medical/financial risk appears", and similar triggers. | Five named triggers send work to a person. | Runtime: CONSCIOUS depth opens a human gate (`src/runtime/review_gate.py:37-78`). Risk, irreversibility and data-sensitivity floors cap autonomy and only ever tighten (`src/governance/cooperation.py:65-69`, tested at `tests/test_cooperation.py:146`). The "standard ambiguous", "needs current fact check" and "contested decision" triggers have no carrier. | `WEAKENED` | Covers risk-shaped triggers, not uncertainty-shaped ones. | No change for #27. | n/a | N |
| M1 | L330: "KPIs are indicators for leadership attention, not binary commands for worker behavior." | No metric automatically drives a decision. | Scores are advisory (`src/schemas/eval_case.py:199-206`). The smevals adapter "never… treat[s] a numeric score as a verdict" (`src/governance/smevals_adapter.py:31-33`). | `CARRIED` | Low. | None. | Already exists. | N |
| M2 | L336: "Quality reports visible to workers and operators should include:" nine items. | Blocker count, unresolved count, loops to pass, fallbacks, package and artifact verdicts, manual changes, recurring categories, capsules promoted. | Pipeline: the blocker, unresolved and fallback counts plus verdicts (`:4505-4509`). Loops, manual changes, recurrence and capsules promoted are missing. | `OUT_OF_REPO` | "Manual changes required after run" is the operator-burden signal, and it is missing. | Pipeline. For #27, record manual cleanup time by hand (Q7). | n/a | Y: Q7 |
| M3 | L368: "This KPI is private. It should be used by owners or governance review, not exposed to worker agents as a success target." | Token cost per package, loop and artifact; enterprise/local mix; engagement per token. All private. | Runtime: none. Pipeline: placeholder fields, all `None`, marked `internal_only` (`:4510-4516`). | `DROPPED` | The North Star's first-milestone definition of done requires "benchmarked human time + token cost". There is nowhere to put either. | Q7: record them for the #27 case without touching FROZEN kernel files. | The #27 case record shows tokens and minutes for both arms. | Y: Q7 |
| M4 | L377: "recording whether extra reasoning changed the output in a way humans can identify" | Metric-quality discipline. | None. | `DROPPED` | Depends on M3. | Revisit after M3. | n/a | N |
| T1 | L391: "capability-lift signals showing which work migrated from orchestrator reasoning to worker agents, deterministic checks, or process capsules" | A leadership-only Mission Control panel. | Absent. Neither Mission Control nor this runtime has it. | `OUT_OF_REPO` | The capability-lift signal has no producer here either (U7.2). | Priority 3 makes this runtime the producer. The panel stays out of scope. | n/a | N |
| T2 | L419: "If private token usage rises without better engagement, the workflow may have accumulated complexity debt and should trigger a Fukasawa non-conformance review." | Cost drift becomes a non-conformance trigger. | None. | `DROPPED` | Depends on M3. | Revisit after M3. | n/a | N |
| R1 | L435: "The first version should not auto-publish or auto-delete anything." Source guide: "Pilot does not auto-publish or auto-delete". | No unattended publish or delete. | Runtime: no publish or deploy machinery (approved ADR-005, revision 2). The ledger is append-only and enforced by database triggers (`src/runtime/ledger.py:53-70`). Promotion always needs a named human (`maturity.py:292-296`). Pipeline: no publish call found. The only delete removes a half-copied file after a failed copy, and it is logged. | `CARRIED` | Low. | Keep as a release condition for any #27 work. | Existing ledger trigger tests. | N |
| R2 | L439-442: "retry only within safe generated artifacts", "hold when uncertain", "preserve all failure evidence", "produce a better task definition for the next loop" | Four rollout behaviours. | Evidence is preserved (append-only ledger). "Hold when uncertain" maps to `NOT_READY_FOR_AUTOMATION`. "Better task definition" has no carrier: nothing turns a resolved failure into an edited workflow (map §4, §9 row). | `WEAKENED` | The improvement step does not feed back into the workflow. | Priority 2 (NCIO §9, "process update needed"). | A resolved record names the workflow version it changed, and that version exists in the ledger. | Y: Q3 |
| R3 | L444: "Automation can expand only after the quality reports show stable improvement and reduced human cleanup." | Expansion needs outcome evidence, not just process conformance. | Promotion needs *process* evidence (runs, evals, no open records; `maturity.py:102-190`). There is no outcome or cleanup evidence. ADR-008 (proposed) adds outcome evidence. | `WEAKENED` | Something can be promoted that conforms but does not help. | Priority 3 requires both arms of evidence for a downward migration. | See priority 3. | Y: Q4 |
| S1 | L423: "Document the `quality-orchestrator` contract." | The first sequencing step. | Pipeline: `docs/contracts/quality-orchestrator.md` **does not exist**. The plan's L88, L118 and later references point at a missing file. | `OUT_OF_REPO` | The pipeline's quality report has no written contract to test against. | Pipeline question. | n/a | N |

### 2.10 Verdict counts

| Verdict | Rows |
|---|---|
| `CARRIED` | 6: U3.5, U6.d, U7, U7.a, M1, R1 |
| `WEAKENED` | 11: F3, F5, U2, U4.1, U4.d, U6, U6.a, U7.c, E2, R2, R3 |
| `DROPPED` | 6: U6.b, U6.c, U7.2, M3, M4, T2 |
| `DEFERRED` | 4: F1, F4, U4, U5.d (each names a proposed, unapproved ADR) |
| `OUT_OF_REPO` | 36: F2, U1, U1.a-d, U2.1, U2.a-c, U3, U3.1-U3.4, U3.6, U3.7, U3.a-d, U4.2, U4.a-c, U5, U5.a-c, U6.1, U7.1, U7.b, E1, M2, T1, S1 |
| **Total** | **63** |

Of the 36 `OUT_OF_REPO` rows, the pipeline at `c49a5cb` fully carries 9 (U1.c, U2.1, U2.b, U3, U3.1, U3.2, U3.4, U3.7, U3.c) and partly carries 4 (U1.a, U1.b, U3.3, U3.6). The other 23 are absent there.

---

## 3. Priority gaps named by issue #27

These three are the gaps the issue names. Each option below is written as an ADR would be, and none is approved. Options are additive and backward compatible unless marked **needs migration**. Frozen files (`src/schemas/graph.py`, `src/schemas/bundle.py`, `src/kernel/*`, `src/security/*`, `src/foundry/generator.py`, `src/runtime/state_machine.py`) are not touched by any recommended option.

"#27's single case" means the North Star's M1: one repeatable Q2C publish defect, run through baseline → narrower rule → independent clean and adversarial tests → approval → shadow mode.

### 3.1 Priority 1 — Full complexity budget

**Gap.** Doctrine has 10 inputs (skill, hardware, RAM/VRAM, maintenance tolerance, time, privacy, criticality, desired autonomy, network topology, sustainability) and 6 outputs. None of them is carried (F1; map §1 and Losses §3). The doctrine's own Workflow Design Brief carries a four-field subset. The superseded July-18 spec had it, and it was lost at the step from spec to schema.

**Overlap with ADR-009 (proposed).** ADR-009 recovers one slice: model capability as a limit on step complexity. It does this with a model-swap matrix run through the ADR-008 harness, and it needs tier declarations that it says must avoid the frozen kernel. **For #27's single case, the matrix is not needed.** One defect replaced by one rule can be compared baseline against candidate on a fixed model. What #27 does need is the *budget statement itself*: how much operator time and maintenance the owner will tolerate for this workflow. That statement is what tells you whether the proposed rule is "simpler" in the sense that matters. ADR-009's main idea, "the lowest tier that reliably passes is the step's complexity score", stays useful later (M3).

| Option | What it is | Trade-offs |
|---|---|---|
| **1A. Optional budget block on the workflow draft** | Add an optional `complexity_budget` to `HumanWorkflowDraft` (`src/schemas/human_workflow.py:407`). All 10 inputs are plain values defaulting to "not stated". There is also one free `reasoning` field and the six outputs as human-written statements. A new **advisory** rule (next free ID, HW-017, non-blocking) fires when an automation-bound workflow states no budget. "Available hardware" may cite recorded computers by name from the node store. | **Pro:** the budget sits where the workflow is designed and validated. It is visible at the point of decision. It costs one optional field and one advisory rule. **Con:** `HumanWorkflowDraft` is an exported JSON Schema contract (`export_jsonschema.py:52`), so its golden schema file changes. That is an additive change under ADR-002, not a migration. Outputs are human-written, so nothing checks them. |
| **1B. Separate budget file per workflow** | A `complexity-budget.yaml` beside the draft, with its own small schema and a `workflow budget` command to validate and show it. No existing contract changes. | **Pro:** zero change to any existing contract. Easy to drop. **Con:** a second source of truth that can drift from the draft, which is exactly what ADR-010 rejects for teaching text. Validation and promotion never see it, so it does not change any decision. |
| **1C. Budget decision table** | Like the cooperation table: a published table computing the six outputs from the ten inputs. | **Pro:** this is what the doctrine describes: outputs derived, not asserted. **Con:** there is no labelled evidence for the thresholds. Writing them now would *invent* doctrine. Premature under "validate before scaling". |

**Recommendation: 1A**, inputs and reasoning only, with human-written outputs. 1C is deferred until at least two worked cases (M2) give evidence for thresholds. For #27, fill the budget for the one Q2C workflow by hand before the case begins. The budget becomes the yardstick that decides whether the candidate rule really is simpler.

### 3.2 Priority 2 — Structured non-conformance diagnosis

**Gap.** NCIO is a ten-section instrument. The runtime record keeps `kind`, `note` and `resolution_note` (U6, U6.b, U6.c; map Losses §1). The parts that carry the doctrine are all missing: the presumption that complexity is guilty, the three-valued root-cause verdict (§6), the closed and ordered preventive actions (§8), the process-update link (§9) and verification (§10). There is a further fact the map does not mention: **`non_conformance_records` is not an append-only table.** It is upserted in place (`src/runtime/ledger.py:53-62`, `:602-621`), so any diagnosis written onto the record can be overwritten without trace.

**Overlap with ADR-010 (proposed).** ADR-010 adopts the §5 questions and the §8 actions verbatim, but places them on validator rules and findings, not on the runtime record (map Losses §1). **For #27's single case, what ADR-010 offers that is needed is the vocabularies.** The same eight questions and nine actions, as closed lists, should be shared so the two paths never diverge. What is *not* needed for #27 is ADR-010's change to the exported `WorkflowFinding` contract, the rule-registry completeness test, or the regenerated rule catalogue. The #27 defect is a run failure, not a validator finding.

| Option | What it is | Trade-offs |
|---|---|---|
| **2A. Optional diagnosis fields on the existing record** | Add defaulted fields to `NonConformanceRecord`: complexity signals (closed list of the 10 from §4), simplification answers (the 8 questions from §5), root-cause verdict (confirmed / contributing / ruled out / not yet assessed), evidence, corrective class, preventive action (closed, ordered list of the 9 from §8), process-update target and verification plan. `nonconformance resolve` requires a verdict and evidence. Choosing "add process" requires a reason why reduction was not enough. | **Pro:** smallest change. The record is not an exported contract (`export_jsonschema.py:51-61`), and old rows load with defaults. The frozen `state_machine.py` keeps creating records unchanged, and diagnosis happens later. **Con:** the diagnosis lives on a record that is overwritten in place, so a revised diagnosis erases the first one. Making `resolve` stricter **changes CLI behaviour**: old scripts that resolve with only a note would be refused. |
| **2B. Append-only diagnosis record linked to the existing one** | A new `NonConformanceDiagnosis` (the same fields as 2A) in a new **append-only** ledger table, linked by record id. A record can only be resolved if it has at least one diagnosis. The latest diagnosis is current, and earlier ones remain. | **Pro:** fits the ledger's own rule that evidence a decision was made on is immutable (`ledger.py:47-52`). Keeps diagnosis history, which matters when a "ruled out" verdict is later overturned. The existing record is untouched. **Con:** one new table and one new model to read. The same CLI strictness change as 2A. |
| **2C. Complete the generated `learning_log.md` template** | Restore the missing signals and actions in the template only. | **Pro:** no schema change. **Con:** `src/foundry/generator.py` is FROZEN. It stays prose that no test can hold to the source, which is the map's exact complaint. Rejected. |

**Recommendation: 2B**, with the two closed vocabularies (§5 and §8) defined once and shared with ADR-010 if it is later approved. The CLI strictness change should apply only to records opened after the change ships. Legacy records can still be resolved the old way and are marked "diagnosis: legacy, not assessed". That avoids a migration. For #27: the defect is captured by hand as a non-conformance, then diagnosed with 2B, and the diagnosis must name "move task downward" (or explain why not). That is what connects this priority to priority 3.

The plan and the doctrine have **two different nine-item lists** (U4). The plan's list (L186-194) mixes fixes with escalations. NCIO §8 is about prevention. 2B keeps both, as separate fields. Q3 asks the owner to confirm this.

### 3.3 Priority 3 — Demonstrated downward capability migration

**Gap.** Maturity promotion moves agents **up** on evidence. Nothing moves a **task down** a reasoning level with evidence, and nothing frees the agent that used to do it (U7.2; map §2, "Capability Lift" row). The only hook is a free-text rationale that any wording satisfies (`maturity.py:303-307`). The North Star's M1 definition of done asks for: a real before/after artifact, a fixed eval dataset, rejected unsafe candidates, an approved low-depth replacement, a readable trace, benchmarked human time and token cost, and a documented rollback.

**Overlap.**
- **ADR-008 (proposed)** supplies the right experiment shape: hold the model constant, vary the configuration, compare two arms on the same tasks with the same grader. For #27, the *shape* is needed. Adopting smevals is not: the runtime's own eval cases and results (`src/schemas/eval_case.py`) can carry both arms. ADR-008 §2, "evidence, never a gate", also stays as is. The approval is a human decision, informed by the evidence.
- **ADR-009 (proposed)** supplies "lowest reasoning is a viability benchmark". For #27, the candidate is a Level 0 rule replacing a model check. The comparison is rule against model, not across model tiers, so the model-swap matrix is not needed.

| Option | What it is | Trade-offs |
|---|---|---|
| **3A. Migration record with a human-gated lifecycle** | A new append-only `CapabilityMigration` record. It holds the task; from level and to level (for example 3 → 0); the donor (agent) and recipient (rule or capsule); the baseline and candidate eval result ids on one fixed case set, including adversarial cases; the rejected candidates; shadow-run ids; human minutes and tokens per arm; the rollback instruction; and the reviewer. Status moves proposed → shadow → approved → active → rolled back. Approval refuses without both arms, the adversarial cases passing, a stated rollback, and a named human. A rule in `shadow` only records findings (U7.c). | **Pro:** makes downward migration a first-class, auditable event. The maturity ladder is unchanged. Additive: one table, one model, CLI commands. **Con:** the most new surface. Designing it before one real case exists risks fitting it to a guess. |
| **3B. Extend maturity promotion with a "lower depth" path** | Let `promote` lower a package's declared depth when evidence is supplied, and rewrite `process_capsule.yaml` and `SKILL.md`. | **Pro:** reuses existing machinery. **Con:** mixes two axes, maturity (upward) and depth (downward), that ADR-005 kept apart for a similar reason. Lowering the depth of an already-validated package invalidates the evals that validated it. **Needs migration:** existing package files and their recorded eval evidence would have to be re-assessed. |
| **3C. A documented worked case first, schema second** | For #27, record the one migration as a dated case folder holding real artifacts: the baseline outputs, the rule, the fixed clean and adversarial eval cases with results for both arms, the rejected candidates, the shadow-run ledger ids, measured minutes and tokens, the approval, and the rollback steps. The eval results and the non-conformance diagnosis (2B) live in the ledger as usual. Build 3A at M2, shaped by what the case actually needed. | **Pro:** follows "validate before scaling" and `AGENTS.md`'s "do not optimize … before there are examples and metrics". It meets the M1 definition of done with real evidence, and adds no schema that would need migrating later. **Con:** the case is not machine-checked. A reviewer must check it against the definition-of-done list by hand. There is a risk of "closing a gap by wording", which the North Star forbids. It is mitigated only because every claim must cite a ledger id or an artifact. |

**Recommendation: 3C for #27, committing now to 3A at M2.** The case folder must satisfy every item of the M1 definition of done, and each item must cite a file or ledger id. If any item cannot be cited, the case is not done. 3B is not recommended.

---

## 4. Decisions requested from the owner

1. **Where does the #27 loop run?** Should the first improvement case keep the Q2C pipeline as the thing that produces and checks packages, with this runtime only recording the diagnosis, eval evidence and migration? (yes / no; "no" means building pipeline behaviour into this runtime)
2. **Complexity budget:** pick 1A (optional block on the workflow draft plus one advisory rule), 1B (separate file), or 1C (decision table now).
3. **Non-conformance diagnosis:** pick 2A (fields on the existing, overwritable record), 2B (separate append-only diagnosis record), or 2C (template only). Also: confirm that the plan's nine corrective classes (immediate fix) and the doctrine's nine preventive actions (§8, recurrence) stay as two separate lists. (yes / no)
4. **Downward migration:** pick 3A (migration record now), 3B (extend maturity promotion; needs migration), or 3C (documented worked case for #27, then 3A at M2).
5. **Observation packet:** may its draft status be lifted, with the plan's missing fields (check id, level, escalation target, confidence reason) added as optional fields? (yes / no)
6. **Three-loop retry and enterprise escalation:** confirm these stay Q2C pipeline policy and are not built into this runtime. (yes / no)
7. **Cost measurement for #27:** may token counts and human minutes for the case be recorded by hand or by a wrapper outside the frozen kernel files, rather than unfreezing `src/kernel/*`? (yes / no)
8. **Pipeline regression tests:** should the private pipeline get explicit tests for the critical examples it lacks: Angela PASS plus placeholder means HOLD; an article tool promise with no tool means HOLD; model-written notes cannot list held files; a clean package can PASS? (yes / no; this work is in the pipeline repository, not here)
9. **"Process capsule" naming:** approve a documentation-only distinction, with no code rename: "transfer capsule" for `AgentCapsuleContract` and "work capsule" for the runtime `ProcessCapsule`. (yes / no)
