<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Copyright (C) 2026 ConcordiaPax LLC -->

# Source-to-Contract Map

The Phase 0 deliverable that was never written. It traces every concept in the
six Source Inputs named in `README.md` to the contract that carries it,
weakens it, renames it, or dropped it.

**Why this exists.** This repository was commissioned to build executable
infrastructure for a design method that already existed. The method lives in
six documents outside the repo, last edited May 2026 and unchanged since. The
repo's own docs — `docs/product-principles.md`, `docs/architecture.md`,
`docs/schema-reference.md` — are downstream restatements, and several of them
restate the sources inaccurately. **A repo doc is not evidence about the
sources.** When they disagree, the source is the older and more specific
document, and this map records which one the runtime actually implements.

Nothing here changes behavior. This is a reading, not a decision.

## How to read a row

| Verdict | Means |
|---|---|
| `CARRIED` | The concept exists in the runtime with its source meaning intact. |
| `WEAKENED` | It exists, but says materially less than the source did. |
| `RENAMED` | It exists under a different name, or its name was reused for something else. |
| `DROPPED` | No contract, schema, validator, or doc carries it. |
| `DEFERRED` | Dropped, but an accepted or proposed ADR names the recovery path. |

`DROPPED` is not automatically a defect. Several sources describe GPT
conversational behavior that has no runtime referent, and the implementation
directive §4 explicitly forbids building others. The verdict records absence;
the note says whether absence was chosen.

## Source Inputs traced

Primary — the four Fukasawa documents (1,143 lines), which define the method:

1. `../FukasawaGPT/# FukasawaGPT.md` (532)
2. `../FukasawaGPT/Fukasawa_Task_Depth_Framework.md` (455)
3. `../FukasawaGPT/Workflow_Design_Brief.md` (89)
4. `../FukasawaGPT/# Non-Conformance Improvement Opportunit.md` (67)

Secondary — the two build-side documents, traced because `src/schemas/agent_spec.py`
and `src/foundry/generator.py` cite them directly:

5. `../agent_foundry_gpt_builder_brief_v_1 (1).md` (Agent Foundry Brief v2)
6. `../Project_Directory_Standard.md`

---

## Losses that matter

Five findings, ranked by consequence. Everything else is in the tables below.

### 1. The Non-Conformance instrument became two free-text strings

Source 4 is a **ten-section diagnostic instrument**. Its §4 names ten
Complexity Signals; §5 fixes eight simplification questions; §6 demands a
root-cause verdict (*complexity confirmed / contributing / ruled out*) with
evidence; §8 gives a **closed nine-item preventive-action vocabulary, ordered
so that "add process" is last and conditional**.

`src/schemas/non_conformance.py` carries `note: str` and `resolution_note: str`.

One partial carrier exists and is worth naming precisely: the `learning_log.md`
that `src/foundry/generator.py` emits into every agent package reproduces the
NCIO shape as a markdown template. But it keeps three of the ten Complexity
Signals (adding two that are in no source), and it keeps the first six
preventive actions while replacing the last three with a free-text
`- [ ] Other:`. It is generated prose inside a package, not a validated
contract, so no test can hold it to the source.

The ordering in §8 is itself doctrine — *prefer reduction before addition*,
with "add process" last and conditional — and a closed vocabulary makes that
preference countable. The one carrier drops exactly that tail and adds an
escape hatch. This is the single largest doctrinal loss in the repository.

**ADR-010 does not cover this.** ADR-010 correctly cites source 4 and adopts
its §5 and §8 vocabularies, but scopes them to `Rule` and `WorkflowFinding` —
the *validator* path. `NonConformanceRecord` is the *runtime* path, and it is
where the source actually placed this structure. Recovering one without the
other leaves the instrument split across two contracts, one structured and one
not. Nothing currently proposed closes it.

### 2. "Process Capsule" names two different things

