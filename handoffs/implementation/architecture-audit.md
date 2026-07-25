# Architecture Audit — Fukasawa-AgentFoundry Runtime

**Phase Handoff 01 deliverable. Audit date: 2026-07-25.**

Repository inspected at commit `679ce00` (v0.1.0 released + Phase 5C signed
bundles + Oldowan examples). This audit now lives on
`feature/human-cooperative-workflow-runtime`, branched from `main` @ `9273374`
(the PR #1 merge that landed Phase 5C). Every `src/` path and line number
cited below is identical in both — `679ce00` differs from `9273374` only by
two example YAML files under `examples/`, which no citation here depends on.

Scope ruling recorded up front (operator-confirmed, 2026-07-25, then amended
the same day when the operator supplied the **Agent Development Master
Handoff v1.0** ("Fukasawa Human & Cooperative Workflow Runtime")):
- The **master Definition of Done** is §2 of the master handoff (Functional /
  Quality / Release criteria for the Human Workflow Validator/Builder and
  Cooperative Workflow Builder). The earlier interim answer (roadmap Phase 5
  exit criteria) is superseded.
- The **proposed domain objects** are §5 of the master handoff
  (`HumanWorkflowDraft`, `WorkflowStep`, `WorkflowFinding`,
  `AccountableWorkflow`, `CooperationAssessment`, `CooperativeWorkflow`),
  mapped onto existing modules in §7 below. The earlier interim answer
  (ADR-topic list) is superseded.
- The repository is **Python-only** (operator-confirmed; verified by
  inspection — zero `.ts` files, no `package.json`). The master handoff's
  premise of a "mixed Python and TypeScript" runtime (§3, §9.2) does not
  match this repository. Its own instruction governs: "agents must inspect
  the repository rather than assume." **Unresolved Gate A item:** master DoD
  §2.2 requires cross-language fixtures proving Python/TS agreement, which a
  Python-only release cannot satisfy as written — see risk R8 and the
  completion note.

---

## 1. Repository map (verified, not asserted)

```
/                           AGENTS.md, CLAUDE.md, HANDOFF.md, LICENSE (AGPLv3),
                            README.md, roadmap.md, pyproject.toml
brief/                      project-brief.md (product thesis, success criteria)
config/                     model_endpoints.example.yaml (placeholder hosts only)
docs/                       architecture.md, dependencies.md,
                            evaluation-strategy.md, product-principles.md
examples/                   q2c-production-handoff.yaml (brief)
                            q2c-pipeline-graph.yaml (graph)
                            oldowan-cataloging-review.yaml (brief)
                            oldowan-pipeline-graph.yaml (graph)
                            evals/  (3 eval cases)
                            packages/ (writer-agent, publisher-agent, build_report.md)
handoffs/                   phase-0..4 handoff docs; implementation/ (this audit)
packaging/                  build.sh, fukasawa.spec, rthook_tk.py, README.md
registry/                   prompt-module-registry.yaml (Phase 6 placeholder)
specs/                      process-capsule-schema.md, runtime-state-contract.md,
                            workflow-brief-schema.md   (July-18 DRAFTS — see §3)
src/
  app_entry.py              one binary, two modes: no args → GUI, args → CLI
  cli.py                    Typer app; 10 sub-apps (see §4)
  schemas/                  10 Pydantic v2 contract modules (see §3)
  runtime/                  state_machine.py, ledger.py, review_gate.py,
                            handoff.py, bundle.py
  foundry/                  generator.py, validator.py
  governance/               checks.py, evals.py, maturity.py
  kernel/                   kernel.py (GraphRunner), adapters.py, models.py
  security/                 signing.py (Ed25519 + SHA-256), trust.py (TrustStore)
  gui/                      app.py (CustomTkinter, 2 tabs), services.py (boundary)
tasks/                      backlog.md
tests/                      10 test modules; 113 passed, 4 skipped (GUI, need display)
.github/workflows/build.yml test (Linux) + PyInstaller build on 3 OSes; v* tag → Release
```

## 2. Ownership boundaries

Single-language repository: **Python 3.11+** end to end (`pyproject.toml`
`requires-python = ">=3.11"`). There are zero `.ts` files, no `package.json`,
no `tsconfig.json`. "Python/TypeScript ownership boundary" therefore has no
current referent; the forward-looking boundary design lives in
`adr-proposals/adr-007-desktop-service-boundary.md`.

Internal ownership boundaries that DO exist, by import direction:

| Layer | Owns | May import |
|---|---|---|
| `src/schemas/` | contracts (Pydantic v2) | nothing outside schemas |
| `src/runtime/` | state machine, ledger, gates, handoffs, bundles | schemas, security |
| `src/foundry/` | package generation + validation | schemas |
| `src/governance/` | evals, checks, maturity | schemas, runtime (ledger) |
| `src/kernel/` | graph execution, adapters, model endpoints | schemas, runtime, security |
| `src/security/` | signing, trust store | nothing above stdlib + cryptography |
| `src/gui/` | widgets only | `src/gui/services.py` only |
| `src/gui/services.py` | the desktop/service seam | schemas, runtime, foundry |
| `src/cli.py` | operator surface | everything |

## 3. Canonical contract source

**Canonical: the Pydantic v2 models in `src/schemas/`.** The runtime
validates against these everywhere (`WorkflowRuntime.load_brief`,
`RunLedger` load/save round-trips, `GraphSpec.model_validate`,
`BundleManifest.model_validate_json`).

- `specs/*.md` are **July-18 drafts**, superseded where they conflict by the
  project `CLAUDE.md` (operator ruling recorded in `HANDOFF.md`, "Key
  context / conventions"). They are historical inputs, not contracts.
- `docs/architecture.md` lists a fuller aspirational object set
  (`TaskDepthAssessment`, `RunTrace`, `PromotionDecision` as objects); the
  implemented subset is what `src/schemas/` contains. `ObservationPacket`
  (`src/schemas/observation_packet.py`) is explicitly draft status.
- Versioning today: only `RuntimeState.schema_version`
  (`src/schemas/runtime_state.py:128`) and `BundleManifest.format_version`
  (`src/schemas/bundle.py:75`). `WorkflowBrief`, `ProcessCapsule`, and
  `GraphSpec` carry **no version field** — see ADR-002 and the risk register.

## 4. Service locations

| Service | Where | Notes |
|---|---|---|
| CLI | `src/cli.py` | Typer sub-apps: validate, runs, package, eval, maturity, graph, trust, model, bundle, nonconformance + top-level run/resume/status/history/review/gui |
| Desktop | `src/gui/app.py` (+ `src/app_entry.py` dispatch) | CustomTkinter; exactly 2 tabs: **Validate Brief**, **Build Workflow**; thin views over services |
| Desktop/service seam | `src/gui/services.py` | `validate_brief_file() → BriefValidation`, `build_workflow() → BuildOutcome` (wraps `generate_packages` + `validate_package`); no widget types cross this line |
| Persistence | `src/runtime/ledger.py` (`RunLedger`) | SQLite via sqlite-utils; append-only `record_event`; save/load for workflow, capsule, run, observation, graph run, eval result, promotion, NCR |
| Runtime state | `src/schemas/runtime_state.py` + `src/runtime/state_machine.py` | durable `RuntimeState`, blocked-run contract (reason + next_action), human gate as first-class state |
| Orchestration | `src/kernel/kernel.py` (`GraphRunner`) | checkpointed graph runs, trust-gated (`UntrustedGraphError`), hash-pinned resume |
| Agent Foundry export | `src/foundry/generator.py` | `generate_packages()` → 10-file package dir; `BuildRefusedError` doctrine gates; self-validated by `src/foundry/validator.py:validate_package` |
| Workflow export/import | `src/runtime/bundle.py` (Phase 5C) | signed `.fkz` bundles; `export_bundle`/`import_bundle`/`inspect_bundle`; refuses untrusted/tampered before writing |
| Trust/signing | `src/security/trust.py`, `src/security/signing.py` | Ed25519 detached signatures; `FUKASAWA_HOME` (default `~/.fukasawa/`) store |

## 5. Package manager and test commands (confirmed working)

- Install: `uv venv .venv --python 3.11 && uv pip install --python .venv/bin/python -e '.[dev,gui]'` (plain `pip install -e` also works; CI uses uv + Python 3.12).
- Tests: `.venv/bin/python -m pytest -q` → **113 passed, 4 skipped** (the 4 are GUI-view tests that need a display; CI runs them under `xvfb-run -a`).
- Binary: `./packaging/build.sh` (PyInstaller; ≈38 MB on Linux). CI builds linux-x64 / macos-arm64 / windows-x64 and attaches them to `v*` tag Releases.
- No JS/TS toolchain exists.

## 6. Backward-compatibility constraints

v0.1.0 is tagged, released, and public with binaries attached. The following
are now compatibility surfaces:

1. **CLI command surface** (`src/cli.py`) — scripts and docs reference it.
2. **Brief/graph YAML formats** — briefs exist outside the repo (operator
   workflows); Pydantic must keep accepting today's files.
3. **SQLite ledger schema** — user `fukasawa.db` files exist; the ledger is
   doctrinally **append-only** (no destructive migration is acceptable).
4. **Signature canonicalization** — graph signatures and `graph_hash` pins
   are computed over `model_dump(mode="json")` (`src/kernel/kernel.py:
   graph_fingerprint`, `_require_trusted`). **Adding any field to `GraphSpec`
   changes the canonical bytes, invalidating every existing `.sig` sidecar
   and breaking hash-pinned resume of in-flight runs.** Same mechanism now
   applies to `BundleManifest` signatures. This is the single sharpest
   compatibility edge in the codebase — see ADR-002 and risk R1.
5. **Agent package layout** — the 10-file package shape is validated by
   `validate_package` and consumed by operators; generated packages exist on
   disk outside the repo.
6. **`.fkz` bundle format v "1"** — now a wire format others may hold copies of.
7. **Trust store layout** — `~/.fukasawa/{identity,trusted}/` with 0600/0700
   permissions; keys must survive upgrades.

## 7. Proposed domain objects (master handoff §5) → existing modules

| §5 object | Exists today? | Nearest existing analog(s) | Proposed home (NEW unless noted) | ADR |
|---|---|---|---|---|
| `HumanWorkflowDraft` | **No** | `WorkflowBrief` (`src/schemas/workflow_brief.py`) is the *downstream* governed artifact, not the observed draft — it has no actors/systems/pain-points/unwritten-rules/source-evidence concepts | `src/schemas/human_workflow.py` | ADR-001/002 |
| `WorkflowStep` | **No** | `Transition` (`workflow_brief.py:52`) carries owner/evidence; `GraphNode` (`src/schemas/graph.py:66`) carries next-links + retry. Neither has decision authority, inputs/outputs, entry/exit conditions, or exception paths | `src/schemas/human_workflow.py` | ADR-004 |
| `WorkflowFinding` | **No** (findings exist only as `list[str]`) | `validate_package()` returns bare strings (`src/foundry/validator.py:54`); `GraphSpec.validate_against_brief` returns `list[str]`; `EvalCheckResult` (`src/schemas/eval_case.py:109`) is the one *typed* finding-like object | `src/schemas/findings.py` | ADR-003 |
| `AccountableWorkflow` | **Partial in spirit** | `WorkflowBrief` already declares owners, states, transitions-with-evidence, exception_path, completion_criteria — it IS the shape §5.4 describes, minus accepted-residual-risks and promotion lineage | `src/schemas/human_workflow.py`, exporting to `WorkflowBrief` (the existing Foundry path) | ADR-005 |
| `CooperationAssessment` | **No** | `TaskDepth` (ROUTINE/GUIDED/CONSCIOUS, `workflow_brief.py:35`) and `AgentSpec.depth_level` are coarse ancestors of the §6 executor classes | `src/schemas/cooperation.py` | ADR-006 |
| `CooperativeWorkflow` | **No** | `WorkflowBrief.agents` (`AgentSpec`: escalation_target, forbidden, deployment_method — `src/schemas/agent_spec.py`) covers the agent-side half; human owner/approval-gate/fallback are new | `src/schemas/cooperation.py` | ADR-006 |

Supporting machinery from the master handoff, same discipline:

| Capability | Exists today? | Existing pattern to reuse | ADR |
|---|---|---|---|
| Validator rule registry (§7, 16 rules) | **No** | dispersal noted above; `EvalCase.scoring` shows the declare-which-checks-run pattern | ADR-003 |
| Promotion state machine (§8, 8 states) | **No** (different axis than what exists) | `src/governance/maturity.py` implements draft→tested→validated for *agent packages* with evidence gates + `RunLedger.record_promotion` audit — the pattern to copy, not the object to extend | ADR-005 |
| Cooperation/executor policy (§6) | **No** | human-gate doctrine (`CONSCIOUS` transitions cannot be agent-owned — `workflow_brief.py:_check_agents_are_consistent`) is the load-bearing precedent | ADR-006 |
| Desktop/service boundary (§9, §16) | **Yes** | `src/gui/services.py` — typed results, no widgets, "no second validator in UI" already honored | ADR-007 |

Nothing in these tables invents a module: "No" rows name only what would be new.

## 8. Verification appendix

Facts a follow-up implementer should re-verify rather than trust:
- Test counts (113/4) were measured on this container at `679ce00`.
- `AGENTS.md` "Source Order" cites doctrine at `../FukasawaGPT/…` — those
  files are **outside this repository** and were not readable in this
  environment.
- `docs/architecture.md` adapter list includes OpenAI/DuckDB/git adapters
  that are **not implemented** (implemented: filesystem, shell, model —
  `src/kernel/adapters.py`, `src/kernel/models.py`). The doc is aspirational.
- `registry/prompt-module-registry.yaml` is a Phase 6 placeholder, unused by
  any runtime code path found.
