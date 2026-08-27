# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Tests for the optional smevals execution backend.

Every test here runs **offline and without smevals installed**. That is a
requirement, not a convenience: the runtime must work when the backend is
absent, so the test suite proves it by never depending on it.

Two things are exercised directly rather than through smevals, because we
cannot assume it is present:

* the generated **runner** and **checker** are invoked exactly the way smevals
  documents — no arguments, everything by environment, stdout captured,
  exit code carrying pass/fail — which verifies our side of the contract
  without needing the other side;
* **normalization** is driven from fixture grade artifacts written to disk in
  the layout smevals documents.

The distinction under most scrutiny is execution failure versus evaluation
failure. A crashed runner must never look like a workflow that failed its
checks.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from src.governance import smevals_adapter as adapter
from src.governance.smevals_adapter import (
    BACKEND_NAME,
    CaseCompilationError,
    CompiledEvaluation,
    ExecutionOutcome,
    compile_case,
    normalize,
)
from src.schemas.eval_case import (
    CheckOutcome,
    EvalCase,
    ExecutionStatus,
    ExpectedOutputs,
)

ROOT = Path(__file__).resolve().parent.parent
POC_CASE = ROOT / "examples" / "evals" / "blocked-handoff-completeness.yaml"


def _case(**kw) -> EvalCase:
    """A minimal valid case, overridable per test."""
    defaults = dict(
        case_id="poc-case",
        name="PoC",
        workflow="q2c-production-handoff",
        expected_outputs=ExpectedOutputs(
            required_fields=["## Next Action"],
            forbidden_claims=["work is complete"],
            expected_escalation="flaveon",
            expected_depth=2,
        ),
        scoring={"handoff_completeness": True},
    )
    return EvalCase(**{**defaults, **kw})


def _artifact(tmp_path: Path, text: str) -> Path:
    """Write the thing under evaluation."""
    p = tmp_path / "handoff.md"
    p.write_text(text, encoding="utf-8")
    return p


GOOD_HANDOFF = """# Run Handoff — run-abc123

- **Current state**: DRAFT_READY
- **Run status**: blocked
- **Operator**: flaveon
- **Trace**: `fukasawa.db`

## Next Action

fukasawa resume run-abc123

## Blocked Reason

Editor unavailable.

## Artifact Paths

- draft.md

## Review Gate Status

pending

## Completion Criteria

Article published.
"""


# ---------------------------------------------------------------- compilation


class TestCompilation:
    def test_valid_case_compiles_to_the_documented_layout(self, tmp_path):
        compiled = compile_case(_case(), tmp_path / "ws", artifact_path=_artifact(tmp_path, GOOD_HANDOFF))
        ws = compiled.workspace
        assert (ws / "eval.yaml").exists()
        assert (ws / "tasks" / "poc-case.yaml").exists()
        assert (ws / "configs" / "deterministic.yaml").exists()
        assert (ws / "graders" / "governance.yaml").exists()
        assert (ws / "runners" / "artifact-runner").exists()
        assert (ws / "checkers" / "governance-check").exists()

    def test_generated_task_config_and_grader_are_well_formed(self, tmp_path):
        art = _artifact(tmp_path, GOOD_HANDOFF)
        compiled = compile_case(_case(), tmp_path / "ws", artifact_path=art, declared_depth=2)
        task = yaml.safe_load((compiled.workspace / "tasks" / "poc-case.yaml").read_text())
        assert task["name"] == "poc-case"
        assert task["artifact_path"] == str(art.resolve())
        assert task["declared_depth"] == "2"

        config = yaml.safe_load((compiled.workspace / "configs" / "deterministic.yaml").read_text())
        assert config["runner"] == "../runners/artifact-runner"
        assert config["model"]

        grader = yaml.safe_load((compiled.workspace / "graders" / "governance.yaml").read_text())
        assert grader["scoring"]["pass_threshold"] == 1.0
        modes = [c["mode"] for c in grader["checks"]]
        # one per required field, per forbidden claim, plus escalation + depth
        assert modes.count("require_text") == 2   # 1 required field + escalation
        assert modes.count("forbid_text") == 1
        assert modes.count("require_depth") == 1
        assert all(c["required"] for c in grader["checks"])

    def test_scoring_dimensions_are_not_compiled_into_checks(self, tmp_path):
        # The five process dimensions are computed from ledger artifacts, not
        # asserted against a text. Compiling them would double-count them.
        compiled = compile_case(
            _case(scoring={"handoff_completeness": True, "depth_compliance": True}),
            tmp_path / "ws", artifact_path=_artifact(tmp_path, GOOD_HANDOFF),
        )
        grader = yaml.safe_load((compiled.workspace / "graders" / "governance.yaml").read_text())
        blob = json.dumps(grader)
        assert "handoff_completeness" not in blob
        assert "depth_compliance" not in blob

    def test_case_with_nothing_checkable_is_rejected(self, tmp_path):
        # An evaluation that asserts nothing would pass vacuously — refuse it
        # rather than report a meaningless success.
        empty = _case(expected_outputs=ExpectedOutputs())
        with pytest.raises(CaseCompilationError, match="no checkable expectations"):
            compile_case(empty, tmp_path / "ws", artifact_path=_artifact(tmp_path, GOOD_HANDOFF))

    def test_the_shipped_poc_case_compiles(self, tmp_path):
        case = EvalCase.model_validate(yaml.safe_load(POC_CASE.read_text(encoding="utf-8")))
        compiled = compile_case(
            case, tmp_path / "ws",
            artifact_path=_artifact(tmp_path, GOOD_HANDOFF), declared_depth=2,
        )
        assert compiled.check_count == len(case.expected_outputs.required_fields) + len(
            case.expected_outputs.forbidden_claims
        ) + 2  # escalation + depth