Source 2's Process Capsule Standard is a **transfer contract for capability
lift**: `task_name`, `owner_agent`, `maturity`, `inputs`, `steps`,
`known_failures`, `escalation_rules`, `output_schema`. Source 5 restates it
verbatim and makes it a precondition for promotion.

The repo has two carriers:

- `src/schemas/agent_package.py` (`AgentCapsuleContract`, emitted as
  `process_capsule.yaml`) — **this is the source concept.** `CARRIED`.
- `src/schemas/process_capsule.py` (`ProcessCapsule`: `id`, `workflow_id`,
  `state`, `assigned_to`, `status`, `evidence`) — a **runtime execution unit**.
  A different concept wearing the same name.

The second was specified in `CLAUDE.md` Phase 0 Step 2 and built to spec. The
collision is not a coding error; it entered through the instruction set. It
matters because "package the process capsule" and "advance the process capsule"
are now sentences about unrelated objects, and `docs/architecture.md` uses the
term without saying which.

### 3. The Complexity Budget System was dropped between July 18 and the models

Source 1 §"Complexity Budget System" takes ten inputs (user skill level,
available hardware, RAM/VRAM limitations, maintenance tolerance, available
time, privacy requirements, operational criticality, desired autonomy level,
network topology, long-term sustainability) and emits six outputs (recommended
workflow depth, appropriate tooling, architecture recommendations,
maintainability assessment, automation recommendations, escalation path).

It appears in no schema, validator, or runtime path.

The loss is datable. `specs/workflow-brief-schema.md` — the superseded July-18
draft — **carries a `complexity_budget:` block and a `depth_recommendation:`
block**, transcribed from source 3. `src/schemas/workflow_brief.py` carries
neither. So the concept survived the source→spec boundary and was dropped at
the spec→Pydantic boundary, at the point where `specs/*.md` was marked
"Superseded ... historical input, not a contract" (`docs/schema-reference.md`).

`ADR-009` recovers one slice: model capability as a constraint on step
complexity. The other nine inputs and five outputs remain dropped.

### 4. Product principle 9 inverts the burden of proof

| | Statement |
|---|---|
| Source 2 §"Complexity-First Non-Conformance Review" | "**Assume** excess workflow complexity is the likely root cause **until proven otherwise**." |
| Source 4 §4 | "Assume excess complexity is the root cause **until disproven**." |
| `docs/product-principles.md` §9 | "When failure occurs, **first ask** whether the workflow is too complex." |

The sources state a **presumption that assigns burden of proof** — complexity
is guilty until cleared, and source 4 §6 requires the clearing to be recorded
with evidence. Principle 9 states a **suggestion that assigns nothing**. An
operator can satisfy "first ask" by asking and moving on; they cannot satisfy
"until disproven" without producing a finding.

ADR-010 makes the same observation and calls principle 9 "materially" weaker.
This map confirms it against both sources and adds that source 4 §6 supplies
the missing mechanism — a three-valued verdict field, not just stronger prose.

### 5. Fukasawa's Primary Objectives were ordered; product principles are not

Source 1 states four objectives **"in the following order"**: (1) Human
Cognitive Harmony, (2) Operational Effectiveness, (3) Real-World Validation,
(4) Scale After Stability. The ordering is the doctrine — it says operator
cognitive load outranks operational efficiency when they conflict.

`docs/product-principles.md` is a flat list of nine numbered items whose
numbers carry no precedence. Nothing in the repo says what to do when two
principles conflict, and the specific claim that human cognitive health wins is
gone. Source 1's supporting lists (reduce: overload, fragmentation, maintenance
anxiety, invisible complexity, operator fatigue; preserve: clarity, confidence,
understanding, agency, joy, curiosity) appear nowhere.

---

## 1. `# FukasawaGPT.md`

