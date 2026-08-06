# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Optional evaluation execution backend — compiles a native case for smevals.

Fukasawa owns evaluation *semantics*: what a case asks, what counts as
evidence, when a human must look, whether anything is promoted. This adapter
borrows only *mechanics* — running a task, capturing an immutable record,
applying checks — from ``smevals`` (https://github.com/prime-radiant-inc/smevals,
MIT). The runtime works exactly the same when smevals is not installed.

Three crossings, all of them files or a subprocess, never an import:

    compile    write eval.yaml, tasks/, configs/, graders/, checkers/ into an
               isolated workspace
    execute    subprocess: smevals run <workspace> ...
    normalize  read run.yaml / grade.yaml off disk into a native EvalResult

Why a subprocess and not a library import: smevals is at 0.2.0 and its package
(``__init__.py``, ``cli.py``, ``site.py``) exposes a Click group, not a
documented API. Binding to internals of a pre-1.0 project would make every
upstream release a possible breakage, and would force a mandatory dependency.
The CLI is the documented interface, so the CLI is the seam. See
``docs/smevals-integration-assessment-v1.md`` for the full reasoning.

**The distinction this module exists to protect:** a runner that crashes is not
evidence that the evaluated work was bad. smevals already honours this — a
non-zero runner exit marks the Run failed, and failed runs are "never graded,
excluded from reports". We carry the same distinction across the boundary as
``ExecutionStatus``, so a dead endpoint can never masquerade as a governance
verdict.

**What this module never does:** decide promotion, write to the ledger on its
own authority, modify run artifacts, or treat a numeric score as a verdict.
"""

import json
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from src.schemas.eval_case import (
    CheckCategory,
    CheckOutcome,
    EvalCase,
    EvalCheckResult,
    EvalResult,
    ExecutionStatus,
)

#: The backend this adapter drives. Recorded on every result it produces.
BACKEND_NAME = "smevals"

#: Supported version range. smevals is pre-1.0, so its CLI flags and on-disk
#: layout carry no compatibility promise; pin deliberately and revisit on
#: upgrade rather than discovering a break through a wrong verdict.
SUPPORTED_VERSION_SPEC = ">=0.2,<0.3"

#: Check modes the compiler emits. Deliberately few: every one is deterministic
#: and needs no model to decide. An LLM judge would be an additional mode, added
#: only when a question genuinely needs judgment — never to verify a field.
MODE_REQUIRE_TEXT = "require_text"
MODE_FORBID_TEXT = "forbid_text"
MODE_REQUIRE_DEPTH = "require_depth"


class SmevalsUnavailableError(RuntimeError):
    """Raised when the smevals CLI is not installed or not on PATH."""


class CaseCompilationError(ValueError):
    """Raised when a native case cannot be expressed as an smevals evaluation."""


# --------------------------------------------------------------- availability


def backend_available() -> bool:
    """Whether the smevals CLI can be found on PATH.

    Feature detection, not an import guard: nothing here imports smevals, so
    the runtime never fails because it is absent — it simply cannot execute,
    which callers surface as NOT_EXECUTED rather than as an error.
    """
    return shutil.which("smevals") is not None


def backend_version() -> str:
    """Return the installed smevals version, or empty string if unavailable.

    Never raises. A version we cannot read is recorded as unknown rather than
    allowed to abort an evaluation.
    """
    if not backend_available():
        return ""
    try:
        proc = subprocess.run(
            ["smevals", "--version"], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return (proc.stdout or proc.stderr).strip()


# ------------------------------------------------------------------- compile


@dataclass
class CompiledEvaluation:
    """An isolated smevals workspace built from one native case.

    A build product, not a source: it is written to a disposable directory,
    never committed, and never hand-edited.
    """

    workspace: Path
    case_id: str
    grader_name: str
    task_name: str
    config_name: str
    check_count: int
    files: list[Path] = field(default_factory=list)


#: Runner: echoes the artifact under evaluation to stdout, which smevals
#: captures as output.txt. Deterministic and offline — the subject of this
#: proof of concept is an artifact the runtime already produces, so no model is
#: involved. Exits non-zero ONLY for infrastructure problems (a missing file),
#: which is exactly the contract smevals documents.
_RUNNER_SCRIPT = '''#!/usr/bin/env python3
"""Deterministic runner: emit the artifact under evaluation on stdout.

