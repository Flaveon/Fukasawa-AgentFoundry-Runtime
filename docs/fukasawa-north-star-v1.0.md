# Fukasawa North Star and Recovery Roadmap v1.0
Date: 2026-10-13
Status: product-intent baseline; implementation milestones are proposals, not completed features.
Owner: ConcordiaPax LLC

## Product purpose
Fukasawa is a humane, local-first continuous-improvement system. It observes real workflows, preserves evidence, diagnoses avoidable complexity, proposes bounded simplifications, tests them, and deliberately moves stable work from expensive reasoning into lower-level agents, rule units, checklists, or scripts. Its success is measured by quality preserved or improved **and** reduced operator burden, recurrence, risk, maintenance, or inference cost. It may recommend *not* automating. Agent Foundry packages and promotes validated capabilities; the existing runtime supplies governance, execution, persistence, human gates, and evaluation.

**Key distinction:** workflow validation is required infrastructure, not the full product. No claim that a complete self-improvement loop exists until a measured end-to-end demonstration passes.

## Authoritative source hierarchy and handling conflicts
1. Owner-approved, dated product decisions and this North Star govern intended outcomes; amendments require an explicit owner-approved ADR, never silent reinterpretation.
2. Original FukasawaGPT doctrine, Task Depth Framework, Workflow Design Brief, Non-Conformance Improvement Opportunity instrument, and 2026-05-31 Quality Orchestrator Integration Plan are product-intent sources. They remain living reference material, not instructions to execute blindly and not runtime dependencies.
3. Approved current contracts and ADRs govern **safe operation of implemented code**. When implementation disagrees with intent, report a traceable gap and propose migration; **do not** pretend code is automatically correct or break production to force agreement.
4. Actual code and tests are the evidence for what works today, not authority to redefine intended product scope. Historical implementation plans are useful context even when superseded for execution.

For every changed requirement record: source passage -> intended behavior -> current carrier -> coverage (carried/weakened/renamed/dropped/deferred) -> proposed action -> acceptance test -> owner decision. Do not close gaps by changing wording alone.

## May 31 quality loop (originally Q2C publish-package pilot)
1. Load task-specific quality standards.
2. Capture output and direct observations separately from inferences; record uncertainty and missing evidence.
3. Apply whole-package deterministic and judgment-based quality gates.
4. Decide PASS / RETRY / HOLD / ESCALATE.
5. Perform complexity-first non-conformance diagnosis: removal, simplification, clarified input, or downward transfer before extra process/agents.
6. Execute a bounded corrective action and remeasure.
7. Record before/after quality, token/compute cost, manual cleanup, recurrence and outcome proxies.
8. On repeated validated success, package correction as a process capsule and propose migration to the lowest safe reasoning level.
9. Promote only with independent tests, owner approval as warranted, provenance and rollback. Repeat when evidence justifies it.
The May 31 plan defined up to three local retry loops before more expensive escalation; this is a Q2C pilot policy, not a universal retry rule.

## Evidence-based recovery gaps
See docs/source-to-contract-map.md for original audit. Priority gaps:
- Missing explicit simplify-before-validate stage and full operator/hardware/time complexity budget.
- Non-conformance diagnostic flattened into free text; restore complexity presumption, structured root-cause verdict, and preventive-action ordering.
- Maturity moves upward but verified **downward task/capability migration** is absent.
- Outcome quality and human maintenance burden are not yet measured in a complete A/B cycle.
- The authoritative word 'Process Capsule' collides with the runtime execution-state object; distinguish a transferable capability contract from a runtime unit without destructive migration.
- Agent cognitive load, operator sustainability, and evidence of benefits must outrank feature accumulation.
Do not mistake unverified repository documentation for tested runtime behavior.

## Bounded milestones
M0 — Source reconciliation: preserve the May 31 plan and source docs by reference; audit divergence and publish owner decisions, no code rewrite.
M1 — First full improvement case: pick a repeatable Q2C publish defect, baseline the current workflow, use existing model adapter to propose a narrower rule, independently test clean and adversarial cases, require approval, run the candidate in shadow mode.
M2 — Safe reasoning-to-rule promotion: a validated process capsule with evidence, domain boundaries, uncertainty/abstention, reversible rollout, rollback and regression checks; prove fewer reasoning calls without lower quality.
M3 — Generalize: reusable diagnosis/corrective-action interfaces, budget-aware decision routing, outcome telemetry (including manual time), and capability lift into Agent Foundry.
M4 — Cross-project adoption: CPAX Marketing, PHASEONE and storefront work use shared portable interfaces without coupling each product's launch to unfinished autonomous self-improvement.
M5 — Investigate a small specialist 'Fukasawa philosophy' model or Jev-like decision model **only** after a labeled outcome dataset and benchmarks show a maintainable, measurable advantage over rules + existing LLMs.

## Definition of done for the first milestone
A worked case includes a real before/after artifact, consistent quality rubric, fixed eval dataset, rejected unsafe candidates, an approved low-depth replacement, human-understandable trace, benchmarked human time + token cost, and documented rollback. Passing schema tests alone is not sufficient.

## Agent autonomy boundaries
Untrusted local coding agents (OpenCode/Qwen or others) may research, plan, simulate and submit branches/PRs in disposable worktrees. No unattended production deploy, secret access beyond least privilege, self-approval, protected-branch merge, payment/action on customer assets, or self-modifying policies. Require CI, independent review, scoped tool permissions, rollback and human release approval. Promote autonomy gradually based on observed eval outcomes rather than model branding.

## CPAX project portfolio dependency sequence (October 2026)
- Existing funnel reported by owner: GreenMind -> Substack subscribers; CPAX General Store Etsy assets; website -> Substack -> YouTube. Verify each link/integration before calling it production-ready.
- Distribution backlog: Pinterest, X, Instagram, TikTok account/content consistency and automations; schedule as a bounded marketing sprint, not a Fukasawa prerequisite.
- Enable AgentCommons + Fukasawa portable governance/workflows for PHASEONE, CPAX Marketing and concordiapax.com digital storefront. Keep AgentCommons independent and its mission centered on bounded delegation, portable resources, trust and reputation.
- Then prioritize CPAX EIP core research, **or** deploy a validated, supervised multi-agent throughput system for other projects. Do not promise reliable unattended autonomy before execution receipts, sandboxing, security evaluations (Reef Protocol), checkpointing and approval gates are proven.
- Portfolio north star: lower operator load and accelerate revenue/launch, not create dependency on another elaborate subsystem.

## Change discipline
Prefer no new dependency, daemon or trained model when a documented rule and existing runtime suffice. For each feature ask: what burden disappears, what complexity is introduced, how is the gain measured, who approves, what is reversible? Preserve already useful governance infrastructure. Keep original source documents discoverable and never rewrite history to make a release look complete.