| Source concept | Carrier | Verdict | Note |
|---|---|---|---|
| Identity: humane systems architect; five priorities (clarity over spectacle, maintainability over trendiness, understanding over opacity, elegance over excess, resilience over premature scale) | `README.md` "Product Frame" (partial) | `WEAKENED` | The frame states what the product is *not* (not LangChain, not a prompt manager, not a swarm). The five priority pairs are absent. |
| Philosophical influences: Naoto Fukasawa, Deming, Imai, Igarashi, Sato | — | `DROPPED` | Deming's "rejection of detached metrics" is the ancestor of product principle 6; the lineage is unrecorded. |
| Foundational philosophy: "Complexity is a cost"; "automation should reduce burden, not create dependency"; "the best workflow is often the simplest viable workflow" | principle 9 (partial) | `WEAKENED` | See *Losses* §4. |
| **Primary Objectives, ordered 1–4** | `docs/product-principles.md` (unordered) | `WEAKENED` | See *Losses* §5. |
| Growth and Phase Gates: "contain the risk, not the growth" governs *within* a phase; "validate before scaling" governs *between* phases; the phase gate reconciles them | `WorkflowMaturity` ladder, `src/governance/workflow_promotion.py`, `src/governance/maturity.py` | `CARRIED` | Strongest structural carry in the repo. `promote()` refuses advancement on unmet criteria while placing no ceiling on activity within a maturity level — exactly the two-axis reading. The reconciliation argument itself is not written down in the repo. |
| Core Behavioral Rules (10 MUSTs: expose hidden operational costs, prefer reversible architectures, guide rather than dominate, …) | — | `DROPPED` | "Prefer reversible architectures" survives as an input, not a rule: `Reversibility` in `StepCharacteristics` and the `IRREVERSIBLE` safety floor. |
| NEVER list (12: never create agents solely because AI is available, never automate understanding away from the user, never recommend complexity without justification, …) | cooperation decision table (partial) | `WEAKENED` | The table's conservatism enacts "never create agents solely because AI is available" for step assignment. The other eleven have no carrier. |
| **Complexity Budget System** (10 inputs, 6 outputs) | — | `DEFERRED` (ADR-009, one slice) | See *Losses* §3. |
| User Archetypes: Beginner / Builder / Lab Operator, each with tone and behavior | — | `DROPPED` | Survives only in superseded `specs/workflow-brief-schema.md` as `user_skill_level`. No runtime adapts output to operator skill. |
| Workflow Philosophy, 9-step preferred order (understand intent → map → **reduce complexity** → preserve human touchpoints → identify failure modes → recommend architecture → determine if agents are necessary → automate carefully → validate sustainability) | the lifecycle: draft → validate → promote → assess → export | `WEAKENED` | Steps 1, 2, 4, 5, 7, 8 have lifecycle stages. **Step 3, "reduce unnecessary complexity," has no stage** — the lifecycle moves from mapping straight to validation. Step 9 is ADR-008 territory. |
| "FukasawaGPT treats agents as tools, not ideology" | `assess_step` recommending `HUMAN_ONLY` / `NOT_READY_FOR_AUTOMATION` freely | `CARRIED` | |
| Project Directory Architecture: Pattern A numbered, Pattern B named, selection criteria table, hybrid guidance | `detect_workspace_profile()` (Pattern A only) | `WEAKENED` | Detects the numbered layout, calls it `c-pax`, and calls everything else `generic`. Pattern B, the six-signal selection table, and the hybrid rule are dropped. See §6 for the naming conflict this creates. |
| Relationship to Agent Foundry: Fukasawa produces the Workflow Design Brief; Agent Foundry ingests it; the brief is the formal handoff and is required before Level 3+ builds | `WorkflowBrief` → `generate_packages()` | `RENAMED` | The seam is real and implemented. But `WorkflowBrief` is **not** source 3's Workflow Design Brief — see §3. The Level 3+ threshold is dropped: `generate_packages` requires an approved brief at every level. |
| UX & Visualization Philosophy: topology visualization, node-based orchestration, organic workflow mapping | — | `DROPPED` (chosen) | Directive §7 lists "node canvas" as a §4 non-goal and makes designing for it a stop-and-escalate condition. Deliberate. |
| Quality Doctrine (7: validate before scaling, observable reality matters, maintenance burden is part of quality, operator wellbeing affects operational success, …) | principles 5, 8 (partial) | `WEAKENED` | "Maintenance burden is part of quality" and "operator wellbeing affects operational success" have no carrier. |
| **Human Clause:** "The human operator is not a disposable component of the workflow" | `StepAssignment.human_owner` (`min_length=1`, mandatory on every assignment including fully automated ones) | `CARRIED` | The cleanest source→schema trace in the repo. The docstring's "automation moves the work, never the accountability" is this clause restated. |
| Future Direction (Godot orchestration, ACP ecosystems, network hippocampus…) | — | `DROPPED` (chosen) | Speculative; several are §4 non-goals. |

