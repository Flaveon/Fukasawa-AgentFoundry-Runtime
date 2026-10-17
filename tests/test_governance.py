# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Governance loop tests: eval running, maturity gating, NC pattern visibility.

The Phase 3 exit criteria, made executable:
* a process can be promoted or blocked based on evidence,
* non-conformance records produce concrete process changes,
* repeated failures are visible in the run ledger.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from src.foundry.generator import generate_packages
from src.foundry.validator import validate_package
from src.governance.evals import load_eval_case, run_eval_case
from src.governance.maturity import PromotionRefusedError, assess, promote
from src.runtime.handoff import write_handoff
from src.runtime.ledger import RunLedger
from src.runtime.state_machine import NonConformanceError, WorkflowRuntime
from src.schemas.eval_case import CheckCategory, CheckOutcome
from src.schemas.non_conformance import NonConformanceKind, ResolutionStatus

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_BRIEF = ROOT / "examples" / "q2c-production-handoff.yaml"
EVAL_DIR = ROOT / "examples" / "evals"


@pytest.fixture()
def world(tmp_path):
    """A complete little world: ledger, brief, generated packages, one full run."""
    ledger = RunLedger(tmp_path / "test.db")
    runtime = WorkflowRuntime(ledger)
    brief = runtime.load_brief(EXAMPLE_BRIEF)

    ws = tmp_path / "ws"
    for d in ("05_tasks/blocked", "11_outputs"):
        (ws / d).mkdir(parents=True)
    (ws / "doctrine.md").write_text("# Doctrine\n")
    packages, _ = generate_packages(brief, tmp_path / "pkgs", workspace_root=ws)
    writer = next(p for p in packages if p.name == "writer-agent")

    capsule, run = runtime.start(brief, brief_path=EXAMPLE_BRIEF)
    for state, ev in [
        ("DRAFT_READY", "~/substack/draft.md"),
        ("EDITOR_REVIEW", "submitted, 1500 words"),
        ("APPROVED", "editor sign-off"),
        ("PUBLISHED", "final.md -> ~/substack/"),
    ]:
        capsule = runtime.advance(brief, capsule, state, evidence=ev, run=run)
    runtime.add_output_artifact(run, "~/substack/draft.md", "draft", "writer-agent")
    runtime.record_observation(
        run, capsule, observer="writer-agent",
        observation="draft is 1500 words with sources",
        confidence="high", missing_evidence="none",
    )
    handoff_dir = tmp_path / "handoffs"
    write_handoff(run, brief, capsule, handoff_dir)
    return ledger, runtime, brief, writer, run, handoff_dir


def _run_all_cases(ledger, run, writer, handoff_dir):
    """Run the reviewed example cases against a real run; return results.

    Filters on ``case.reviewed``, which is what this helper always claimed to
    do and what the schema means by the flag — "only reviewed cases count
    toward promotion". Unreviewed cases in examples/ are drafts or fixtures for
    other machinery (e.g. the optional execution backend) and are not evidence
    about this runner.
    """
    results = []
    for case_file in sorted(EVAL_DIR.glob("*.yaml")):
        case = load_eval_case(case_file)
        if not case.reviewed:
            continue
        results.append(
            run_eval_case(
                case, ledger, run.run_id, package_dir=writer, handoff_dir=handoff_dir
            )
        )
    return results


class TestEvalRunner:
    def test_reviewed_cases_pass_against_real_run(self, world):
        ledger, runtime, brief, writer, run, handoff_dir = world
        results = _run_all_cases(ledger, run, writer, handoff_dir)
        assert len(results) == 3
        assert all(r.overall is CheckOutcome.PASS for r in results), [
            (c.category, c.outcome, c.evidence)
            for r in results
            for c in r.checks
            if c.outcome is CheckOutcome.FAIL
        ]

    def test_results_are_persisted(self, world):
        ledger, runtime, brief, writer, run, handoff_dir = world
        _run_all_cases(ledger, run, writer, handoff_dir)
        stored = ledger.eval_results_for(agent="writer-agent")
        assert len(stored) == 3

    def test_forbidden_claim_fails_observation_discipline(self, world, tmp_path):
        ledger, runtime, brief, writer, run, handoff_dir = world
        # Poison the handoff with a claim the writer does not own.
        handoff = handoff_dir / f"{run.run_id}.md"
        handoff.write_text(handoff.read_text() + "\n\nThe article was editor approved.\n")
        case = load_eval_case(EVAL_DIR / "q2c-writer-handoff.yaml")
        result = run_eval_case(
            case, ledger, run.run_id, package_dir=writer, handoff_dir=handoff_dir
        )
        obs = next(
            c for c in result.checks
            if c.category is CheckCategory.OBSERVATION_DISCIPLINE
        )
        assert obs.outcome is CheckOutcome.FAIL
        assert "editor approved" in obs.evidence

    def test_missing_handoff_fails_completeness(self, world, tmp_path):
        ledger, runtime, brief, writer, run, handoff_dir = world
        case = load_eval_case(EVAL_DIR / "q2c-writer-handoff.yaml")
        result = run_eval_case(
            case, ledger, run.run_id, package_dir=writer,
            handoff_dir=tmp_path / "empty",
        )
        assert result.overall is CheckOutcome.FAIL


