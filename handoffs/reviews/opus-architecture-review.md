# Architecture Review — Phase Handoff 02

**Role:** senior design challenge, risk review, implementation authorization.
**Date:** 2026-07-25. **Reviewed at:** `0ac4b2e` on
`feature/human-cooperative-workflow-runtime`.
**Verdict: APPROVED WITH REVISIONS.** Eight defects found; two are blocking
(D1, D2). No plan rewrite required — the audit's shape holds.

> **Provenance note (read this).** Phase Handoff 02 assigns this review to
> Opus 4.8. It was actually performed by **`claude-fable-5`**, the model
> configured for the session at the time. The filename follows the specified
> deliverable path so the pipeline resolves it; the attribution is corrected
> here so the repo does not carry a false provenance record. Master handoff
> §19 Gate G requires "selected critical diffs reviewed by Opus" — that
> requirement is **not** satisfied by this document. See §12 for the
> diff list a genuine Opus pass must cover.
> The same model authored the audit under review, so this is a self-review;
> weight it accordingly and treat D2/D3 (where I overturned my own design)
> as the evidence it was performed adversarially rather than as a rubber stamp.

---

## Answers to the 12 review questions

**1. Does the design extend the existing runtime rather than create a parallel framework?**
Yes, with one correction (D3). The load-bearing choice is right: the new layer
terminates in an export to the **existing** `WorkflowBrief`
(`src/schemas/workflow_brief.py`), so the proven state machine, ledger,
kernel, package generator, and bundle format execute the result unchanged.
Nothing in the plan forks `src/runtime/state_machine.py` or `src/kernel/`.
The one place parallelism nearly crept in is `AccountableWorkflow` — ruled on
in D3.

**2. Is there one authoritative contract source?**
Yes. Pydantic v2 models in `src/schemas/` (ADR-001, approved). This is the
factual status quo, not an aspiration: every load path already validates
through them. `specs/*.md` are superseded drafts; `docs/architecture.md` is
aspirational. Both must be labeled as such in the schema reference so future
agents don't treat them as contracts.