---

## 2. `Fukasawa_Task_Depth_Framework.md`

| Source concept | Carrier | Verdict | Note |
|---|---|---|---|
| Core Rule: "a workflow should contain the least reasoning required to complete the task safely, consistently, and clearly" | `TaskDepth`, `AgentSpec.depth_level`, cooperation decision table | `CARRIED` | |
| The five pre-agent questions (deterministic rule? checklist or script? simple condition? does it truly require judgment? lowest reliable level?) | `StepCharacteristics` (`judgment_load`, `determinism`, `repeatability`) | `WEAKENED` | The *factors* are captured; the *questions* are asked nowhere. Source 5 makes question 5 a hard gate ("Agent Foundry cannot continue until this is answered"); the repo never asks it — see §5. |
| "If a workflow requires enterprise-level reasoning to operate routinely, the workflow is too complex" | `WorkflowBrief._check_agents_are_consistent` (ROUTINE workflow cannot declare a Level 5 agent); `generate_packages` refuses Level 5 outright | `CARRIED` | Enforced twice, at validation and at build. ADR-009 proposes making it measurable rather than declared. |
| Task Depth Levels 0–5: definitions, behaviors, examples | `AgentSpec.depth_level` (`ge=0, le=5`) with the level names in its description | `CARRIED` | |
| Per-level **output requirements** (L0: result + evidence + error state; L2: observations, classification, confidence, recommended next check, escalation condition; L3: summary, evidence, probable cause, confidence, corrective action, preventive opportunity, escalation target; L4: workflow status, completed checks, blockers, decisions, escalations, next actions, doc updates) | — | `DROPPED` | No schema shapes an agent's output by its declared level. `evals.yaml` checks *schema conformance* against `process_capsule.yaml#output_schema`, but that schema is free-form and unrelated to depth level. A Level 3 agent may emit a Level 0 shape and pass. |
| **Observation Packet Standard** (`observation` / `inference` / `confidence{level,reason}` / `missing_evidence` / `escalation{next_layer,requested_checks}`) | `src/schemas/observation_packet.py` | `CARRIED` | Structure matches. Note: this contract is flagged as a draft pending human review before Phase 2 consumers depend on it. |
| "Bad systems turn observations into conclusions too early" | `ObservationPacket`'s separation of `observation` from `inference` | `CARRIED` | The design rule is enforced by the field split rather than by prose. |
| Shards / Agents / Coordinators / Strategists, each with explicit **can** and **cannot** lists ("a shard cannot invent strategy, redesign the workflow, or make broad business decisions") | `depth_level` 0–5; `AgentSpec.forbidden` (free text) | `WEAKENED` | The ladder is carried as an integer. The per-role prohibitions are not derived from it — `forbidden` is hand-written per agent, so nothing stops a Level 1 spec from omitting "does not synthesize". |
| Capability Lift: "standardized tasks should migrate downward, reliable agents should move upward"; promotion requires evidence, not vibes | `src/governance/maturity.py`, principle 5 | `WEAKENED` | The *upward* half is implemented: `assess()` gates promotion on ledger evidence. The **downward** half — a validated task migrating to a lower-reasoning layer, freeing the donor — has no carrier at all, and it is the half that raises base organizational intelligence. |
| Six promotion criteria (high completion rate, low error rate, stable output format, clear escalation behavior, related-domain overlap, validated process package available) | `maturity.assess()` criteria list | `WEAKENED` | Four carry directly: completion rate (≥3 passing eval cases, then ≥3 complete runs), error rate (no open non-conformance records), escalation behavior (`ESCALATION_CORRECTNESS` coverage), and package availability (`validate_package` clean). **"Stable output format" is only indirect** — `_TESTED_COVERAGE` requires handoff, depth, and escalation checks but not the output-schema-conformance check that source 5 makes mandatory in `evals.yaml`. **"Related-domain overlap" is dropped entirely** — nothing constrains *which* task an agent may inherit, only whether it is mature enough to inherit one. |
| **Process Capsule Standard** | `AgentCapsuleContract` / `process_capsule.yaml` | `CARRIED` / `RENAMED` | See *Losses* §2 — carried faithfully by one contract, and the name reused by an unrelated one. |
| **Complexity-First Non-Conformance Review:** the presumption, ten Complexity Signals, nine ordered corrective actions | principle 9; `NonConformanceRecord` | `WEAKENED` | See *Losses* §1 and §4. The ten signals and nine actions have no carrier anywhere. |
| "A smarter organization is not one with more rules. It is one where fewer routine decisions require higher reasoning." | — | `DROPPED` | This is the framework's thesis sentence. |
| Workflow Generation Checklist (14 items) | the lifecycle | `WEAKENED` | Items 2, 3, 10, 11, 13 map to stages. Item 12 ("look for excess complexity before adding new process") and item 14 ("identify promotion opportunities when reliability is proven") do not. |
| Anti-Patterns (9: calling every task an agent; giving low-level shards broad authority; **allowing agents to improvise when they should escalate**; treating preliminary observations as final diagnoses; designing one large agent; …) | `AgentSpec.escalation_target` (`min_length=1`); `ObservationPacket` | `WEAKENED` | Two are structurally enforced — the escalation field's description quotes this doctrine almost verbatim ("an agent with nowhere to escalate will improvise, and improvisation is non-conformance"). The list as a reviewable artifact is dropped. |