def _package_snapshot(pkg: Path) -> dict:
    """Byte contents of every file a promotion can rewrite.

    Used to prove a refused or interrupted promotion left the package
    exactly as it found it — a comparison that only means something if it
    covers every file `promote()` touches, so the list here must track
    `_render_maturity_declarations`/`_render_mandatory_eval_checks`/
    `_render_learning_log_entry` in `src/governance/maturity.py`.
    """
    names = ("SKILL.md", "process_capsule.yaml", "manifest.json", "evals.yaml", "learning_log.md")
    return {name: (pkg / name).read_bytes() for name in names}


def _run_to_completion(runtime, brief) -> None:
    """Start and fully advance one extra run to PUBLISHED (and therefore
    RunStatus.COMPLETE), for tests that need several complete runs on the
    ledger."""
    capsule, run = runtime.start(brief)
    for state, ev in [
        ("DRAFT_READY", "~/substack/draft.md"),
        ("EDITOR_REVIEW", "submitted, 1500 words"),
        ("APPROVED", "editor sign-off"),
        ("PUBLISHED", "final.md -> ~/substack/"),
    ]:
        capsule = runtime.advance(brief, capsule, state, evidence=ev, run=run)


class TestPromotionIsAtomic:
    """Gate G findings F-M1 and F-M2: a refused promotion must not change the
    package, and an interrupted one must never leave it in a state that is
    neither the old maturity nor the new one."""

    def test_blank_reviewer_leaves_the_package_untouched(self, world):
        ledger, runtime, brief, writer, run, handoff_dir = world
        before = _package_snapshot(writer)
        with pytest.raises(PromotionRefusedError, match="human reviewer"):
            promote(writer, ledger, reviewed_by="   ")
        assert _package_snapshot(writer) == before
        assert ledger.promotions_for("writer-agent") == []

    def test_unmet_criteria_leaves_the_package_untouched(self, world):
        ledger, runtime, brief, writer, run, handoff_dir = world
        before = _package_snapshot(writer)
        with pytest.raises(PromotionRefusedError, match="unmet criteria"):
            promote(writer, ledger, reviewed_by="flaveon")
        assert _package_snapshot(writer) == before
        assert ledger.promotions_for("writer-agent") == []

    def test_missing_rationale_leaves_the_package_untouched(self, world):
        ledger, runtime, brief, writer, run, handoff_dir = world
        _run_all_cases(ledger, run, writer, handoff_dir)
        promote(writer, ledger, reviewed_by="flaveon")  # draft -> tested
        before = _package_snapshot(writer)
        before_rows = len(ledger.promotions_for("writer-agent"))
        with pytest.raises(PromotionRefusedError, match="rationale"):
            promote(writer, ledger, reviewed_by="flaveon")
        assert _package_snapshot(writer) == before
        assert len(ledger.promotions_for("writer-agent")) == before_rows

    def test_already_validated_leaves_the_package_untouched(self, world):
        ledger, runtime, brief, writer, run, handoff_dir = world
        # Hand-set rather than earned: cheaper than climbing the full ladder,
        # and `assess()` returns at Maturity.VALIDATED before reading
        # anything else, so this is enough to reach the refusal under test.
        manifest = json.loads((writer / "manifest.json").read_text())
        manifest["maturity"] = "validated"
        (writer / "manifest.json").write_text(json.dumps(manifest))
        before = _package_snapshot(writer)
        with pytest.raises(PromotionRefusedError, match="already"):
            promote(writer, ledger, reviewed_by="flaveon")
        assert _package_snapshot(writer) == before
        assert ledger.promotions_for("writer-agent") == []

    def test_ledger_write_failure_leaves_old_state_everywhere(self, world, monkeypatch):
        """F-M2 fault injection: the ledger commit happens before any file is
        touched, so a failure there must leave every file at the old
        maturity and record no promotion."""
        ledger, runtime, brief, writer, run, handoff_dir = world
        _run_all_cases(ledger, run, writer, handoff_dir)
        before = _package_snapshot(writer)

        def boom(*a, **k):
            raise RuntimeError("ledger write failed mid-promotion")

        monkeypatch.setattr(ledger, "record_promotion", boom)
        with pytest.raises(RuntimeError, match="ledger write failed"):
            promote(writer, ledger, reviewed_by="flaveon")
        monkeypatch.undo()

        assert _package_snapshot(writer) == before, (
            "no file may change before the ledger commits the promotion"
        )
        assert ledger.promotions_for("writer-agent") == []

    def test_partial_file_swap_after_ledger_commit_is_surfaced_not_silent(
        self, world, monkeypatch
    ):
        """F-M2's documented residual risk, proven rather than assumed: once
        the ledger row commits, a crash during the file swap can leave the
        ledger ahead of the files. `manifest.json` is swapped last for
        exactly this reason — the mismatch then shows up as a concrete,
        actionable validator finding on the very next check, instead of two
        maturities quietly disagreeing forever.
        """
        ledger, runtime, brief, writer, run, handoff_dir = world
        _run_all_cases(ledger, run, writer, handoff_dir)

        import src.governance.maturity as maturity_module

        real_replace = maturity_module.os.replace

        def flaky_replace(src, dst):
            if str(dst).endswith("manifest.json"):
                raise OSError("disk died right before the last replace")
            return real_replace(src, dst)

        monkeypatch.setattr(maturity_module.os, "replace", flaky_replace)
        with pytest.raises(OSError, match="disk died"):
            promote(writer, ledger, reviewed_by="flaveon")
        monkeypatch.undo()

        # The ledger already committed — it is the one step that cannot be
        # undone once it happens.
        history = ledger.promotions_for("writer-agent")
        assert len(history) == 1
        assert history[0]["to_maturity"] == "tested"

        # manifest.json never got swapped (it was last in line), so it still
        # disagrees with SKILL.md and process_capsule.yaml, which did. That
        # disagreement is exactly what the next validation reports — visible
        # and repairable, not a silent split.
        manifest = json.loads((writer / "manifest.json").read_text())
        assert manifest["maturity"] == "draft"
        findings = validate_package(writer)
        assert any("maturity disagrees" in f for f in findings), findings

        # Nothing is left half-written: the swap either fully replaced a
        # file or left the original untouched (plus the orphaned temp file
        # it never got to replace with).
        assert (writer / "SKILL.md").read_text().count("maturity: tested") == 1
        leftover_temp = list(writer.glob("manifest.json.promotion-tmp-*"))
        assert len(leftover_temp) == 1

    def test_rationale_reaches_the_promotions_ledger(self, world):
        """F-M3: the rationale text passed to a tested -> validated
        promotion must land in the append-only ledger row, not just the
        learning log."""
        ledger, runtime, brief, writer, run, handoff_dir = world
        _run_all_cases(ledger, run, writer, handoff_dir)
        promote(writer, ledger, reviewed_by="flaveon")  # draft -> tested

        # `world` already produced one COMPLETE run; two more clear the
        # "3+ complete runs" criterion for tested -> validated.
        _run_to_completion(runtime, brief)
        _run_to_completion(runtime, brief)

        rationale = "level 1 rejected: drafting needs a frame; level 2 adopted as-is"
        promote(writer, ledger, reviewed_by="flaveon", rationale=rationale)

        history = ledger.promotions_for("writer-agent")
        assert history[-1]["to_maturity"] == "validated"
        assert history[-1]["rationale"] == rationale