# ------------------------------------------ generated runner / checker contract


def _run_script(path: Path, env: dict, cwd: Path) -> subprocess.CompletedProcess:
    """Invoke a generated script exactly as smevals documents: no args, env only."""
    return subprocess.run(
        [sys.executable, str(path)],
        env={**os.environ, **env}, cwd=str(cwd),
        capture_output=True, text=True, timeout=60,
    )


class TestGeneratedRunnerContract:
    """Our side of smevals' runner contract, verified without smevals."""

    def test_runner_emits_the_artifact_on_stdout_and_exits_zero(self, tmp_path):
        art = _artifact(tmp_path, GOOD_HANDOFF)
        compiled = compile_case(_case(), tmp_path / "ws", artifact_path=art)
        run_dir = tmp_path / "run"; run_dir.mkdir()
        proc = _run_script(
            compiled.workspace / "runners" / "artifact-runner",
            {"SMEVALS_TASK_ARTIFACT_PATH": str(art), "SMEVALS_RUN_DIR": str(run_dir)},
            run_dir,
        )
        assert proc.returncode == 0
        assert "## Next Action" in proc.stdout

    def test_runner_records_declared_depth_as_an_artifact(self, tmp_path):
        art = _artifact(tmp_path, GOOD_HANDOFF)
        compiled = compile_case(_case(), tmp_path / "ws", artifact_path=art, declared_depth=2)
        run_dir = tmp_path / "run"; run_dir.mkdir()
        _run_script(
            compiled.workspace / "runners" / "artifact-runner",
            {"SMEVALS_TASK_ARTIFACT_PATH": str(art),
             "SMEVALS_TASK_DECLARED_DEPTH": "2", "SMEVALS_RUN_DIR": str(run_dir)},
            run_dir,
        )
        assert (run_dir / "declared_depth.txt").read_text().strip() == "2"

    def test_runner_exits_nonzero_only_for_infrastructure_problems(self, tmp_path):
        # smevals: "Exit non-zero only for infrastructure problems". A missing
        # artifact is infrastructure; bad content is not.
        compiled = compile_case(_case(), tmp_path / "ws", artifact_path=_artifact(tmp_path, GOOD_HANDOFF))
        run_dir = tmp_path / "run"; run_dir.mkdir()
        proc = _run_script(
            compiled.workspace / "runners" / "artifact-runner",
            {"SMEVALS_TASK_ARTIFACT_PATH": str(tmp_path / "nope.md"), "SMEVALS_RUN_DIR": str(run_dir)},
            run_dir,
        )
        assert proc.returncode != 0
        assert "cannot read artifact" in proc.stderr

    def test_runner_exits_zero_on_bad_content(self, tmp_path):
        art = _artifact(tmp_path, "this handoff is useless")
        compiled = compile_case(_case(), tmp_path / "ws", artifact_path=art)
        run_dir = tmp_path / "run"; run_dir.mkdir()
        proc = _run_script(
            compiled.workspace / "runners" / "artifact-runner",
            {"SMEVALS_TASK_ARTIFACT_PATH": str(art), "SMEVALS_RUN_DIR": str(run_dir)},
            run_dir,
        )
        assert proc.returncode == 0, "bad output must still be judged, not marked a harness error"