---

## 3. `Workflow_Design_Brief.md`

This document defines the FukasawaGPT → Agent Foundry handoff format. **The
repo's `WorkflowBrief` is a different artifact that inherited the name.**

Source 3 is a *design specification*: intent, complexity budget, depth
recommendation, agents required, handoff checklist. It contains no states and
no transitions. `src/schemas/workflow_brief.py` is a *state-machine
declaration*: states, transitions, owners, evidence, exception path. It
contains no complexity budget and no depth recommendation.

Both are legitimate artifacts. The problem is that `README.md` presents source
3 as an input, `docs/architecture.md` refers to "the brief", and neither says
these are two objects. Phase 5's `workflow-design-brief.yaml` pilot artifact
will make this ambiguity load-bearing unless the two are named apart.

| Source field | Carrier | Verdict | Note |
|---|---|---|---|
| `brief_name`, `date`, `designed_by: FukasawaGPT` | `WorkflowBrief.title` | `WEAKENED` | Authorship and date dropped. `PromotionLineage` records `promoted_by`/`promoted_at` for the promotion path only. |
| `status: draft \| reviewed \| approved` | `BriefStatus` | `CARRIED` | Exact enum, and `generate_packages` enforces `approved` before any build. |
| `workflow_intent: {goal, trigger, outcome_definition}` | `HumanWorkflowDraft.purpose` / `.trigger` / `.claimed_outcome`; `WorkflowBrief.completion_criteria` | `CARRIED` | Renamed but intact, and strengthened: HW-001 and HW-002 make trigger and outcome blocking. |
| `complexity_budget: {user_skill_level, available_hardware, maintenance_tolerance, desired_autonomy}` | — | `DEFERRED` (ADR-009, partial) | See *Losses* §3. |
| `depth_recommendation: {coordinator_level, shard_levels, reasoning}` | `WorkflowBrief.task_depth` + per-agent `depth_level` | `WEAKENED` | The coordinator/shard split is gone — the repo has one flat workflow depth plus per-agent levels, with no notion of *which* agent coordinates. **`reasoning` is dropped**: nothing records *why* a depth was chosen, which is the field that would make a depth decision reviewable. |
| `agents_required[].{agent_name, depth_level, responsibilities, escalation_target}` | `AgentSpec` | `CARRIED` | Field-for-field. |
| `agents_required[].{inputs, outputs}` | — | `DROPPED` | `AgentSpec` has no per-agent input or output declaration. Contract data lives on `WorkflowStep` and `StepAssignment` instead, which is defensible, but nothing ties an agent to its own I/O contract at the spec level. |
| `handoff_checklist` (7 items, including "complexity budget evaluated" and "process capsule template identified for each agent") | validators (partial) | `WEAKENED` | "Escalation paths defined" and "no Level 5 for routine execution" are enforced in code. The checklist as an artifact — a thing a human signs — is dropped, along with the two items that have no other carrier. |
| Design rule: "**Level 0–2 tasks may be built without a full brief** if scope is narrow and clear" | — | `DROPPED` | `generate_packages` requires an approved brief unconditionally. Stricter than doctrine. Defensible as a safety choice, but it is a deviation and is undocumented as one. |
| Design rule: "FukasawaGPT owns the brief. Agent Foundry does not write it." | Directive §3 file ownership | `CARRIED` | The separation is preserved by a different mechanism — per-phase file ownership rather than per-tool. |
| Design rule: "The brief is not a system prompt. It is an architectural specification." | `generator.py` deriving SKILL.md/SOUL.md *from* the brief | `CARRIED` | |