smevals invokes a runner with no arguments and passes everything by
environment. A non-zero exit means a harness problem, never a bad result —
so a missing artifact exits 1 (infrastructure) while any real content exits 0
(judge it, however bad).
"""
import os
import sys

path = os.environ.get("SMEVALS_TASK_ARTIFACT_PATH", "")
if not path:
    sys.stderr.write("no SMEVALS_TASK_ARTIFACT_PATH provided\\n")
    sys.exit(1)
try:
    with open(path, "r", encoding="utf-8") as fh:
        sys.stdout.write(fh.read())
except OSError as exc:
    sys.stderr.write("cannot read artifact: %s\\n" % exc)
    sys.exit(1)

declared = os.environ.get("SMEVALS_TASK_DECLARED_DEPTH", "")
if declared:
    with open("declared_depth.txt", "w", encoding="utf-8") as fh:
        fh.write(declared)
sys.exit(0)
'''

#: Checker: one script, several modes, selected per check by configuration.
#: Exit 0 passes, non-zero fails, and a JSON object on stdout carries notes.
#: It is defensive on purpose — smevals' checker contract gives exit codes only
#: pass/fail meaning, with no third state, so a crashing checker would be
#: indistinguishable from a failing check. Anything unexpected fails loudly
#: with a note saying why.
_CHECKER_SCRIPT = '''#!/usr/bin/env python3
"""Deterministic governance checker for a compiled Fukasawa evaluation case.

Modes:
  require_text   the output must contain a required marker
  forbid_text    the output must NOT contain a forbidden claim
  require_depth  the runner-declared depth must equal the expected depth