class TestGeneratedCheckerContract:
    """Our side of smevals' checker contract, verified without smevals."""

    def _check(self, tmp_path, output: str, check: dict, extra=None):
        compiled = compile_case(_case(), tmp_path / "ws", artifact_path=_artifact(tmp_path, GOOD_HANDOFF))
        run_dir = tmp_path / "rundir"; run_dir.mkdir(exist_ok=True)
        (run_dir / "output.txt").write_text(output, encoding="utf-8")
        for name, text in (extra or {}).items():
            (run_dir / name).write_text(text, encoding="utf-8")
        return _run_script(
            compiled.workspace / "checkers" / "governance-check",
            {"SMEVALS_RUN_DIR": str(run_dir), "SMEVALS_CHECK": json.dumps(check)},
            run_dir,
        )

    def test_required_field_present_passes(self, tmp_path):
        proc = self._check(tmp_path, GOOD_HANDOFF, {"mode": "require_text", "value": "## Next Action"})
        assert proc.returncode == 0
        assert json.loads(proc.stdout)["score"] == 1.0

    def test_required_field_missing_fails(self, tmp_path):
        proc = self._check(tmp_path, "nothing useful", {"mode": "require_text", "value": "## Next Action"})
        assert proc.returncode == 1
        assert "missing required marker" in json.loads(proc.stdout)["notes"]

    def test_forbidden_claim_absent_passes(self, tmp_path):
        proc = self._check(tmp_path, GOOD_HANDOFF, {"mode": "forbid_text", "value": "work is complete"})
        assert proc.returncode == 0

    def test_forbidden_claim_present_fails(self, tmp_path):
        proc = self._check(
            tmp_path, GOOD_HANDOFF + "\nwork is complete\n",
            {"mode": "forbid_text", "value": "work is complete"},
        )
        assert proc.returncode == 1
        assert "PRESENT" in json.loads(proc.stdout)["notes"]

    def test_depth_matching_passes_and_mismatch_fails(self, tmp_path):
        ok = self._check(tmp_path, GOOD_HANDOFF, {"mode": "require_depth", "value": "2"},
                         extra={"declared_depth.txt": "2"})
        assert ok.returncode == 0
        bad = self._check(tmp_path, GOOD_HANDOFF, {"mode": "require_depth", "value": "2"},
                          extra={"declared_depth.txt": "5"})
        assert bad.returncode == 1

    def test_checker_is_defensive_about_its_own_failures(self, tmp_path):
        # The checker contract gives exit codes only pass/fail meaning, so a
        # crash is indistinguishable from a failure. It must at least say why.
        proc = self._check(tmp_path, GOOD_HANDOFF, {"mode": "no-such-mode", "value": "x"})
        assert proc.returncode == 1
        assert "unknown check mode" in json.loads(proc.stdout)["notes"]


# --------------------------------------------------------------- normalization


def _compiled_at(tmp_path) -> CompiledEvaluation:
    return compile_case(_case(), tmp_path / "ws", artifact_path=_artifact(tmp_path, GOOD_HANDOFF))


def _write_grade(compiled: CompiledEvaluation, grade: dict) -> Path:
    """Write a grade artifact in the layout smevals documents."""
    run_dir = compiled.workspace / "runs" / "poc-case" / "deterministic" / "local" / "20260806T000000"
    grade_dir = run_dir / "grades" / compiled.grader_name
    grade_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "output.txt").write_text(GOOD_HANDOFF, encoding="utf-8")
    (run_dir / "run.yaml").write_text("exit_code: 0\n", encoding="utf-8")
    path = grade_dir / "grade.yaml"
    path.write_text(yaml.safe_dump(grade), encoding="utf-8")
    return path