---

## 4. `# Non-Conformance Improvement Opportunit.md`

The whole document is a single instrument. Traced section by section against
`src/schemas/non_conformance.py`, `ProcessCapsule.non_conformance_note`, and
`learning_log.md` as generated by `src/foundry/generator.py`.

| Source section | Carrier | Verdict | Note |
|---|---|---|---|
| §1 Event Summary | `NonConformanceRecord.note` | `WEAKENED` | Free text absorbing §1–§3. |
| §2 Expected Outcome | `NonConformanceRecord.attempted_state` | `WEAKENED` | Captured only for the state-transition case; no field for a general expectation. |
| §3 Actual Outcome | `NonConformanceRecord.from_state`, `.kind` | `WEAKENED` | Same. |
| **§4 Complexity-First Review + ten Complexity Signals** (too many handoffs / tools / decision points / approvals / context required / unclear owners / files / exceptions / manual translations / reasoning for a repeatable task) | `learning_log.md` template prompt (generated text only) | `WEAKENED` | No field, no enum, no validation. The generated template asks "**Complexity signal?**" and offers *"too many handoffs / too much context required / unclear ownership / undefined output / scope exceeded / etc."* — **three of the ten source signals, two invented ones, and an "etc."**. The seven omitted include "too many approvals" and "too much reasoning required for a repeatable task", which are the two most diagnostic for this product. |
| **§5 Can This Be Simplified — eight fixed questions** | — | `DEFERRED` (ADR-010) | ADR-010 adopts these verbatim as `reduction_prompt` on `Rule`/`WorkflowFinding`. Not proposed for `NonConformanceRecord`. |
| **§6 Root Cause Finding** — complexity *confirmed / contributing / ruled out*, plus evidence | — | `DROPPED` | This is the field that operationalizes "until disproven": it forces the presumption to be discharged on the record. Nothing proposed recovers it. |
| §7 Corrective Action (immediate fix) | `NonConformanceRecord.resolution_note` | `WEAKENED` | Free text absorbing §7 and §8. |
| **§8 Preventive Action — closed nine-item vocabulary, ordered reduction-before-addition** | `learning_log.md` template checkboxes (generated text only) | `WEAKENED` / `DEFERRED` (ADR-010) | The closest thing to a carrier, and it degrades in a revealing way. It tracks **source 2's** nine-item list rather than source 4 §8 (the two lists differ: source 2 says "convert a decision into a rule" where source 4 says "reduce decision complexity"), keeps the first six, and replaces the last three — *split an overloaded task*, *merge redundant artifacts*, *add process only if simplification is insufficient* — with a free-text `- [ ] Other:`. **The dropped tail is where the doctrine lives**: §8's ordering exists to put "add process" last and conditional, and an "Other" escape hatch defeats a closed vocabulary by construction. It is also emitted prose in an agent package, not a validated contract, so nothing can test it. ADR-010 proposes typing this on `remediation`. |
| §9 Process Update Needed | — | `DROPPED` | No link from a non-conformance to the workflow, contract, or checklist it should change. The loop the document exists to close is open. |
| §10 Verification ("how will we know complexity was reduced?") | — | `DROPPED` | |
| Core intent: "the goal is not merely to recover from failure, but to prevent recurrence by improving the process" | `ResolutionStatus` | `WEAKENED` | Records *that* something was resolved, not what changed to prevent recurrence. |
| Instruction: "do not create standalone `failureRecovery.md` as the primary response to failure" | `generator.py` emitting `learning_log.md` in NCIO format, with no separate failure log | `CARRIED` | Source 5 restates this rule and the generator obeys it. |