"""
import json
import os
import sys


def emit(notes, score):
    sys.stdout.write(json.dumps({"notes": notes, "score": score}))


run_dir = os.environ.get("SMEVALS_RUN_DIR", "")
raw = os.environ.get("SMEVALS_CHECK", "{}")
try:
    check = json.loads(raw)
except json.JSONDecodeError as exc:
    emit("checker could not parse SMEVALS_CHECK: %s" % exc, 0.0)
    sys.exit(1)

mode = check.get("mode", "")
value = str(check.get("value", ""))

try:
    with open(os.path.join(run_dir, "output.txt"), "r", encoding="utf-8") as fh:
        output = fh.read()
except OSError as exc:
    emit("checker could not read output.txt: %s" % exc, 0.0)
    sys.exit(1)

if mode == "require_text":
    ok = value.lower() in output.lower()
    emit(("found" if ok else "missing") + " required marker: %s" % value, 1.0 if ok else 0.0)
    sys.exit(0 if ok else 1)

if mode == "forbid_text":
    ok = value.lower() not in output.lower()
    emit(("absent" if ok else "PRESENT") + " forbidden claim: %s" % value, 1.0 if ok else 0.0)
    sys.exit(0 if ok else 1)

if mode == "require_depth":
    try:
        with open(os.path.join(run_dir, "declared_depth.txt"), "r", encoding="utf-8") as fh:
            declared = fh.read().strip()
    except OSError:
        emit("no declared depth was recorded by the runner", 0.0)
        sys.exit(1)
    ok = declared == value
    emit("declared depth %s, expected %s" % (declared, value), 1.0 if ok else 0.0)
    sys.exit(0 if ok else 1)

emit("unknown check mode: %s" % mode, 0.0)
sys.exit(1)
'''


def _checks_for(case: EvalCase) -> list[dict]:
    """Derive deterministic checks from a native case's expected outputs.

    Only what is genuinely checkable against an output is compiled. The case's
    ``scoring`` dimensions are deliberately *not* compiled: those five
    categories are process checks computed from ledger artifacts by
    src/governance/checks.py, and they are not assertions about a text.
    """
    expected = case.expected_outputs
    checks: list[dict] = []
    for marker in expected.required_fields:
        checks.append({"mode": MODE_REQUIRE_TEXT, "value": marker})
    for claim in expected.forbidden_claims:
        checks.append({"mode": MODE_FORBID_TEXT, "value": claim})
    if expected.expected_escalation:
        checks.append({"mode": MODE_REQUIRE_TEXT, "value": expected.expected_escalation})
    if expected.expected_depth is not None:
        checks.append({"mode": MODE_REQUIRE_DEPTH, "value": str(expected.expected_depth)})
    return checks


def compile_case(
    case: EvalCase,
    workspace: str | Path,
    *,
    artifact_path: str | Path,
    declared_depth: Optional[int] = None,
    model: str = "deterministic-local",
) -> CompiledEvaluation:
    """Compile a native EvalCase into an isolated smevals workspace.

    ``artifact_path`` is the thing under evaluation — for the proof of concept,
    a run handoff produced by src/runtime/handoff.py. No model is invoked.

    Raises CaseCompilationError when the case declares nothing checkable, so a
    silently empty evaluation can never be mistaken for a passing one.
    """
    checks = _checks_for(case)
    if not checks:
        raise CaseCompilationError(
            f"case '{case.case_id}' declares no checkable expectations "
            f"(required_fields, forbidden_claims, expected_escalation or "
            f"expected_depth). Compiling it would produce an evaluation that "
            f"passes without asserting anything."
        )

    root = Path(workspace)
    task_name = case.case_id
    grader_name = "governance"
    config_name = "deterministic"
    written: list[Path] = []

    def write(rel: str, text: str, executable: bool = False) -> Path:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        if executable:
            path.chmod(0o755)
        written.append(path)
        return path

    write("eval.yaml", yaml.safe_dump(
        {"name": case.case_id, "description": case.name}, sort_keys=False
    ))

    # Task scalar keys reach the runner as SMEVALS_TASK_<KEY>.
    task: dict = {
        "name": task_name,
        "prompt": case.notes or case.name,
        "artifact_path": str(Path(artifact_path).resolve()),
    }
    if declared_depth is not None:
        task["declared_depth"] = str(declared_depth)
    write(f"tasks/{task_name}.yaml", yaml.safe_dump(task, sort_keys=False))

    write(f"configs/{config_name}.yaml", yaml.safe_dump(
        {"name": config_name, "runner": "../runners/artifact-runner", "model": model},
        sort_keys=False,
    ))

    write(f"graders/{grader_name}.yaml", yaml.safe_dump(
        {
            "name": grader_name,
            "checks": [
                {"checker": "../checkers/governance-check", "required": True, **c}
                for c in checks
            ],
            "scoring": {"pass_threshold": 1.0},
        },
        sort_keys=False,
    ))

    write("runners/artifact-runner", _RUNNER_SCRIPT, executable=True)
    write("checkers/governance-check", _CHECKER_SCRIPT, executable=True)

    return CompiledEvaluation(
        workspace=root,
        case_id=case.case_id,
        grader_name=grader_name,
        task_name=task_name,
        config_name=config_name,
        check_count=len(checks),
        files=written,
    )


# ------------------------------------------------------------------- execute


@dataclass
class ExecutionOutcome:
    """What happened when the backend was invoked — mechanics, not verdict."""

    ok: bool
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    note: str = ""


def execute(
    compiled: CompiledEvaluation, *, repeats: int = 1, timeout: float = 300.0
) -> ExecutionOutcome:
    """Invoke the smevals CLI against a compiled workspace.

    Reports failure by returning ``ok=False`` rather than raising, following
    the runtime's existing adapter convention — the caller owns the policy
    decision about what a failure means, and an adapter that throws steals it.

    ``repeats`` maps to smevals' ``-n``. Outcome evaluation is not
    reproducible the way the rest of this runtime is, so more than one trial is
    the norm, not an optimization.
    """
    if not backend_available():
        return ExecutionOutcome(
            ok=False,
            note=(
                "the smevals CLI is not installed or not on PATH. Install it "
                "with 'uv tool install smevals' — the runtime works without it, "
                "but this evaluation cannot execute."
            ),
        )
    cmd = [
        "smevals", "run", str(compiled.workspace),
        "-n", str(repeats),
        "-g", compiled.grader_name,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return ExecutionOutcome(ok=False, note=f"smevals timed out after {timeout}s")
    except OSError as exc:
        return ExecutionOutcome(ok=False, note=f"could not invoke smevals: {exc}")
    return ExecutionOutcome(
        ok=proc.returncode == 0,
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        note="" if proc.returncode == 0 else f"smevals exited {proc.returncode}",
    )


# ----------------------------------------------------------------- normalize


def find_grade_files(compiled: CompiledEvaluation) -> list[Path]:
    """Locate grade artifacts written under the workspace, newest last.

    Sorted for determinism. A run that failed at the harness level is never
    graded by smevals, so its absence here is meaningful rather than an error.
    """
    runs = compiled.workspace / "runs"
    if not runs.exists():
        return []
    return sorted(runs.rglob(f"grades/{compiled.grader_name}/grade.yaml"))


def _read_yaml(path: Path) -> dict:
    """Read a YAML mapping, returning {} for anything unusable."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _first(data: dict, *names, default=None):
    """Return the first present key among ``names``.

    smevals is pre-1.0 and a literal grade.yaml could not be retrieved during
    assessment, so the normalizer accepts several plausible spellings rather
    than hard-coding one and silently mis-reading a future release. Recorded as
    open risk 1 in docs/smevals-integration-assessment-v1.md.
    """
    for name in names:
        if name in data:
            return data[name]
    return default


