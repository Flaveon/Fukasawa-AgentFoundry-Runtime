# smevals Integration Assessment — v1

**Date:** 2026-08-06 · **Assessed:** `prime-radiant-inc/smevals` @ v0.2.0
**Verdict: ADOPT as an optional execution backend, behind a subprocess boundary,
with a pinned version constraint.**

Observed facts are marked **[F]** and are verifiable from the external
repository or ours. Architectural recommendations are marked **[R]** and are
judgement calls. Where evidence was unavailable, it is listed in §11 rather
than filled in.

---

## 1. Current Fukasawa evaluation architecture

**[F]** Evaluation today is entirely *post hoc analysis of recorded state*:

| Component | Location | Role |
|---|---|---|
| `EvalCase` | `src/schemas/eval_case.py` | one governance question, declared in YAML |
| `EvalResult` / `EvalCheckResult` | same | the recorded answer, persisted |
| `CheckCategory` | same | five process checks: handoff completeness, observation discipline, depth compliance, escalation correctness, complexity reduction |
| `run_eval_case()` | `src/governance/evals.py` | runs a case against a recorded run's artifacts |
| `checks.py` | `src/governance/checks.py` | the check implementations |
| persistence | `src/runtime/ledger.py` → `eval_results` | indexed columns plus a `result_json` blob |
| consumers | `src/governance/maturity.py`, CLI `eval run` | promotion evidence, operator reporting |

**[F]** There is no execution machinery. Nothing in the runtime invokes a model
to produce an artifact and then judges it. `EvalCase` has no prompt, no model,
and no runner field; its `scoring` selects which of the five process checks run
against artifacts the ledger already holds.

**[F]** `docs/evaluation-strategy.md:5` — *"The runtime should evaluate workflow
quality, **not just** model output quality."* Output evaluation is declared
insufficient alone, not out of scope. **[F]** `brief/project-brief.md` lists
*"Compare agent prompt/module versions against reviewed examples"* as an initial
use case that was never built.

## 2. Relevant smevals capabilities

**[F]** All verified against the repository, not inferred from the summary:

* **Version 0.2.0**, MIT licensed, `requires-python = ">=3.10"`.
* **Dependencies are two:** `click>=8.4.2`, `pyyaml>=6.0.3`. No model SDK, no
  network client, no orchestration framework.
* **Console entry point:** `smevals = "smevals.cli:cli"` (a Click group).
* **Package layout:** `src/smevals/` contains `__init__.py`, `cli.py`,
  `site.py`, `app.html`. There is no models module, no schema module, and no
  documented importable API surface.
* **Runner contract:** invoked with **no arguments**; input arrives entirely by
  environment — `SMEVALS_MODEL`, `SMEVALS_TASK`, `SMEVALS_PROMPT`,
  `SMEVALS_TASK_<KEY>`, `SMEVALS_RUN_DIR`. Working directory is the Run's
  directory. Stdout is captured as `output.txt`, stderr as `stderr.txt`; other
  files written are kept as Run artifacts.
* **Runner exit codes are load-bearing:** *"A non-zero exit code marks the Run
  as failed: a harness-level error — a network drop, a crashed tool — not
  evidence about the model, so it is never graded, is excluded from reports,
  and does not count towards an `-n` target."* And: *"Exit non-zero only for
  infrastructure problems; exit 0 whenever the output is a real model response
  you want judged, however bad."*
* **Checker contract:** no arguments; environment carries `SMEVALS_RUN_DIR`,
  `SMEVALS_CHECK` (the full check config as JSON), `SMEVALS_CHECK_<KEY>`,
  `SMEVALS_TASK`, `SMEVALS_TASK_<KEY>`. Exit 0 passes. A checker may emit a JSON
  object on stdout with up to five keys: `score`, `metrics`, `tags`, `notes`,
  `details`.