class TestMaturity:
    """Exit criterion: promoted or blocked based on evidence."""

    def test_draft_blocked_without_eval_evidence(self, world):
        ledger, runtime, brief, writer, run, handoff_dir = world
        report = assess(writer, ledger)
        assert not report.allowed
        with pytest.raises(PromotionRefusedError, match="unmet criteria"):
            promote(writer, ledger, reviewed_by="flaveon")

    def test_promotion_without_human_reviewer_is_refused(self, world):
        ledger, runtime, brief, writer, run, handoff_dir = world
        _run_all_cases(ledger, run, writer, handoff_dir)
        with pytest.raises(PromotionRefusedError, match="human reviewer"):
            promote(writer, ledger, reviewed_by="   ")

    def test_promotion_with_evidence_and_reviewer_succeeds(self, world):
        ledger, runtime, brief, writer, run, handoff_dir = world
        _run_all_cases(ledger, run, writer, handoff_dir)
        report = promote(writer, ledger, reviewed_by="flaveon")
        assert report.current.value == "tested"
        # Files agree after rewrite, and the validator confirms.
        from src.foundry.validator import validate_package
        assert validate_package(writer) == []
        # Promotion is in the append-only ledger with evidence.
        history = ledger.promotions_for("writer-agent")
        assert len(history) == 1
        assert history[0]["reviewed_by"] == "flaveon"
        assert "handoff_completeness" in history[0]["evidence"]
        # And in the learning log.
        assert "Promoted draft -> tested" in (writer / "learning_log.md").read_text()

    def test_validated_requires_rationale_and_runs(self, world):
        ledger, runtime, brief, writer, run, handoff_dir = world
        _run_all_cases(ledger, run, writer, handoff_dir)
        promote(writer, ledger, reviewed_by="flaveon")
        # Rationale gate fires first.
        with pytest.raises(PromotionRefusedError, match="rationale"):
            promote(writer, ledger, reviewed_by="flaveon")
        # With rationale but only 1 complete run: blocked on evidence.
        with pytest.raises(PromotionRefusedError, match="unmet criteria"):
            promote(writer, ledger, reviewed_by="flaveon", rationale="level 1 rejected: drafting needs a frame")

    def test_promotion_history_is_tamper_proof(self, world):
        ledger, runtime, brief, writer, run, handoff_dir = world
        _run_all_cases(ledger, run, writer, handoff_dir)
        promote(writer, ledger, reviewed_by="flaveon")
        db = sqlite3.connect(ledger.db_path)
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute("UPDATE promotions SET reviewed_by='nobody'")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute("DELETE FROM promotions")