def _outcome_from(value) -> CheckOutcome:
    """Map a backend pass/fail signal onto the native outcome vocabulary."""
    if isinstance(value, bool):
        return CheckOutcome.PASS if value else CheckOutcome.FAIL
    text = str(value).strip().lower()
    if text in {"pass", "passed", "ok", "true", "success"}:
        return CheckOutcome.PASS
    if text in {"fail", "failed", "false", "failure"}:
        return CheckOutcome.FAIL
    return CheckOutcome.SKIPPED


def normalize(
    case: EvalCase,
    compiled: CompiledEvaluation,
    outcome: ExecutionOutcome,
    *,
    workflow_id: str = "",
    run_id: str = "",
    grade_path: Optional[Path] = None,
) -> EvalResult:
    """Turn a backend grade into a native EvalResult.

    The one rule that governs every branch below: **a harness failure is not
    evidence about the evaluated work.** It is recorded as EXECUTION_FAILED
    with the checks SKIPPED, so the aggregate rule cannot turn broken
    infrastructure into a governance verdict, and ``is_evidence`` is False.
    """
    version = backend_version()
    base = dict(
        result_id=f"eval-{uuid.uuid4().hex[:8]}",
        case_id=case.case_id,
        workflow_id=workflow_id or case.workflow,
        agent=case.agent,
        run_id=run_id,
        executed_by=BACKEND_NAME,
        executor_version=version,
    )

    # 1. The backend never ran, or broke before producing a grade.
    if not outcome.ok:
        status = (
            ExecutionStatus.NOT_EXECUTED
            if not backend_available()
            else ExecutionStatus.EXECUTION_FAILED
        )
        return EvalResult(
            **base,
            checks=[],
            overall=CheckOutcome.SKIPPED,
            execution_status=status,
            requires_human_review=True,
            notes=(
                f"evaluation did not produce a verdict: {outcome.note or 'unknown failure'}. "
                f"This says nothing about the evaluated work."
            ),
        )

    # 2. It ran, but no grade exists — smevals excludes failed runs from
    #    grading, so this is a harness failure too, not a silent pass.
    path = grade_path or (find_grade_files(compiled)[-1] if find_grade_files(compiled) else None)
    if path is None or not path.exists():
        return EvalResult(
            **base,
            checks=[],
            overall=CheckOutcome.SKIPPED,
            execution_status=ExecutionStatus.EXECUTION_FAILED,
            requires_human_review=True,
            notes=(
                "smevals reported success but wrote no grade artifact. A run "
                "that fails at the harness level is never graded, so this is an "
                "execution failure, not a passing evaluation."
            ),
        )

    grade = _read_yaml(path)
    if not grade:
        return EvalResult(
            **base,
            checks=[],
            overall=CheckOutcome.SKIPPED,
            execution_status=ExecutionStatus.EXECUTION_FAILED,
            external_run_ref=str(path.parent.parent.parent),
            artifact_paths=[str(path)],
            requires_human_review=True,
            notes=f"grade artifact at {path} is missing or malformed; no verdict can be read.",
        )

    # 3. A real grade. Translate it — without letting its score decide anything.
    raw_checks = _first(grade, "checks", "check_results", "results", default=[]) or []
    checks: list[EvalCheckResult] = []
    candidates: list[str] = []
    for entry in raw_checks:
        if not isinstance(entry, dict):
            continue
        result = _outcome_from(
            _first(entry, "outcome", "result", "status", "passed", default="skipped")
        )
        label = str(_first(entry, "checker", "name", "check", default="check"))
        detail = str(_first(entry, "notes", "note", "detail", "message", default=""))
        checks.append(
            EvalCheckResult(
                # Externally executed checks assert things about an output, not
                # the five process dimensions; handoff completeness is the
                # dimension this proof of concept exercises.
                category=CheckCategory.HANDOFF_COMPLETENESS,
                outcome=result,
                evidence=f"{label}: {detail}" if detail else label,
            )
        )
        if result is CheckOutcome.FAIL:
            candidates.append(f"{label}: {detail}" if detail else label)

    overall = EvalResult.overall_from(checks) if checks else CheckOutcome.SKIPPED
    score = _first(grade, "score", "total_score")
    run_dir = path.parent.parent.parent
    artifacts = [str(path)] + [
        str(run_dir / name)
        for name in ("output.txt", "stderr.txt", "run.yaml")
        if (run_dir / name).exists()
    ]

    return EvalResult(
        **base,
        checks=checks,
        overall=overall,
        execution_status=ExecutionStatus.COMPLETED,
        external_run_ref=str(run_dir),
        score=float(score) if isinstance(score, (int, float)) else None,
        artifact_paths=artifacts,
        non_conformance_candidates=candidates,
        # A failed verdict is evidence for a person, never an automatic breach.
        requires_human_review=overall is not CheckOutcome.PASS,
        notes=(
            f"executed by {BACKEND_NAME} {version or 'unknown version'}; "
            f"{len(checks)} check(s); grade at {path}"
        ),
    )


def evaluate(
    case: EvalCase,
    workspace: str | Path,
    *,
    artifact_path: str | Path,
    declared_depth: Optional[int] = None,
    repeats: int = 1,
    workflow_id: str = "",
    run_id: str = "",
) -> EvalResult:
    """Compile, execute, and normalize in one call — the whole vertical slice.

    Returns a native EvalResult in every case, including when the backend is
    absent. Nothing here writes to the ledger or decides anything: the caller
    owns what to do with the evidence.
    """
    compiled = compile_case(
        case, workspace, artifact_path=artifact_path, declared_depth=declared_depth
    )
    outcome = execute(compiled, repeats=repeats)
    return normalize(
        case, compiled, outcome, workflow_id=workflow_id, run_id=run_id
    )
