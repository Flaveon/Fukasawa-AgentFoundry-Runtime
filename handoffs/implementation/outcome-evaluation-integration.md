# Outcome Evaluation Integration — Fukasawa × smevals

**Status:** design handoff, post-release. Companion to
`adr-proposals/adr-008-outcome-evaluation.md`, which holds the *why* and the
binding constraints; this holds the *how*.

**Provenance.** Merges the operator's integration handoff (which supplied the
contract pipeline: compile → execute → normalize → govern) with ADR-008 (which
supplied the boundary policy). The operator's pipeline is the spine of this
document. Three things were changed against it after type-checking the flow
against the real schemas; each change is called out and justified below rather
than quietly absorbed.

---

## 1. The pipeline

```
                        OutcomeEvalCase                    ← NEW contract
                     (tasks · grader · two arms)
                               │
                    compile    │
             ┌─────────────────┴─────────────────┐
             ▼                                   ▼
     smevals eval dir                     smevals eval dir
     Task + Grader                        Task + Grader        (identical)
     Config: model M, runner=baseline     Config: model M, runner=fukasawa
             │                                   │
     execute │  smevals run -n N -g              │  smevals run -n N -g
             ▼                                   ▼
     Run + Grade  (immutable, on disk)   Run + Grade
             └─────────────────┬─────────────────┘
                               │  normalize + compare arms
                               ▼
                    Fukasawa EvalResult                ← EXISTING contract
              category: outcome_quality · evidence cites grade paths
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
        regression →     Human Review      Promotion evidence
        NonConformance    (always)         (never automatic)
```

**The model is the control.** Both arms pin the same model and the same tasks
and the same grader. The only difference is the runner: unoptimized versus the
Fukasawa export. The delta is the measurement. A single arm produces a score
about a model; two arms produce evidence about *our intervention*, which is the
only thing this integration exists to measure.

## 2. Changes made to the original handoff, and why

### 2.1 The source object cannot be `EvalCase`

The original flow starts at `Fukasawa EvaluationCase`. Checked against
`src/schemas/eval_case.py`, that does not type-check:

| smevals needs | `EvalCase` has |
|---|---|
| `Task.prompt` | — no prompt field |
| `Config.model`, `Config.runner` | — no model or runner field |
| `Grader.checks` (output assertions) | `scoring: dict[CheckCategory, bool]` — the five **process** checks |

`EvalCase.scoring` selects handoff completeness, observation discipline, depth
compliance, escalation correctness, complexity reduction. Those are computed
*post hoc from ledger artifacts*; they are not assertions a checker can apply
to a model output. There is nothing to compile.

**Resolution: a new `OutcomeEvalCase` contract, beside `EvalCase`, not
replacing or extending it.** Overloading `EvalCase` would repeat the mistake the
architecture review already caught once (D3, where `AccountableWorkflow` nearly
became a second `WorkflowBrief`): two different questions, different lifecycles,
one schema. The two cases differ on every axis —

| | `EvalCase` (exists) | `OutcomeEvalCase` (new) |
|---|---|---|
| asks | did the work move correctly? | did the work come out better? |
| timing | post hoc, on a recorded run | active execution of tasks |
| input | ledger artifacts | prompts, model, runner |
| verdict | conformance | comparative score |

### 2.2 The sink is `EvalResult`, and that is worth keeping

The original flow normalizes back into `EvaluationResult`. **Keep this** — it is
the highest-value decision in the handoff. Reusing `EvalResult` inherits the
entire existing pipeline at the cost of one enum value: the `eval_results`
ledger table, promotion evidence lookup, CLI reporting, and the aggregate rule.

One additive schema change is required: **`CheckCategory` gains
`OUTCOME_QUALITY`**. Additive enum values are safe within a major version
(ADR-002), and the category name is what keeps outcome results visibly distinct
from process results wherever they are read.

### 2.3 The flow needs a second arm

The original diagram is single-path: one case → one task/config/grader → one
run/grade → one result. That yields an absolute score with nothing to compare it
against, which cannot answer "did optimization work."

**Resolution: the diagram above is the *per-experiment* view; the original is
the per-arm view.** An `OutcomeEvalCase` declares both arms and the compile step
emits two smevals Configs sharing one model, one task set, one grader.

## 3. The boundary: CLI and files, never a library import

ADR-008 requires a peer tool — no import, no vendoring, no `pyproject.toml`
entry. The compile/normalize steps do not weaken that, because both cross the
boundary as **files and a subprocess**:

* **compile** writes `eval.yaml`, `tasks/*.yaml`, `configs/*.yaml`,
  `graders/*.yaml` into an eval directory.
* **execute** shells out: `smevals run <dir> -n N -g <grader>`.
* **normalize** reads `smevals report <dir> --json`, plus the immutable
  `runs/<task>/<config>/<model>/<ts>/grades/<grader>/grade.yaml` artifacts.

This is exactly the existing adapter doctrine — *"adapters connect the runtime
to tools without making those tools the architecture"*
(`src/kernel/adapters.py`). If smevals is absent, the adapter reports
`ok=False`; nothing else in the runtime notices. Proposed home:
`src/governance/outcome_eval.py`, reusing the `ShellAdapter` execution pattern.

