# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Phase 3 tests — promotion and persistence, the Gate D evidence.

Covers the state tests the release strategy asks for: the valid promotion path,
forbidden transitions, promotion blocked by findings, accepted non-blocking
risk, audit metadata, persisted resume, interrupted-write recovery, and
old-version load behaviour.

The invariants under most scrutiny:

* a workflow climbs **one step at a time** — declaring a workflow accountable
  does not make it so;
* **blocking findings cannot be accepted away**, only fixed;
* **promotion produces an artifact and never overwrites one**, because an audit
  may already cite what is there;
* **refusals are recorded**, so history shows what was declined and why.
"""

from pathlib import Path

import pytest
import yaml

from src.governance.workflow_promotion import (
    LAST_ENFORCED,
    PROMOTION_PATH,
    PromotionRefusedError,
    RiskAcceptanceRefusedError,
    accept_risk,
    assess,
    is_valid_transition,
    next_maturity,
    promote,
)
from src.governance.workflow_rules import validate_workflow
from src.runtime.ledger import RunLedger
from src.schemas.human_workflow import (
    AccountableWorkflow,
    HumanWorkflowDraft,
    WorkflowMaturity,
)

ROOT = Path(__file__).resolve().parent.parent
PILOT_DIR = ROOT / "examples" / "workflows" / "substack-publication"
OBSERVED = PILOT_DIR / "observed-workflow.yaml"
REPAIRED = PILOT_DIR / "repaired-workflow.yaml"


def _load(path: Path) -> HumanWorkflowDraft:
    return HumanWorkflowDraft.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@pytest.fixture()
def ledger(tmp_path) -> RunLedger:
    return RunLedger(str(tmp_path / "t.db"))


@pytest.fixture()
def repaired() -> HumanWorkflowDraft:
    """The pilot after repair: zero blocking findings, ready to promote."""
    return _load(REPAIRED)


@pytest.fixture()
def broken() -> HumanWorkflowDraft:
    """The pilot as observed: deliberately full of blocking findings."""
    return _load(OBSERVED)


# ----------------------------------------------------------------- the ladder


class TestLadder:
    def test_path_is_the_declared_eight_states(self):
        assert [m.value for m in PROMOTION_PATH] == [
            "OBSERVED", "MAPPED", "ACCOUNTABLE", "COOPERATION_READY",
            "COOPERATIVE_DESIGN_APPROVED", "RUNTIME_READY", "DEPLOYED", "VALIDATED",
        ]

    def test_one_step_at_a_time(self):
        assert next_maturity(WorkflowMaturity.OBSERVED) is WorkflowMaturity.MAPPED
        assert is_valid_transition(WorkflowMaturity.OBSERVED, WorkflowMaturity.MAPPED)

    def test_observed_cannot_jump_to_runtime_ready(self):
        # The explicit prohibition in the maturity contract.
        assert not is_valid_transition(
            WorkflowMaturity.OBSERVED, WorkflowMaturity.RUNTIME_READY
        )

    def test_no_skipping_anywhere_on_the_ladder(self):
        for i, current in enumerate(PROMOTION_PATH):
            for j, target in enumerate(PROMOTION_PATH):
                assert is_valid_transition(current, target) is (j == i + 1)

    def test_backwards_is_never_a_promotion(self):
        assert not is_valid_transition(
            WorkflowMaturity.ACCOUNTABLE, WorkflowMaturity.OBSERVED
        )

    def test_top_of_the_ladder_has_no_next_step(self):
        assert next_maturity(WorkflowMaturity.VALIDATED) is None


# --------------------------------------------------------------- risk acceptance


class TestRiskAcceptance:
    def test_non_blocking_finding_can_be_accepted_with_a_reason(self, ledger, repaired):
        report = validate_workflow(repaired)
        advisory = [f for f in report.findings if not f.blocking]
        assert advisory, "the repaired pilot should still carry advisory findings"
        acceptance = accept_risk(
            ledger, repaired.workflow_id, report, advisory[0].finding_id,
            "flaveon", "Known and tolerated; revisit if it causes a miss.",
        )
        assert acceptance.accepted_by == "flaveon"
        assert acceptance.rationale
        assert acceptance.accepted_at is not None
        assert advisory[0].accepted

    def test_blocking_finding_cannot_be_accepted_away(self, ledger, broken):
        # The gate would be a formality if a blocking finding could be waived.
        report = validate_workflow(broken)
        blocking = report.unresolved_blocking[0]
        with pytest.raises(RiskAcceptanceRefusedError, match="cannot be accepted"):
            accept_risk(
                ledger, broken.workflow_id, report, blocking.finding_id,
                "flaveon", "we are in a hurry",
            )

    def test_unknown_finding_is_refused(self, ledger, repaired):
        report = validate_workflow(repaired)
        with pytest.raises(RiskAcceptanceRefusedError, match="no finding"):
            accept_risk(ledger, "wf", report, "HW-999:nope", "flaveon", "why not")

    def test_acceptance_is_persisted_with_full_audit_metadata(self, ledger, repaired):
        report = validate_workflow(repaired)
        advisory = [f for f in report.findings if not f.blocking][0]
        accept_risk(ledger, repaired.workflow_id, report, advisory.finding_id,
                    "flaveon", "documented reason")
        rows = ledger.risk_acceptances_for(repaired.workflow_id)
        assert len(rows) == 1
        row = rows[0]
        assert row["accepted_by"] == "flaveon"
        assert row["rationale"] == "documented reason"
        assert row["accepted_at"] and row["rule_id"] and row["rule_version"]

    def test_acceptances_are_append_only(self, ledger, repaired):
        report = validate_workflow(repaired)
        advisory = [f for f in report.findings if not f.blocking][0]
        accept_risk(ledger, repaired.workflow_id, report, advisory.finding_id,
                    "flaveon", "reason")
        with pytest.raises(Exception, match="append-only"):
            ledger.db.execute("UPDATE risk_acceptances SET accepted_by = 'someone else'")


# -------------------------------------------------------------------- gating


class TestPromotionGating:
    def test_blocking_findings_prevent_promotion(self, ledger, broken):
        report = validate_workflow(broken)
        with pytest.raises(PromotionRefusedError, match="refused"):
            promote(ledger, broken, report, "flaveon")

    def test_assessment_names_what_is_missing(self, broken):
        report = validate_workflow(broken)
        result = assess(broken, report)
        assert not result.allowed
        assert result.target is WorkflowMaturity.MAPPED
        assert result.unmet
        assert any("HW-00" in c.detail for c in result.unmet)

    def test_refusal_is_recorded_in_the_audit_trail(self, ledger, broken):
        report = validate_workflow(broken)
        with pytest.raises(PromotionRefusedError):
            promote(ledger, broken, report, "flaveon")
        trail = ledger.workflow_promotions_for(broken.workflow_id)
        assert len(trail) == 1
        assert trail[0]["granted"] == 0
        assert trail[0]["detail"]
        # The refusal cites the evidence it was based on.
        assert trail[0]["report_id"]

    def test_promotion_requires_a_named_person(self, ledger, repaired):
        report = validate_workflow(repaired)
        with pytest.raises(PromotionRefusedError, match="named person"):
            promote(ledger, repaired, report, "   ")

    def test_promotion_beyond_this_release_is_refused_with_a_reason(self, ledger, repaired):
        report = validate_workflow(repaired)
        ahead = repaired.model_copy(deep=True)
        ahead.maturity = WorkflowMaturity.ACCOUNTABLE
        with pytest.raises(PromotionRefusedError, match="cooperation assessment"):
            promote(ledger, ahead, report, "flaveon")

    def test_gates_are_enforced_only_through_runtime_ready(self, repaired):
        beyond = repaired.model_copy(deep=True)
        beyond.maturity = WorkflowMaturity.RUNTIME_READY
        assert assess(beyond, None).enforced is False
        assert LAST_ENFORCED is WorkflowMaturity.RUNTIME_READY

    def test_top_of_ladder_has_nothing_to_assess(self, repaired):
        top = repaired.model_copy(deep=True)
        top.maturity = WorkflowMaturity.VALIDATED
        result = assess(top, None)
        assert result.target is None and not result.allowed


# ------------------------------------------------------------ the happy path


class TestPromotionPath:
    def test_observed_to_mapped_advances_the_draft(self, ledger, repaired):
        report = validate_workflow(repaired)
        outcome = promote(ledger, repaired, report, "flaveon")
        assert outcome.to_maturity is WorkflowMaturity.MAPPED
        assert outcome.draft is not None and outcome.artifact is None
        assert outcome.draft.maturity is WorkflowMaturity.MAPPED
        # The source object handed in is not mutated behind the caller's back.
        assert repaired.maturity is WorkflowMaturity.OBSERVED

    def test_mapped_to_accountable_produces_an_artifact(self, ledger, repaired):
        report = validate_workflow(repaired)
        mapped = promote(ledger, repaired, report, "flaveon").draft
        outcome = promote(ledger, mapped, report, "flaveon")
        art = outcome.artifact
        assert isinstance(art, AccountableWorkflow)
        assert art.maturity is WorkflowMaturity.ACCOUNTABLE
        assert art.owners and art.steps and art.completion_contract
        assert outcome.draft is None

    def test_steps_travel_unchanged(self, ledger, repaired):
        report = validate_workflow(repaired)
        mapped = promote(ledger, repaired, report, "flaveon").draft
        art = promote(ledger, mapped, report, "flaveon").artifact
        assert [s.step_id for s in art.steps] == [s.step_id for s in repaired.steps]

    def test_artifact_declares_no_states_or_transitions(self, ledger, repaired):
        # Promotion resolves accountability; it does not flatten the work into
        # a runnable brief. That is export's job, in a later phase.
        report = validate_workflow(repaired)
        mapped = promote(ledger, repaired, report, "flaveon").draft
        art = promote(ledger, mapped, report, "flaveon").artifact
        dumped = art.model_dump()
        assert not {"states", "transitions", "initial_state"} & set(dumped)

    def test_lineage_records_the_versions_the_decision_was_made_under(self, ledger, repaired):
        report = validate_workflow(repaired)
        mapped = promote(ledger, repaired, report, "flaveon").draft
        art = promote(ledger, mapped, report, "flaveon").artifact
        lin = art.lineage
        assert lin.source_workflow_id == repaired.workflow_id
        assert lin.from_maturity is WorkflowMaturity.MAPPED
        assert lin.to_maturity is WorkflowMaturity.ACCOUNTABLE
        assert lin.promoted_by == "flaveon"
        assert lin.rule_set_version and lin.schema_version

    def test_accepted_risks_travel_onto_the_artifact(self, ledger, repaired):
        report = validate_workflow(repaired)
        advisory = [f for f in report.findings if not f.blocking]
        for f in advisory:
            accept_risk(ledger, repaired.workflow_id, report, f.finding_id,
                        "flaveon", "tolerated for now")
        mapped = promote(ledger, repaired, report, "flaveon").draft
        art = promote(ledger, mapped, report, "flaveon").artifact
        assert len(art.accepted_risks) == len(advisory)
        assert all(a.rationale and a.accepted_by for a in art.accepted_risks)

    def test_the_source_draft_survives_promotion_untouched(self, ledger, repaired):
        report = validate_workflow(repaired)
        ledger.save_workflow_draft(repaired)
        mapped = promote(ledger, repaired, report, "flaveon").draft
        promote(ledger, mapped, report, "flaveon")
        # The original draft record is still loadable at its own maturity.
        assert ledger.load_workflow_draft(repaired.workflow_id, "1") is not None


# ------------------------------------------------------------- immutability


class TestArtifactImmutability:
    def test_promoting_the_same_version_twice_is_refused_cleanly(self, ledger, repaired):
        report = validate_workflow(repaired)
        mapped = promote(ledger, repaired, report, "flaveon").draft
        promote(ledger, mapped, report, "flaveon")
        with pytest.raises(PromotionRefusedError, match="already been promoted"):
            promote(ledger, mapped, report, "flaveon")

    def test_a_bumped_version_promotes_and_the_earlier_one_survives(self, ledger, repaired):
        report = validate_workflow(repaired)
        mapped = promote(ledger, repaired, report, "flaveon").draft
        promote(ledger, mapped, report, "flaveon")
        revised = mapped.model_copy(deep=True)
        revised.version = "2"
        promote(ledger, revised, report, "flaveon")
        assert set(ledger.accountable_workflow_versions(repaired.workflow_id)) == {"1", "2"}
        assert ledger.load_accountable_workflow(repaired.workflow_id, "1").version == "1"

    def test_promotions_and_artifacts_are_append_only(self, ledger, repaired):
        report = validate_workflow(repaired)
        promote(ledger, repaired, report, "flaveon")
        with pytest.raises(Exception, match="append-only"):
            ledger.db.execute("UPDATE workflow_promotions SET granted = 0")
        with pytest.raises(Exception, match="append-only"):
            ledger.db.execute("DELETE FROM validation_reports")


# ------------------------------------------------------------- persistence


class TestPersistence:
    def test_draft_saves_reloads_and_resumes(self, ledger, repaired):
        ledger.save_workflow_draft(repaired)
        again = ledger.load_workflow_draft(repaired.workflow_id)
        assert again.workflow_id == repaired.workflow_id
        assert [s.step_id for s in again.steps] == [s.step_id for s in repaired.steps]

    def test_drafts_stay_editable_unlike_everything_derived_from_them(self, ledger, repaired):
        ledger.save_workflow_draft(repaired)
        repaired.known_pain_points.append("a newly noticed pain point")
        ledger.save_workflow_draft(repaired)
        assert "a newly noticed pain point" in ledger.load_workflow_draft(
            repaired.workflow_id
        ).known_pain_points

    def test_unknown_draft_raises_rather_than_returning_empty(self, ledger):
        with pytest.raises(KeyError, match="no draft stored"):
            ledger.load_workflow_draft("never-captured")

    def test_unknown_accountable_workflow_raises(self, ledger):
        with pytest.raises(KeyError, match="no accountable workflow"):
            ledger.load_accountable_workflow("never-promoted")

    def test_validation_report_round_trips(self, ledger, repaired):
        report = validate_workflow(repaired)
        report_id = ledger.save_validation_report(report)
        again = ledger.load_validation_report(report_id)
        assert len(again.findings) == len(report.findings)
        assert again.rule_set_version == report.rule_set_version

    def test_reports_are_queryable_per_workflow(self, ledger, repaired, broken):
        ledger.save_validation_report(validate_workflow(repaired))
        ledger.save_validation_report(validate_workflow(broken))
        assert len(ledger.validation_reports_for(repaired.workflow_id)) == 2

    def test_interrupted_write_leaves_no_phantom_promotion(self, ledger, repaired, monkeypatch):
        # The artifact is written before the audit row. If the process dies in
        # between, the trail shows no promotion — the safe direction to fail.
        report = validate_workflow(repaired)
        mapped = promote(ledger, repaired, report, "flaveon").draft
        before = len(ledger.workflow_promotions_for(repaired.workflow_id))

        def boom(*a, **k):
            raise RuntimeError("process died mid-promotion")

        monkeypatch.setattr(ledger, "record_workflow_promotion", boom)
        with pytest.raises(RuntimeError):
            promote(ledger, mapped, report, "flaveon")
        monkeypatch.undo()
        after = ledger.workflow_promotions_for(repaired.workflow_id)
        granted = [r for r in after if r["granted"] == 1 and r["to_maturity"] == "ACCOUNTABLE"]
        assert not granted, "a promotion must not appear granted if its audit row never landed"
        assert len(after) == before

    def test_old_version_drafts_still_load(self, ledger, repaired):
        # Contracts are additive within a major version, so a draft persisted
        # before newer optional fields existed must still load.
        stripped = repaired.model_dump(mode="json")
        stripped.pop("notes", None)
        stripped.pop("known_pain_points", None)
        revived = HumanWorkflowDraft.model_validate(stripped)
        ledger.save_workflow_draft(revived)
        assert ledger.load_workflow_draft(revived.workflow_id).schema_version == "1"


# ------------------------------------------------------------------- pilot


class TestPilotArtifacts:
    def test_repaired_pilot_has_no_blocking_findings(self, repaired):
        report = validate_workflow(repaired)
        assert report.promotion_ready
        assert not report.unresolved_blocking

    def test_observed_pilot_is_still_deliberately_broken(self, broken):
        # The repair must not have been applied to the validator fixture.
        assert not validate_workflow(broken).promotion_ready

    def test_shipped_accountable_artifact_is_valid_and_traceable(self):
        art = AccountableWorkflow.model_validate(
            yaml.safe_load((PILOT_DIR / "accountable-workflow.yaml").read_text(encoding="utf-8"))
        )
        assert art.maturity is WorkflowMaturity.ACCOUNTABLE
        assert art.lineage.source_workflow_id == "substack-publication"
        assert art.lineage.promoted_by
        assert art.owners and art.steps
        assert art.accepted_risks, "the pilot accepted its advisory findings"
        assert all(a.rationale for a in art.accepted_risks)