class TestNonConformanceLoop:
    """Exit criteria: NC records produce process changes; repeats are visible."""

    def test_repeated_failures_fail_complexity_check_until_resolved(self, world):
        ledger, runtime, brief, writer, run, handoff_dir = world
        # Two missing-evidence breaches: a repeat.
        capsule2, run2 = runtime.start(brief)
        for _ in range(2):
            with pytest.raises(NonConformanceError):
                runtime.advance(brief, capsule2, "DRAFT_READY", evidence="", run=run2)
        from src.governance.checks import check_complexity_reduction
        result = check_complexity_reduction(ledger, brief.id)
        assert result.outcome is CheckOutcome.FAIL
        assert "repeated" in result.evidence

        # Resolving with a concrete process change flips the check.
        for record in ledger.non_conformance_records(open_only=True):
            record.resolution_status = ResolutionStatus.RESOLVED
            record.resolution_note = (
                "simplified: draft path auto-filled from pipeline output, "
                "removing the manual evidence entry step"
            )
            ledger.save_non_conformance_record(record)
        result = check_complexity_reduction(ledger, brief.id)
        assert result.outcome is CheckOutcome.PASS
        assert "process change" in result.evidence

    def test_repeats_are_visible_in_ledger_events(self, world):
        ledger, runtime, brief, writer, run, handoff_dir = world
        capsule2, run2 = runtime.start(brief)
        for _ in range(2):
            with pytest.raises(NonConformanceError):
                runtime.advance(brief, capsule2, "DRAFT_READY", evidence="", run=run2)
        events = ledger.history(brief.id)
        non_conforming = [e for e in events if not e["conforming"]]
        assert len(non_conforming) == 2
        # Same failure signature twice — the repeat is right there in the trail.
        assert (
            non_conforming[0]["note"] == non_conforming[1]["note"]
        )

    def test_resolution_without_note_is_impossible_via_schema(self):
        # The schema allows constructing resolved-without-note only if the
        # note field is explicitly given; the complexity check catches the
        # empty-note case (tested above). The capture CLI requires --note.
        from src.schemas.non_conformance import NonConformanceRecord
        with pytest.raises(Exception):
            NonConformanceRecord(
                id="ncr-x", workflow_id="w", capsule_id="c",
                kind=NonConformanceKind.OTHER, from_state="S", note="",
            )