---

## 5. `agent_foundry_gpt_builder_brief_v_1 (1).md` (secondary)

| Source concept | Carrier | Verdict | Note |
|---|---|---|---|
| Agent template file set (SKILL.md, SOUL.md, CONTRACT.md, evals.yaml, simulations.yaml, permissions.json, learning_log.md, candidate_skill.md, process_capsule.yaml, README.md) | `src/foundry/generator.py` | `CARRIED` | Generated file-for-file. |
| `SKILL.md` declares `depth_level` and `maturity`; "every agent must know its level and must not reach above it" | `_skill_md()`, `AgentSpec.depth_level`, `src/foundry/validator.py` cross-checking declarations agree | `CARRIED` | The validator's three-way agreement check is stronger than the source asked for. |
| `SOUL.md` opens with `inherits: ../../doctrine.md` in C-Pax workspaces; refuse to build if no `doctrine.md` exists | `_soul_md()`; `generate_packages` raising `BuildRefusedError` | `CARRIED` | Refusal implemented as specified. |
| `evals.yaml` must test three things by default: output schema conformance, escalation correctness, scope compliance | `_evals_yaml()`, `CheckCategory` | `CARRIED` | |
| `simulations.yaml` results must be emitted as Observation Packets — "undefined output format is not acceptable" | `_simulations_yaml()` | `CARRIED` | |
| **Complexity Gate: "What is the lowest reasoning level this task actually needs?" — the user must answer before the build proceeds; Agent Foundry cannot continue until this is answered** | `AgentSpec.depth_level` (a required field) | `WEAKENED` | The *answer* is required; the *asking* is not. A required schema field is satisfied by any value, including a copied one. The source made this an interactive gate precisely so the number would be considered. Nothing in the repo distinguishes a considered depth level from a default. Relevant to Phase 5: an exported `depth_level` derived by table is by construction unasked. |
| Complexity Gate table caps at Level 4; "if the user selects Level 4, ask whether the task can be decomposed first" | `generate_packages` refusing Level 5 | `WEAKENED` | The Level 5 refusal is carried. The Level 4 decomposition prompt is dropped. |
| C-Pax Directory Profile: seven required paths; "agents must not read or write outside these paths unless declared in CONTRACT.md" | `C_PAX_PATHS`, `_paths_for()`, `_permissions_json()` | `CARRIED` | Including the refusal to build a non-C-Pax agent without explicit paths. |
| Deployment Method taxonomy (10 methods); default File Package; "the user must confirm deployment method before the build is finalized" | `DeploymentMethod` enum (all 10), defaulting to `FILE_PACKAGE` | `WEAKENED` | Same shape as the Complexity Gate loss: the taxonomy and default are carried, the required confirmation is not. |
| Practical Upgrade Path (draft → tested → validated → scale, each with a trigger and method) | `maturity.py` ladder | `WEAKENED` | Maturity levels carried; the method-per-phase mapping is dropped. |
| "Contain the risk, not the growth" + the reconciliation with validate-before-scaling | promotion gates | `CARRIED` | See §1. |
| Memory Philosophy: network hippocampus, shared canonical memory, contextual retrieval | — | `DROPPED` (chosen) | Directive §9 forbids new dependencies; no requirement demands it. |
| Long-Term Capabilities: multi-agent coordination, agent ecosystems, simulating organizational structures | — | `DROPPED` (chosen) | Explicit §4 non-goals. Building toward them is a stop-and-escalate condition. |