class TestNormalization:
    def test_passing_grade_normalizes_to_a_passing_result(self, tmp_path):
        compiled = _compiled_at(tmp_path)
        _write_grade(compiled, {
            "outcome": "pass", "score": 1.0,
            "checks": [{"checker": "governance-check", "outcome": "pass", "notes": "found marker"}],
        })
        result = normalize(_case(), compiled, ExecutionOutcome(ok=True), workflow_id="wf")
        assert result.overall is CheckOutcome.PASS
        assert result.execution_status is ExecutionStatus.COMPLETED
        assert result.is_evidence
        assert result.executed_by == BACKEND_NAME
        assert result.score == 1.0
        assert not result.requires_human_review
        assert not result.non_conformance_candidates

    def test_failing_grade_normalizes_to_evidence_needing_review(self, tmp_path):
        compiled = _compiled_at(tmp_path)
        _write_grade(compiled, {
            "outcome": "fail", "score": 0.5,
            "checks": [
                {"checker": "governance-check", "outcome": "pass", "notes": "found marker"},
                {"checker": "governance-check", "outcome": "fail", "notes": "missing ## Next Action"},
            ],
        })
        result = normalize(_case(), compiled, ExecutionOutcome(ok=True))
        assert result.overall is CheckOutcome.FAIL
        # It still *is* evidence — the evaluation genuinely ran and found a fault.
        assert result.execution_status is ExecutionStatus.COMPLETED
        assert result.is_evidence
        assert result.requires_human_review
        assert any("missing ## Next Action" in c for c in result.non_conformance_candidates)

    def test_artifact_paths_are_preserved_not_copied(self, tmp_path):
        compiled = _compiled_at(tmp_path)
        grade_path = _write_grade(compiled, {"outcome": "pass", "checks": []})
        result = normalize(_case(), compiled, ExecutionOutcome(ok=True))
        assert str(grade_path) in result.artifact_paths
        assert any(p.endswith("output.txt") for p in result.artifact_paths)
        assert result.external_run_ref == str(grade_path.parent.parent.parent)

    def test_tolerant_of_alternative_field_spellings(self, tmp_path):
        # smevals is pre-1.0 and a literal grade.yaml could not be retrieved
        # during assessment; the normalizer accepts plausible spellings rather
        # than silently mis-reading a future release.
        compiled = _compiled_at(tmp_path)
        _write_grade(compiled, {
            "result": "fail",
            "check_results": [{"name": "c1", "passed": False, "message": "nope"}],
        })
        result = normalize(_case(), compiled, ExecutionOutcome(ok=True))
        assert result.overall is CheckOutcome.FAIL
        assert result.non_conformance_candidates


class TestExecutionVersusEvaluationFailure:
    """The distinction the whole adapter exists to protect."""

    def test_infrastructure_failure_is_not_evidence(self, tmp_path, monkeypatch):
        monkeypatch.setattr(adapter, "backend_available", lambda: True)
        monkeypatch.setattr(adapter, "backend_version", lambda: "0.2.0")
        compiled = _compiled_at(tmp_path)
        result = normalize(
            _case(), compiled,
            ExecutionOutcome(ok=False, returncode=1, note="model endpoint unavailable"),
        )
        assert result.execution_status is ExecutionStatus.EXECUTION_FAILED
        assert result.overall is CheckOutcome.SKIPPED, "must not read as a failed evaluation"
        assert not result.is_evidence
        assert result.requires_human_review
        assert "says nothing about the evaluated work" in result.notes

    def test_success_without_a_grade_is_execution_failure_not_a_pass(self, tmp_path, monkeypatch):
        # smevals never grades a failed run, so a missing grade after a
        # reported success is a harness problem — never a silent pass.
        monkeypatch.setattr(adapter, "backend_available", lambda: True)
        monkeypatch.setattr(adapter, "backend_version", lambda: "0.2.0")
        compiled = _compiled_at(tmp_path)
        result = normalize(_case(), compiled, ExecutionOutcome(ok=True))
        assert result.execution_status is ExecutionStatus.EXECUTION_FAILED
        assert result.overall is not CheckOutcome.PASS
        assert not result.is_evidence

    def test_malformed_grade_artifact_is_execution_failure(self, tmp_path, monkeypatch):
        monkeypatch.setattr(adapter, "backend_available", lambda: True)
        monkeypatch.setattr(adapter, "backend_version", lambda: "0.2.0")
        compiled = _compiled_at(tmp_path)
        run_dir = compiled.workspace / "runs" / "t" / "c" / "m" / "ts"
        grade_dir = run_dir / "grades" / compiled.grader_name
        grade_dir.mkdir(parents=True)
        (grade_dir / "grade.yaml").write_text(": : not yaml : :", encoding="utf-8")
        result = normalize(_case(), compiled, ExecutionOutcome(ok=True))
        assert result.execution_status is ExecutionStatus.EXECUTION_FAILED
        assert not result.is_evidence
        assert "malformed" in result.notes

    def test_a_harness_failure_can_never_produce_a_pass(self, tmp_path, monkeypatch):
        monkeypatch.setattr(adapter, "backend_available", lambda: True)
        monkeypatch.setattr(adapter, "backend_version", lambda: "")
        compiled = _compiled_at(tmp_path)
        for outcome in (
            ExecutionOutcome(ok=False, note="timeout"),
            ExecutionOutcome(ok=False, note="runner crashed"),
            ExecutionOutcome(ok=True),  # ran, but produced no grade
        ):
            result = normalize(_case(), compiled, outcome)
            assert result.overall is not CheckOutcome.PASS
            assert not result.is_evidence