* **Built-in checkers:** `contains`, `xml-valid`. That is the complete list.
* **Storage:** `runs/<task>/<config>/<model>/<timestamp>/` holding `run.yaml`
  (*"the full task, resolved config, timing, exit code"*), `output.txt`,
  `stderr.txt`, and `grades/<grader>/grade.yaml` (*"outcome, score, tags,
  per-check results"* plus *"a byte-for-byte snapshot of its Grader"*).
  *"run.yaml is written last, so its presence marks a complete Run. Runs are
  immutable."*
* **CLI:** `run` (with `-n N` repeats), `grade` (with `--regrade`), `report`
  (with `--json`), `serve`, `build`, `docs`.

## 3. Concept mapping

| Fukasawa (native, authoritative) | smevals (execution mechanics) |
|---|---|
| `EvalCase` | *(no equivalent — compiles into the three below)* |
| — | `Task` (name, prompt) |
| — | `Config` (model, runner) |
| `EvalCase.expected_outputs` | `Grader` + `Check` list |
| — | `Run` (immutable execution record) |
| — | `Grade` (outcome, score, per-check results) |
| `EvalResult` / `EvalCheckResult` | *(normalization target)* |
| `CheckCategory` | *(no equivalent — smevals checks are output assertions)* |
| `NonConformanceRecord` | *(none — governance stays ours)* |
| promotion, human review, task depth | *(none — deliberately)* |

**[F]** The mapping is not symmetric. `EvalCase` cannot compile to Task + Config
+ Grader as written: it has no prompt, no model, and no runner, and its
`scoring` names process checks computed from ledger artifacts rather than
assertions applicable to a model output. **[R]** The prototype therefore treats
`EvalCase.expected_outputs` as the compilable surface — `required_fields`,
`forbidden_claims`, `expected_escalation`, `expected_depth` are all genuinely
checkable against an output — and carries the prompt/model/runner as adapter
inputs rather than inventing schema fields for them before the need is proven.

## 4. Dependency and version risks

**[F]** Version **0.2.0**: pre-1.0, so semantic-versioning convention offers no
compatibility promise. **[F]** No importable API is documented; the package
contains a CLI module and a site generator. **[R]** Therefore any Python-level
integration would be binding to undocumented internals of a pre-1.0 project —
the single strongest argument in this assessment, and the reason for §7's
recommendation.

**[F]** The dependency surface is unusually small (`click`, `pyyaml`); we
already depend on PyYAML. **[R]** Low collision risk if it were ever installed
in the same environment, but the prototype avoids the question by not importing
it at all.

**[R]** Risk that matters most: **the CLI's flags and the on-disk layout are the
contract we depend on.** Both are documented in the README and neither is
version-guaranteed. Mitigation is version pinning plus tolerant parsing (§7).

## 5. Licensing

**[F]** MIT, with `license-files = ["LICENSE"]` declared in `pyproject.toml`.
**[F]** This repository is AGPL-3.0-or-later. **[R]** MIT is permissive and
compatible with AGPL for downstream combination. **[R]** The question is moot in
practice for the prototype: we neither vendor, fork, nor link the code — we
execute an installed program and read files it writes, which is not a derivative
work under any reading. No license notice obligation is triggered by invoking a
binary. If a future phase ever vendors code, this conclusion must be revisited.

## 6. Filesystem and artifact implications

**[F]** smevals owns a directory tree and treats it as immutable and additive:
runs are never modified, grading *"only ever adds files under grades/"*, and
`--runs-dir` can relocate run storage.

**[R]** Implications we must respect:

* Generated workspaces are **build products**, not sources. They belong in a
  disposable location, not committed, and not hand-edited (the handoff forbids
  modifying generated run artifacts by hand, and smevals' own immutability
  discipline agrees).
* Our ledger stores **references, not copies**. `EvalResult` gains artifact
  paths; the run directory stays where smevals wrote it. Copying grade content
  into the ledger would duplicate a source of truth.
* Retention is the operator's choice. The adapter neither prunes nor rotates.
* This is the same append-only discipline as our own ledger, arrived at
  independently — a good sign for conceptual fit.

## 7. CLI versus library integration

| Option | Assessment |
|---|---|
| **Import `smevals` as a library** | **Rejected [R].** No documented public API; the package exposes a Click group and a site generator. Binding to internals of a 0.2.0 project would make every upstream release a potential breakage, and would require adding a runtime dependency. |
| **Subprocess against the installed CLI** | **Recommended [R].** The CLI *is* the documented interface. Failure is observable (exit code, stderr). No dependency is added. The runtime works unchanged when smevals is absent. |
| **Reimplement the harness natively** | **Rejected [R].** It is a real subsystem — immutable runs, repeats, grading, regrade, reporting — and it already exists under MIT. Building it would fail our own External Framework Adoption Test on "can that primitive be implemented locally in less code?" |
| **Vendor the source** | **Rejected [R].** Explicitly forbidden by the handoff, and it would convert an external maintenance burden into ours. |

## 8. Recommended adapter boundary

**[R]** Three crossings, all of them files or processes — never an import:

```
   compile   →  write eval.yaml, tasks/, configs/, graders/, checkers/
                into an isolated workspace directory
   execute   →  subprocess: smevals run <workspace> -n N -g <grader>
   normalize →  read runs/**/run.yaml, grades/**/grade.yaml from disk
```

**[R]** Responsibilities the adapter has, and the ones it must not take:

*Does:* validate the native case; compile a workspace; invoke through the
subprocess boundary; distinguish execution failure from evaluation failure;
locate artifacts; normalize into a native `EvalResult`; preserve evidence paths.

*Does not:* decide promotion; write to the ledger on its own authority; alter
run artifacts; interpret a numeric score as a governance verdict; require an
LLM to check a field.

## 9. Recommendation

**ADOPT as an optional execution backend**, with these conditions:

1. Subprocess boundary only; no import, no vendoring, no mandatory dependency.
2. Pin a supported version range and record the version actually used on every
   result (`executor_version`), because a pre-1.0 interface will move.
3. Grades are evidence. Promotion remains a human decision on our side of the
   boundary — an smevals grade must never be the sole authority for it.
4. Deterministic checks first. An LLM judge may be added later as an explicitly
   optional check; it must never be required to verify a field, a schema, or a
   known forbidden claim.

## 10. Rejected alternatives

* **Making `EvalCase` compile directly** — rejected; it lacks prompt, model and
  runner, and its `scoring` addresses a different question (§3).
* **Replacing `EvalResult` with smevals' grade shape** — rejected; it would make
  the external schema our native schema, which the handoff forbids and which
  would couple our ledger to a pre-1.0 external format.
* **Adding `smevals` to `pyproject.toml`** — rejected for the prototype;
  feature detection plus documented installation keeps the runtime usable
  without it, which is an acceptance criterion.
* **Auto-filing a non-conformance from a failing grade** — rejected; a failed
  check is evidence for a human, and conflating it with a governance breach
  would dilute the non-conformance record.

## 11. Explicit unknowns requiring further validation

Recorded rather than guessed. Each needs a real run against an installed CLI:

1. **The exact `grade.yaml` field names.** The README describes its *contents*
   ("outcome, score, tags, per-check results") but the assessment could not
   retrieve a literal example — the GitHub API returned 403 from this
   environment. The normalizer is therefore written **tolerantly**, accepting
   several plausible spellings and degrading to a stated `EXECUTION_FAILED`
   rather than guessing. **This is the largest open risk.**
2. **`smevals report --json` schema.** Same limitation. The prototype reads
   `grade.yaml` directly rather than depending on the report format.
3. **Exact CLI exit codes** for `run` and `grade` beyond the documented runner
   semantics.
4. **Whether `-n N` repeats appear as sibling timestamped run directories** (the
   layout implies yes, unverified).
5. **Test coverage and failure behavior of smevals itself** — its test suite was
   not retrievable from this environment.
6. **Behavior when a grader references a checker that exits non-zero for
   infrastructure reasons** rather than a genuine check failure — the checker
   contract gives exit codes only pass/fail meaning, with no third state.
   Consequence: **a crashing checker is indistinguishable from a failing
   check.** Our checkers must therefore be defensive and emit `notes` on error.

## 12. Verified compatibility facts

**[F]** `requires-python >=3.10`; ours is `>=3.11` — compatible.
**[F]** Adding fields to `EvalResult` requires **no ledger DDL change**: the
`eval_results` table stores indexed columns plus a `result_json` blob
(`src/runtime/ledger.py`), so additional model fields serialize into the blob.
**[F]** `src/runtime/handoff.py:write_handoff()` already produces the artifact
the proof-of-concept evaluates, with stable section headers (`## Next Action`,
`## Blocked Reason`, `## Artifact Paths`, `## Review Gate Status`,
`## Completion Criteria`).
