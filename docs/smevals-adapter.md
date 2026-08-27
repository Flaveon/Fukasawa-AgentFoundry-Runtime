# The smevals Evaluation Backend (optional)

A prototype adapter that runs a Fukasawa evaluation case through
[smevals](https://github.com/prime-radiant-inc/smevals) and brings the result
back as a native `EvalResult`.

**It is optional.** Nothing in the runtime requires it, imports it, or fails
without it. If you never install smevals, everything else works exactly as
before — the test suite proves this, and runs entirely without it.

Assessment and rationale: `smevals-integration-assessment-v1.md`.
Decision record: `../handoffs/implementation/adr-proposals/adr-008-outcome-evaluation.md`.

## Installing

smevals is **not** a Python dependency of this project and is deliberately
absent from `pyproject.toml`. The adapter talks to it as an installed
command-line program, so install it as a tool:

```bash
uv tool install smevals        # or: pipx install smevals
smevals --version              # the adapter records whatever this reports
```

Supported range: **`>=0.2,<0.3`** (`SUPPORTED_VERSION_SPEC` in the adapter).
smevals is pre-1.0, so its CLI flags and on-disk layout carry no compatibility
promise. The version in use is recorded on every result as `executor_version`,
because a result that cannot say what produced it cannot be compared with a
later one.

Check availability from Python:

```python
from src.governance import smevals_adapter
smevals_adapter.backend_available()   # False is a normal, handled state
```

## Running the proof-of-concept evaluation

The shipped case asks whether a **blocked run produces a handoff someone else
could actually pick up** — the failure named in the project brief as recurring
("handoffs omit artifact paths or next actions"). The artifact under evaluation
is real: `src/runtime/handoff.py` writes it whenever a run pauses or blocks.

```python
import yaml
from pathlib import Path
from src.schemas.eval_case import EvalCase
from src.governance.smevals_adapter import evaluate

case = EvalCase.model_validate(
    yaml.safe_load(Path("examples/evals/blocked-handoff-completeness.yaml").read_text())
)

result = evaluate(
    case,
    workspace="build/evals/blocked-handoff",   # disposable
    artifact_path="run_handoffs/run-abc123.md",  # the handoff to judge
    declared_depth=2,
    repeats=1,
)

print(result.execution_status.value, result.overall.value, result.is_evidence)
```

No model is called. Every check is a deterministic assertion about text, so the
evaluation runs offline.

## Generated workspace

`compile_case()` writes an isolated smevals evaluation into the directory you
name:

```
<workspace>/
├── eval.yaml
├── tasks/<case_id>.yaml           name, prompt, artifact_path, declared_depth
├── configs/deterministic.yaml     runner + model (model is a fixed label here)
├── graders/governance.yaml        one check per expectation, pass_threshold 1.0
├── runners/artifact-runner        emits the artifact under evaluation
├── checkers/governance-check      require_text / forbid_text / require_depth
└── runs/                          created by smevals; immutable
```

**Treat the workspace as a build product.** It is regenerated from the case, so
put it somewhere disposable (`build/`, a temp dir), do not commit it, and do not
hand-edit it. Editing generated run artifacts is forbidden outright — smevals
treats runs as immutable and grading as append-only, and so do we.

## Artifact retention

The adapter **never deletes, prunes, or rotates** anything, and never copies
grade content into the ledger. `EvalResult.artifact_paths` and
`external_run_ref` hold *references*; the files stay where smevals wrote them.
Copying them in would create a second source of truth. Retention is your
choice — the workspace is safe to delete once you no longer need the evidence.

## How results reach the ledger

They do not, by themselves. The adapter returns a native `EvalResult` and
**makes no persistence decision**. A caller that wants it recorded does so
explicitly:

```python
from src.runtime.ledger import RunLedger
RunLedger("fukasawa.db").save_eval_result(result)
```

This needs no database migration: `eval_results` stores indexed columns plus a
`result_json` blob, so the externally-executed fields serialize into the blob.

## Execution failure vs evaluation failure

The distinction the adapter exists to protect. Always read
`execution_status` **before** drawing any conclusion from `overall`:

| `execution_status` | Meaning | `overall` | `is_evidence` |
|---|---|---|---|
| `completed` | the evaluation ran and reached a verdict | `pass` / `fail` | **True** |
| `execution_failed` | the harness broke — crash, timeout, missing grade, malformed artifact | `skipped` | **False** |
| `not_executed` | nothing was attempted (backend absent) | `skipped` | **False** |

A dead model endpoint, a crashed runner, or a timeout produces
`execution_failed` with checks `skipped` — never a failing verdict. The
evaluated work is neither proven nor disproven, and `is_evidence` says so.
smevals honours the same rule on its side: a non-zero runner exit marks the run
failed, and failed runs are never graded and excluded from reports.

## What stays under human authority

The adapter supplies evidence. It decides nothing:

* **It never promotes.** A grade is not authority to advance maturity. Promotion
  remains `src/governance/maturity.py` plus a named human reviewer.
* **It never files a non-conformance.** Failed checks surface as
  `non_conformance_candidates` — candidates for a person to consider. A failed
  check is evidence, not a governance breach.
* **It never writes to the ledger** on its own authority.
* **A numeric `score` is advisory.** Nothing in the runtime branches on it.
* `requires_human_review` is set whenever the verdict is not a pass, or the
  harness failed and left the question unanswered.

Tests enforce these mechanically: the adapter's source is asserted to contain no
promotion calls, no ledger writes, and no smevals import.

## Limitations

1. **The grade format is not fully verified.** A literal `grade.yaml` could not
   be retrieved during assessment (GitHub's API was blocked from the build
   environment), so the normalizer accepts several plausible field spellings and
   degrades to a stated `execution_failed` rather than guessing. This is the
   largest open risk — see assessment §11.
2. **A crashing checker is indistinguishable from a failing check.** smevals'
   checker contract gives exit codes only pass/fail meaning, with no third
   state. Our checker is defensive and always emits a `notes` explaining itself,
   but the ambiguity is inherent to the contract.
3. **Outcome evaluation is not reproducible** the way the rest of this runtime
   is. Nothing here is byte-stable once a real model is involved. Use `repeats`
   (smevals `-n`) and treat a single trial as anecdote.
4. **Only three check modes** exist: `require_text`, `forbid_text`,
   `require_depth`. That is what the proof of concept needed. An LLM judge is a
   deliberate non-feature — it must never be required to verify a field, a
   schema, or a known forbidden claim.
5. **The five process dimensions are not compiled.** `EvalCase.scoring` selects
   checks computed from ledger artifacts by `src/governance/checks.py`; they are
   not assertions about a text and are left where they belong.
6. **Depth checking verifies the declaration travelled**, not full depth
   compliance, which stays with the in-process governance checks.

## Removing or replacing the adapter

Removal is complete and leaves nothing behind:

```bash
rm src/governance/smevals_adapter.py tests/test_smevals_adapter.py
rm -rf <your workspace dirs>
```

Nothing imports it, no dependency references it, no database column is specific
to it. The `EvalResult` fields it populates (`executed_by`, `executor_version`,
`external_run_ref`, `execution_status`, `score`, `artifact_paths`,
`non_conformance_candidates`, `requires_human_review`) are backend-neutral by
design — no field is named after smevals — so a different execution backend
implements the same three functions (`compile_case`, `execute`, `normalize`) and
populates the same native contract.