class TestBackendUnavailable:
    """Fukasawa must be fully usable without smevals installed."""

    def test_availability_is_feature_detection_not_an_import(self, monkeypatch):
        monkeypatch.setattr(adapter.shutil, "which", lambda name: None)
        assert adapter.backend_available() is False
        assert adapter.backend_version() == ""

    def test_execute_reports_unavailability_without_raising(self, tmp_path, monkeypatch):
        monkeypatch.setattr(adapter, "backend_available", lambda: False)
        outcome = adapter.execute(_compiled_at(tmp_path))
        assert not outcome.ok
        assert "not installed" in outcome.note

    def test_unavailable_backend_normalizes_to_not_executed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(adapter, "backend_available", lambda: False)
        monkeypatch.setattr(adapter, "backend_version", lambda: "")
        result = normalize(_case(), _compiled_at(tmp_path), ExecutionOutcome(ok=False, note="absent"))
        assert result.execution_status is ExecutionStatus.NOT_EXECUTED
        assert not result.is_evidence

    def test_full_slice_returns_a_native_result_with_no_backend(self, tmp_path, monkeypatch):
        monkeypatch.setattr(adapter, "backend_available", lambda: False)
        monkeypatch.setattr(adapter, "backend_version", lambda: "")
        result = adapter.evaluate(
            _case(), tmp_path / "ws",
            artifact_path=_artifact(tmp_path, GOOD_HANDOFF), declared_depth=2,
        )
        assert result.execution_status is ExecutionStatus.NOT_EXECUTED
        assert result.case_id == "poc-case"

    def test_importing_the_adapter_does_not_import_smevals(self):
        # The peer-tool constraint, mechanically enforced.
        assert "smevals" not in sys.modules
        source = (ROOT / "src" / "governance" / "smevals_adapter.py").read_text(encoding="utf-8")
        assert "import smevals" not in source
        assert "from smevals" not in source


class TestGovernanceBoundary:
    """The adapter supplies evidence; it never decides."""

    def test_it_files_candidates_not_non_conformance_records(self, tmp_path):
        compiled = _compiled_at(tmp_path)
        _write_grade(compiled, {
            "outcome": "fail",
            "checks": [{"checker": "c", "outcome": "fail", "notes": "missing next action"}],
        })
        result = normalize(_case(), compiled, ExecutionOutcome(ok=True))
        assert result.non_conformance_candidates
        assert result.requires_human_review

    def test_the_adapter_makes_no_promotion_decision(self):
        source = (ROOT / "src" / "governance" / "smevals_adapter.py").read_text(encoding="utf-8")
        for forbidden in ("promote(", "record_promotion", "PromotionRefusedError"):
            assert forbidden not in source, f"adapter must not touch promotion ({forbidden})"

    def test_the_adapter_does_not_write_to_the_ledger(self):
        source = (ROOT / "src" / "governance" / "smevals_adapter.py").read_text(encoding="utf-8")
        for forbidden in ("RunLedger", "save_eval_result", "save_non_conformance_record"):
            assert forbidden not in source, f"adapter must not persist on its own authority ({forbidden})"