## 4. Failure semantics — harness error is not evidence

smevals is explicit: *"a non-zero exit code marks the Run as failed: a
harness-level error… not evidence about the model."* If a harness error
normalized to `FAIL`, a broken API key would manufacture a non-conformance.

**Our aggregate rule already handles this correctly, with no change.** Verified:

```
PASS + SKIPPED  -> pass       # a skipped check does not poison the verdict
all SKIPPED     -> skipped    # nothing ran, so nothing is claimed
```

**Mapping:** harness failure → `CheckOutcome.SKIPPED` with the stderr path as
evidence. Genuine low grade → `FAIL`. The distinction must be made at normalize
time, because after that the two are indistinguishable.

## 5. Non-determinism — the honest caveat

Every other evidence artifact this runtime produces is reproducible: the
validator emits byte-identical reports, and graph fingerprints are pinned. **An
outcome result is not.** LLM sampling means the same case run twice yields
different grades.

Consequences, which must be stated wherever these results are displayed:

* **Never treat a single run as evidence.** Always `-n N` (smevals supports
  repeats natively); record N and the spread, not just a mean.
* **A delta inside the noise band is not a result.** The normalized
  `EvalResult.notes` must carry N and variance so a reader can tell a real
  improvement from sampling.
* These results are **evidence for a human**, never an automatic gate — which is
  ADR-008 constraint 2, and non-determinism is the second independent reason for
  it.

## 6. Non-conformance: only on regression

The original flow routes to `NonConformanceRecord`. Refined: **a low absolute
score is not a non-conformance.** `NonConformanceKind` today means the work left
the governed path (`no_valid_path`, `missing_evidence`, `review_rejected`,
`other`). Filing an NCR for every mediocre score would dilute the concept until
nobody reads them.

**A regression is different and does belong there.** If the Fukasawa-optimized
arm scores *worse* than baseline, the optimization made the work worse — which
is precisely the signal the doctrine wants: *repeated failures trigger
non-conformance review, and the first corrective question is whether a step can
be removed or simplified.* Record as kind `other` with a note naming both arms
and the delta; a dedicated kind can be added later if the pattern recurs.

## 7. Contract mapping (implementer's reference)

| Fukasawa | direction | smevals |
|---|---|---|
| `OutcomeEvalCase.tasks[]` | compile → | `tasks/<name>.yaml` (`name`, `prompt`) |
| `OutcomeEvalCase.model` | compile → | `configs/*.yaml` `model:` — **identical in both arms** |
| arm identity | compile → | `configs/*.yaml` `runner:` — the only difference |
| `OutcomeEvalCase.grader` | compile → | `graders/<name>.yaml` (`checks`, `scoring.pass_threshold`) |
| `EvalResult.checks[].outcome` | ← normalize | `grade.yaml` per-check result |
| `EvalResult.checks[].category` | ← normalize | *(constant)* `outcome_quality` |
| `EvalResult.checks[].evidence` | ← normalize | path to `grade.yaml` / `output.txt` |
| `EvalResult.notes` | ← normalize | N, variance, both arms' scores, the delta |
| `EvalResult.overall` | ← normalize | `EvalResult.overall_from(checks)` — unchanged |
| `OutputArtifact(kind="outcome_grade", path=…)` | ← normalize | the run directory, referenced not copied |

## 8. Schema deltas required (none of them now)

1. **New:** `OutcomeEvalCase` — tasks, model, grader spec, two arm definitions.
2. **Additive:** `CheckCategory.OUTCOME_QUALITY`.
3. **Nothing else.** Confirmed: `RuntimeState` evidence references are already
   opaque strings, so grade artifacts attach via `OutputArtifact.path`/`kind`
   with no contract change. Phase 3 persistence needs **no** modification for
   this, and phase 5's export already carries the provenance
   (`PromotionLineage`) an experiment needs to name what was under test.

## 9. Constraints carried from ADR-008 (unchanged)

1. Peer tool, referenced by path — no import, no vendoring, no dependency entry.
2. Evidence, never an automatic gate. If a future ADR proposes gating on these,
   deterministic checkers only — an LLM judge must never become load-bearing in
   an authoritative decision.
3. Never used to select a model. That is not what this measures.
4. Vocabulary is disambiguated in every operator-facing surface: "workflow run"
   vs "smevals run", "governance eval" vs "outcome eval".

## 10. Open, deliberately

* **What the first grader actually asserts.** The Substack pilot is the intended
  first subject, but nobody has written checks for "is this article good." That
  is a content-quality question and may be where an LLM judge is genuinely
  appropriate — which makes constraint 2 load-bearing rather than theoretical.
* **What "baseline" means concretely.** The observed workflow has no runnable
  form; the honest baseline is probably a naive single-prompt runner. Needs a
  decision before the first experiment.
* **Whether outcome evidence should ever inform promotion.** Separate ADR. Not
  now.

## 11. Not in this release

Untouched by all of the above: the release proves map → validate → repair →
cooperate → export. Outcome measurement is strictly downstream of the export,
and nothing here changes a phase in flight.