---

## 6. `Project_Directory_Standard.md` (secondary)

**A conflict between sources that the repo resolved silently.** This document
is titled *C-Pax Project Directory Standard* and specifies **named**
directories (`brief/`, `context/`, `research/`, `tasks/active/`, `outputs/`) —
which source 1 classifies as **Pattern B**. Source 5's "C-Pax Directory
Profile" specifies **numbered** directories (`02_context/`, `05_tasks/ready/`,
`11_outputs/`) — source 1's **Pattern A**.

Two source documents therefore attach the name "C-Pax" to opposite layouts.
`detect_workspace_profile()` resolves this in favor of the numbered layout —
correctly, since that is what the generator must emit paths for — but the
resolution is recorded nowhere, and a reader arriving from this document will
find `profile == "c-pax"` returning `generic` for a workspace built to the
standard that carries the C-Pax name.

| Source concept | Carrier | Verdict | Note |
|---|---|---|---|
| Named-directory layout (Pattern B) | — | `DROPPED` | Falls to `generic`, which requires explicit paths per agent. |
| "Agents don't explore intuitively — they look for known paths" | `_paths_for()` refusing to build without defined paths | `CARRIED` | The rationale for the refusal, restated in `BuildRefusedError`'s message. |
| `doctrine.md` as the non-negotiable layer agents use to reject out-of-scope requests | `SOUL.md` `inherits:` declaration; C-Pax build refusal | `CARRIED` | |
| Naming conventions table (kebab-case, `YYYYMMDD-` dated outputs, `ARCHIVED-` prefix) | slug patterns on `workflow_id`, `step_id`, `gate_id`, `agent_name` | `WEAKENED` | Identifier slugs are enforced; file-naming conventions are not. |
| "Never let agents overwrite `final/` without a review step" | `_permissions_json()` path whitelist | `CARRIED` | Agents write to `outputs/`, never to a final path, and permissions are a whitelist. |
| Minimum Viable Project (README + doctrine + system prompt) | — | `DROPPED` | No scaffolding command exists. Backlogged as "add project initialization command". |
| `archive/` — "nothing is deleted, it's moved here" | Append-only `RunLedger` | `CARRIED` | Different mechanism, same doctrine. `docs/schema-reference.md` and the maturity contract both require previous artifacts to remain available. |

---

## What this map does not do

- It does not change any contract. Every verdict is an observation.
- It does not judge the four `DROPPED (chosen)` rows as defects. Directive §4
  forbids building them and §7 makes designing toward them a stop-and-escalate
  condition.
- It does not trace the July-18 `specs/*.md` drafts as sources. They are
  intermediate restatements, cited only where they date a loss.
- It records two gaps nothing currently proposes to close: the Non-Conformance
  instrument (*Losses* §1, especially source 4 §6 and §9) and the downward half
  of Capability Lift (§2). Both are candidates for an ADR; neither is one yet.

Regenerate this map when a Source Input changes. The sources have been stable
since May 2026; a change to one of them is the event this document exists to
make visible.