**3. Can Python and TypeScript remain compatible without duplicate hand-maintained schemas?**
The question is moot for this release — **there is no TypeScript**
(verified: no `.ts`, no `package.json`, no `tsconfig.json`). See D1: the
master handoff's premise is factually wrong about this repository and the DoD
inherits an unsatisfiable clause. Forward mechanism approved: JSON Schema
export as the single generation seam, so any future TS consumer is generated,
never hand-written (§9.2's actual intent).

**4. Are promotion invariants explicit and enforceable?**
Mostly, after D4 and D5. The 8-state ladder is fine as an enum but the plan
did not say which states this release actually *gates*, nor which findings
block. Both are now fixed by ruling. The critical invariant —
**blocking findings block promotion, never capture** — was implicit and is
now stated normatively (D5). Enforcement pattern is sound: copy the
`assess`/`promote`/`PromotionRefusedError` idiom from
`src/governance/maturity.py`, which already refuses on missing evidence.

**5. Is deterministic validation separated from AI assistance?**
Yes, and strongly. No LLM appears anywhere in the authoritative path; rules
are plain Python functions (ADR-003). The AI-assist surface (§9.3) is
deliberately excluded from the release-critical path entirely, which is the
right call — it cannot silently alter state if it does not exist yet.

**6. Are audit, migration, and persistence requirements sufficient?**
Sufficient for local single-operator use, with one honestly-stated ceiling
(D6): **actor attribution on risk acceptances is self-attested, not
authenticated.** Append-only ledger discipline, additive-only DDL, and
`schema_version` on every new row are the right minimum. ADR-002's
signing-canonicalization freeze is the most valuable finding in the audit and
is approved without change.

**7. Can the CustomTkinter UI remain a thin client of runtime services?**
Yes — but ADR-007 mis-named what "the services" are, producing a real phase
ordering bug (D7). Corrected: the **domain modules are the authoritative
service layer**; `src/gui/services.py` is a GUI-facing adapter. This is
already how the repo works — `src/cli.py` and `src/gui/services.py` both
import `generate_packages`/`validate_package` directly. Parity comes from
both callers hitting the same domain modules, not from the CLI calling
through a GUI module.

**8. Are executor classifications safe, explainable, and overrideable?**
Yes. Three properties make it safe rather than merely configurable: all seven
enum values exist from day one (no breaking change to add the rest);
recommendations come from a **published decision table**, not a model, so a
human can predict them; and **safety floors are one-directional** — an
override may always move work toward human control, never toward more
autonomy on a floored step. That last rule is the single most important line
in ADR-006 and mirrors existing doctrine (`_check_agents_are_consistent`
already forbids agent-owned CONSCIOUS transitions).

**9. Are human authority, escalation, fallback, and evidence preserved?**
Yes. `NOT_READY_FOR_AUTOMATION` blocks agent export of a step;
`BOUNDED_AUTONOMOUS_AGENT` exports only with an explicit approval gate;
fallback executor and escalation target carry into `AgentSpec`
(`escalation_target`, `forbidden` already exist). Evidence requirements
survive because the export maps them onto `Transition.evidence_required`,
which the state machine already refuses to advance without.

**10. Is the implementation plan cost-effective and minimally complex?**
Yes, with D2's resequencing. Nine new modules for a release of this scope is
lean; no new dependency, no new persistence engine, no new state-machine
framework, no server. I looked specifically for overengineering and found
only one candidate: `src/schemas/export_jsonschema.py` is thin enough to be a
function, but it is cheap and gives the TS seam a home — keep it. The real
cost risk is phase 7 (15 desktop requirements), addressed in D7/D8.

**11. Which decisions are expensive to reverse?**
Ranked, most to least:
1. **Signing canonicalization** (`graph_fingerprint` over `model_dump`) — a
   wrong move invalidates signatures and hash-pinned resumes in the field.
2. **Persisted enum values** — `WorkflowMaturity` and `ExecutorClass` strings
   land in SQLite rows and exported YAML forever.
3. **Rule IDs** — persisted on findings and risk acceptances; renaming
   orphans audit history.
4. **Ledger table shapes** — append-only doctrine forbids destructive
   migration.
5. **Canonical schema source** — reversing means regenerating every consumer.
6. **The export mapping** (executor class → depth/agent) — becomes the
   semantics of every generated package.
Get 1–4 right in phase 1–3; 5 is already settled; 6 is reviewable later.

**12. Which files or diffs require a final Opus review?**
See the list in §"Diffs requiring senior review" below.

---

## Defects found

### D1 — BLOCKING: the DoD contains an unsatisfiable clause (was R8)
Master handoff §2.2 requires "Cross-language fixtures prove Python and
TypeScript agree on serialized contract shapes" and §2.1/§15.2 require
"generated TS type compatibility"; Gate B requires "Python/TS agreement
verified." The repository has no TypeScript. §3's "Runtime: Mixed Python and
TypeScript" is factually incorrect for this repo, and §9.2 is self-resolving:
"Use TypeScript **where the current project already uses it**" → it does not,
so the obligation is void.

**Ruling.** The cross-language clauses are **NOT APPLICABLE** to this
release. Substituted, binding obligations:
- Ship JSON Schema export for all public contracts (`fukasawa schema dump`).
- Golden-file tests asserting the exported schemas are stable.
- Documented statement in `docs/schema-reference.md`: any future non-Python
  consumer MUST generate types from these artifacts; hand-written parallel
  definitions are prohibited (§9.2's intent, preserved).
- **Gate B is amended** to "schemas versioned; JSON Schema artifacts exported
  and golden-tested; migrations planned; contract tests green."
This is a DoD amendment and requires operator acknowledgement — it is the one
item that cannot be settled by architecture alone.

### D2 — BLOCKING: the pilot is sequenced last, so the design is unvalidated until the end
The audit's file-change-map puts the entire Substack pilot in phase 8. That
defers the only end-to-end proof of the lifecycle to after every design
decision is frozen, and it starves Gate C's false-positive review of
realistic input (rules 13/14 are heuristic and *need* a messy real workflow
to tune against).

**Ruling.** Split the pilot across phases: author
`examples/workflows/substack-publication/observed-workflow.yaml` **in phase 1**
as the driving fixture (it is a data file, no code depends on it), and let
each later phase emit its own derived artifact
(validation-report → phase 2, accountable-workflow → phase 3,
cooperation-assessment → phase 4, cooperative-workflow + workflow-design-brief
→ phase 5, README + walkthrough → phase 8). The pilot's seven seeded problems
(§10) become the acceptance fixtures for the rule set, not an afterthought.
Ownership stays conflict-free: each phase owns only the file it emits.

### D3 — `AccountableWorkflow` risked being a second `WorkflowBrief`
My audit itself noted `WorkflowBrief` already has owners, states,
transitions-with-evidence, exception paths, and completion criteria — i.e.
nearly the whole §5.4 list. Introducing a new schema with the same vocabulary
is precisely the "parallel framework" review question 1 guards against.

I considered making `AccountableWorkflow` a thin envelope
(`{brief: WorkflowBrief, lineage, accepted_risks}`) and **rejected it**:
flattening to states+transitions at promotion time destroys per-step
attributes (decision authority, reversibility, data sensitivity, per-step
evidence) that the *next* stage — cooperation assessment — must read. It also
forces a premature `task_depth` and an `agents` list that does not exist yet.

**Ruling.** Keep `AccountableWorkflow` distinct, but constrain it:
it **reuses `WorkflowStep`** rather than re-modeling steps; it introduces
**no** `states`/`transitions` vocabulary; flattening to `WorkflowBrief`
happens **only** in `src/foundry/workflow_export.py` (phase 5). Semantically
it is "the same observed steps, with accountability resolved, plus accepted
residual risks and promotion lineage." Record this rationale in ADR-005 so
the next reviewer does not re-litigate it.

### D4 — the 8-state ladder did not say which states this release enforces
`DEPLOYED` and `VALIDATED` depend on evidence only the *existing* runtime can
produce (real runs, eval results). Building new gates for them would
duplicate `src/governance/maturity.py` and edge toward the §4 non-goal
"automatic deployment of agents without explicit approval."

**Ruling.** Define all 8 values in the enum (cheap, and schema stability is
required). **Enforce gates only through `RUNTIME_READY`** in this release.
`DEPLOYED` and `VALIDATED` are recorded states whose entry criteria delegate
to existing run/eval evidence and a human `reviewed_by`; no new deployment
machinery. Document the delegation explicitly in
`docs/promotion-state-reference.md`.

### D5 — blocking policy per rule was unspecified, and "blocking" was ambiguous
DoD §2.2 requires a positive and negative test for "every blocking validation
rule," but nothing said which rules block. Worse, "blocking" was undefined:
blocking *what*?

**Ruling.** Two parts, both normative:
1. **"Blocking" means blocks promotion to `ACCOUNTABLE` — never blocks
   capture, save, or reload.** An observed draft is allowed to be a mess;
   that is the entire point of "human workflow truth comes first." Any
   implementation that refuses to save a draft because it has findings is a
   defect.
2. The per-rule blocking table is fixed in the Codex directive (§"Rule
   blocking policy"). 14 blocking, 2 non-blocking; the two non-blocking ones
   (HW-013 unwritten rules, HW-014 ambiguous terms) are the heuristic pair and
   default to non-blocking precisely because they carry false-positive risk.

### D6 — audit trail records authority acts it cannot authenticate
A risk acceptance is an authority act: a named person waives a known risk.
The stored actor is a **self-attested string** (same as `reviewed_by` in
`maturity.promote`). There is no authentication, and §4 excludes identity
management. This is acceptable for local single-operator use and must not be
oversold.

**Ruling.** Ship it, and state the ceiling plainly in
`docs/promotion-state-reference.md`: "attribution is self-attested;
adequate for a single trusted operator, insufficient as multi-party
non-repudiation." Backlog (not this release) the natural upgrade: sign risk
acceptances with the operator's existing Ed25519 identity via
`src/security/signing.py` — the trust layer already exists, which makes this
a small future change rather than a redesign.

### D7 — file-map ordering bug: the CLI phase preceded the module that owned its services
The map assigns `src/gui/services.py` to phase 7 (desktop) while requiring
(§15.6, Gate F) that CLI and desktop "call the same services" — but the CLI
lands in phase 6. As written, phase 6 cannot call a phase-7 file.

The premise was wrong, not just the order. Verified in the repo: `src/cli.py`
and `src/gui/services.py` **both import domain modules directly**
(`generate_packages`, `validate_package`, `assess`, `promote`). There is no
CLI→GUI dependency today and there must not be one.

**Ruling.** The **authoritative service layer is the domain modules**
(`src/governance/workflow_rules.py`, `workflow_promotion.py`,
`cooperation.py`, `src/foundry/workflow_export.py`). Both the CLI and the GUI
adapter call *those*. `src/gui/services.py` remains a GUI-facing adapter
containing **no decisions** — it may shape data for display and translate
refusals into renderable results, nothing more. Phase ordering is then
correct as-is, and ADR-007's wording is revised accordingly. Add a test
asserting no rule/promotion/classification logic lives in `src/gui/`.

### D8 — minor: baseline artifact placement contradicted itself
The map lists `artifacts/test-baseline.txt` under phase 8 while noting it is
"actually recorded at phase 1 start." **Ruling:** record AND commit it in
phase 1; §15.1 is a pre-work gate, and a baseline committed at the end proves
nothing.

---

## Security, permissions, failure handling

Reviewed against master handoff §2.2 ("security-sensitive permissions and
tool boundaries remain explicit") and existing posture:

- **Tool boundaries** flow into generated packages via `permissions.json` and
  `AgentSpec.forbidden`, both already validated by `validate_package`. The
  export mapping must never widen permissions beyond what the executor class
  authorizes — assert this in `tests/test_workflow_export.py`.
- **Findings render user-supplied text.** The repo already escapes Rich markup
  (`src/cli.py` uses `rich.markup.escape`); new finding output must do the
  same. Low severity, trivial to get wrong.
- **No new network surface.** Offline operation (§17) is preserved: nothing in
  the plan opens a socket. The existing "no network calls during runtime
  execution" constraint holds.
- **Secrets hygiene.** The pilot describes a real publication workflow; use
  placeholder hosts/paths per `config/model_endpoints.example.yaml`. The
  repo has had one LAN-IP leak (`9d49d56`); the pending cross-repo gitleaks
  task should land on this repo before the pilot merges (risk R11).
- **Failure handling** follows the established two-mode pattern (retryable
  refusal vs frozen non-conformance). New code must not raise bare exceptions
  across the CLI boundary — §17 forbids stack traces for normal user errors.

## Overengineering check

Found none material. Explicitly endorsed as *not* overengineering: three
coexisting state machines (run states, package maturity, workflow maturity)
— they track different axes and conflating them would corrupt all three;
ADR-005's reasoning is sound. Explicitly rejected as unnecessary: a rules
DSL, a policy-pack plugin system, FastAPI, a graph library, and any LLM in
the authoritative path. All four were correctly declined in the ADRs.

## Diffs requiring senior review (answer to question 12)

A genuine Opus pass — which this document does **not** provide (see the
provenance note) — should review these, and only these:

1. `src/schemas/human_workflow.py`, `findings.py`, `cooperation.py` — all
   three, in full. Persisted enum values and field names are expensive to
   reverse (question 11, items 2–3).
2. `src/governance/workflow_promotion.py` — the transition table and the
   blocking/acceptance gate logic.
3. `src/governance/cooperation.py` — the decision table and, specifically,
   the one-directional safety floors.
4. `src/foundry/workflow_export.py` — the executor-class → depth/agent
   mapping and the permission-widening assertion.
5. The `RunLedger._ensure_schema` diff — additive-only DDL.
6. **Any** diff touching `src/security/`, `src/kernel/`, or
   `src/schemas/graph.py` / `bundle.py`. These are frozen (ADR-002); a diff
   here means an invariant broke and needs escalation, not review.

Routine implementation (CLI wiring, views, docs, fixtures) does not need it.
