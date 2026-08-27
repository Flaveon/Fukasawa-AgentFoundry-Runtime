# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Phase 1 contract tests — the Gate B evidence.

Covers what the release test strategy asks of contracts: required and optional
fields, enum stability, version fields, unknown-field policy, malformed ids,
invalid references, serialization round trips, and deterministic output.

Two tests here are tripwires rather than ordinary coverage:

* ``TestFrozenSchemaFingerprints`` pins the content hash of the existing
  example graphs. Graph and bundle signatures are computed over
  ``model_dump(mode="json")``, which **includes defaulted fields** — so adding
  even an optional field to ``GraphSpec`` would invalidate every ``.sig``
  sidecar in the field and break hash-pinned graph resume. If this test fails,
  a frozen schema was edited: stop and escalate (ADR-002).

* ``TestExportedJsonSchemaIsStable`` pins the exported JSON Schema surface.
  It is the substituted obligation for the cross-language requirement that was
  ruled not applicable in a Python-only repository (review defect D1).
"""

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from src.kernel.kernel import graph_fingerprint, load_graph
from src.schemas.cooperation import (
    CooperationAssessment,
    CooperativeWorkflow,
    ExecutorClass,
    ExecutorOverride,
    SafetyFloor,
    StepAssignment,
    SupervisionMode,
    AutomationReadiness,
)
from src.schemas.export_jsonschema import (
    EXPORTED_CONTRACTS,
    all_schemas,
    schema_json,
    write_schemas,
)
from src.schemas.findings import (
    FindingLocation,
    FindingType,
    RiskAcceptance,
    RuleRef,
    Severity,
    ValidationReport,
    WorkflowFinding,
)
from src.schemas.human_workflow import (
    SCHEMA_VERSION,
    AccountableWorkflow,
    HumanWorkflowDraft,
    PromotionLineage,
    Reversibility,
    StepCharacteristics,
    WorkflowMaturity,
    WorkflowStep,
)

ROOT = Path(__file__).resolve().parent.parent
PILOT = ROOT / "examples" / "workflows" / "substack-publication" / "observed-workflow.yaml"
EXAMPLE_GRAPHS = [
    ROOT / "examples" / "q2c-pipeline-graph.yaml",
    ROOT / "examples" / "oldowan-pipeline-graph.yaml",
]


def _finding(**kw) -> WorkflowFinding:
    """A minimal valid finding, overridable per test."""
    defaults = dict(
        finding_id="f-001",
        rule=RuleRef(rule_id="HW-003"),
        finding_type=FindingType.ACCOUNTABILITY,
        severity=Severity.ERROR,
        blocking=True,
        message="step 'publish-post' has no actor",
        location=FindingLocation(workflow_id="wf", step_id="publish-post", field="actor"),
        remediation="Name the person or role accountable for this step.",
    )
    return WorkflowFinding(**{**defaults, **kw})


def _lineage(**kw) -> PromotionLineage:
    """A minimal valid promotion lineage."""
    defaults = dict(
        source_workflow_id="wf",
        from_maturity=WorkflowMaturity.MAPPED,
        to_maturity=WorkflowMaturity.ACCOUNTABLE,
        promoted_by="operator",
    )
    return PromotionLineage(**{**defaults, **kw})


class TestDraftContract:
    def test_minimal_draft_is_valid_and_permissive(self):
        # A draft with nothing but an id and a name must be valid: capture is
        # never blocked by incompleteness.
        d = HumanWorkflowDraft(workflow_id="wf", name="W")
        assert d.maturity is WorkflowMaturity.OBSERVED
        assert d.schema_version == SCHEMA_VERSION
        assert d.steps == [] and d.entry_step is None

    def test_unknown_field_is_rejected(self):
        # A mistyped field silently ignored is invisible drift — forbid it.
        with pytest.raises(ValidationError):
            HumanWorkflowDraft(workflow_id="wf", name="W", trigge="typo")

    @pytest.mark.parametrize("bad", ["Not_A_Slug", "has space", "UPPER", "trailing-", "-lead", ""])
    def test_malformed_workflow_id_is_rejected(self, bad):
        with pytest.raises(ValidationError):
            HumanWorkflowDraft(workflow_id=bad, name="W")

    @pytest.mark.parametrize("bad", ["Step_One", "step one", "STEP", ""])
    def test_malformed_step_id_is_rejected(self, bad):
        with pytest.raises(ValidationError):
            WorkflowStep(step_id=bad, name="S")

    def test_step_lookup_and_ids(self):
        d = HumanWorkflowDraft(
            workflow_id="wf",
            name="W",
            steps=[WorkflowStep(step_id="a", name="A"), WorkflowStep(step_id="b", name="B")],
        )
        assert d.step("a").name == "A"
        assert d.step_ids() == {"a", "b"}
        assert d.entry_step.step_id == "a"
        with pytest.raises(KeyError):
            d.step("nope")

    def test_characteristics_default_to_unknown(self):
        # Unknown must be the default so an uncharacterized step is never
        # mistaken for one that is safe to automate.
        c = StepCharacteristics()
        assert all(v.value == "UNKNOWN" for v in c.model_dump().values())

    def test_round_trip_is_lossless(self):
        raw = yaml.safe_load(PILOT.read_text(encoding="utf-8"))
        d = HumanWorkflowDraft.model_validate(raw)
        again = HumanWorkflowDraft.model_validate(json.loads(d.model_dump_json()))
        assert again == d


class TestPilotFixture:
    """The pilot is a fixture: its defects are load-bearing, not bugs."""

    def test_pilot_loads(self):
        d = HumanWorkflowDraft.model_validate(yaml.safe_load(PILOT.read_text(encoding="utf-8")))
        assert d.workflow_id == "substack-publication"
        assert len(d.steps) == 8

    def test_pilot_still_contains_its_seeded_defects(self):
        # If someone "fixes" the pilot, the phase-2 rule fixtures lose their
        # subject. Assert the seeded defects survive.
        d = HumanWorkflowDraft.model_validate(yaml.safe_load(PILOT.read_text(encoding="utf-8")))
        ids = d.step_ids()
        refs = {n for s in d.steps for n in s.next_steps}
        assert refs - ids == {"promote-post"}, "HW-005 fixture (dangling ref) missing"
        assert any(not s.actor for s in d.steps), "HW-003 fixture (unowned step) missing"
        assert any(
            not s.decision_authority for s in d.steps
        ), "HW-004 fixture (no decision authority) missing"
        assert any(
            not e.owner for s in d.steps for e in s.exception_paths
        ), "HW-012 fixture (unowned exception) missing"
        assert any(not g.on_reject for g in d.gates), "HW-015 fixture (gate w/o reject) missing"
        assert d.unwritten_rules, "HW-013 fixture (unwritten rules) missing"
        assert any(
            s.characteristics.reversibility is Reversibility.IRREVERSIBLE for s in d.steps
        ), "safety-floor fixture (irreversible step) missing"


class TestFindingContract:
    def test_blocking_finding_blocks_until_fixed(self):
        f = _finding()
        assert f.blocking and not f.accepted and f.blocks_promotion

    def test_acceptance_requires_actor_and_rationale(self):
        with pytest.raises(ValidationError):
            RiskAcceptance(finding_id="f", rule=RuleRef(rule_id="HW-013"), accepted_by="", rationale="x")
        with pytest.raises(ValidationError):
            RiskAcceptance(finding_id="f", rule=RuleRef(rule_id="HW-013"), accepted_by="op", rationale="")

    def test_message_and_remediation_cannot_be_empty(self):
        with pytest.raises(ValidationError):
            _finding(message="")
        with pytest.raises(ValidationError):
            _finding(remediation="")

    @pytest.mark.parametrize("bad", ["hw-003", "HW-3", "HW-0033", "HX-003", "003"])
    def test_malformed_rule_id_is_rejected(self, bad):
        with pytest.raises(ValidationError):
            RuleRef(rule_id=bad)

    def test_report_promotion_gate(self):
        blocking = _finding(finding_id="f1")
        nonblocking = _finding(
            finding_id="f2", rule=RuleRef(rule_id="HW-013"),
            severity=Severity.WARNING, blocking=False,
            finding_type=FindingType.REASONING_LOAD,
        )
        report = ValidationReport(workflow_id="wf", findings=[blocking, nonblocking])
        assert not report.promotion_ready
        assert report.unresolved_blocking == [blocking]
        assert len(report.by_severity(Severity.WARNING)) == 1

    def test_clean_report_is_promotion_ready(self):
        assert ValidationReport(workflow_id="wf").promotion_ready

    def test_nonblocking_findings_never_gate_promotion(self):
        report = ValidationReport(
            workflow_id="wf",
            findings=[
                _finding(
                    finding_id="f2", rule=RuleRef(rule_id="HW-014"),
                    severity=Severity.WARNING, blocking=False,
                    finding_type=FindingType.INFORMATION,
                )
            ],
        )
        assert report.promotion_ready

    def test_accepting_a_finding_clears_it_from_the_gate(self):
        f = _finding(blocking=False, severity=Severity.WARNING)
        assert not f.blocks_promotion
        f.acceptance = RiskAcceptance(
            finding_id=f.finding_id, rule=f.rule, accepted_by="operator",
            rationale="Known and tolerated for the pilot.",
        )
        assert f.accepted and not f.blocks_promotion

    def test_findings_locate_the_problem(self):
        f = _finding()
        assert f.location.step_id == "publish-post" and f.location.field == "actor"


class TestAccountableWorkflowContract:
    def test_promotion_requires_resolved_essentials(self):
        # trigger, owners, steps, and completion contract are mandatory here —
        # the blocking rules must be resolved before this artifact can exist.
        with pytest.raises(ValidationError):
            AccountableWorkflow(
                workflow_id="wf", name="W", purpose="p", trigger="",
                owners=["op"], steps=[WorkflowStep(step_id="a", name="A")],
                completion_contract="done when X", lineage=_lineage(),
            )
        with pytest.raises(ValidationError):
            AccountableWorkflow(
                workflow_id="wf", name="W", purpose="p", trigger="t",
                owners=[], steps=[WorkflowStep(step_id="a", name="A")],
                completion_contract="done when X", lineage=_lineage(),
            )
        with pytest.raises(ValidationError):
            AccountableWorkflow(
                workflow_id="wf", name="W", purpose="p", trigger="t",
                owners=["op"], steps=[], completion_contract="done when X",
                lineage=_lineage(),
            )

    def test_valid_accountable_workflow_carries_lineage(self):
        aw = AccountableWorkflow(
            workflow_id="wf", name="W", purpose="p", trigger="t", owners=["op"],
            steps=[WorkflowStep(step_id="a", name="A")],
            completion_contract="done when X is published",
            lineage=_lineage(),
        )
        assert aw.maturity is WorkflowMaturity.ACCOUNTABLE
        assert aw.lineage.promoted_by == "operator"
        assert aw.lineage.to_maturity is WorkflowMaturity.ACCOUNTABLE
        assert aw.step("a").name == "A"

    def test_it_declares_no_states_or_transitions(self):
        # Review defect D3: this must not become a second WorkflowBrief.
        # Flattening to states/transitions belongs to export, not promotion.
        fields = set(AccountableWorkflow.model_fields)
        assert not fields & {"states", "transitions", "initial_state", "task_depth"}


class TestExecutorClassStability:
    def test_all_seven_classes_exist(self):
        # Persisted, exported values — adding one later must not be breaking,
        # so all seven ship now even though the UI emphasizes a subset.
        assert {e.value for e in ExecutorClass} == {
            "HUMAN_ONLY",
            "HUMAN_LED_AI_ASSISTED",
            "AGENT_PREPARED_HUMAN_APPROVED",
            "AGENT_EXECUTED_HUMAN_SUPERVISED",
            "DETERMINISTIC_AUTOMATION",
            "BOUNDED_AUTONOMOUS_AGENT",
            "NOT_READY_FOR_AUTOMATION",
        }

    def test_maturity_ladder_is_stable_and_ordered(self):
        assert [m.value for m in WorkflowMaturity] == [
            "OBSERVED", "MAPPED", "ACCOUNTABLE", "COOPERATION_READY",
            "COOPERATIVE_DESIGN_APPROVED", "RUNTIME_READY", "DEPLOYED", "VALIDATED",
        ]

    def test_autonomy_rank_is_total_and_unique(self):
        ranks = [e.autonomy_rank for e in ExecutorClass]
        assert len(set(ranks)) == len(ranks), "ranks must be unique to compare overrides"

    def test_not_ready_is_the_least_autonomous(self):
        assert ExecutorClass.NOT_READY_FOR_AUTOMATION.autonomy_rank == min(
            e.autonomy_rank for e in ExecutorClass
        )

    def test_bounded_autonomous_is_the_most_autonomous(self):
        assert ExecutorClass.BOUNDED_AUTONOMOUS_AGENT.autonomy_rank == max(
            e.autonomy_rank for e in ExecutorClass
        )

    def test_deterministic_automation_ranks_below_supervised_agent(self):
        # A script has no latitude to misjudge, so it is safer than an agent
        # acting under observation. Ranking must follow delegated judgment,
        # not absence of humans.
        assert (
            ExecutorClass.DETERMINISTIC_AUTOMATION.autonomy_rank
            < ExecutorClass.AGENT_EXECUTED_HUMAN_SUPERVISED.autonomy_rank
        )

    def test_human_authorization_and_agent_involvement_flags(self):
        assert ExecutorClass.AGENT_PREPARED_HUMAN_APPROVED.requires_human_authorization
        assert not ExecutorClass.BOUNDED_AUTONOMOUS_AGENT.requires_human_authorization
        assert ExecutorClass.HUMAN_LED_AI_ASSISTED.involves_agent
        assert not ExecutorClass.HUMAN_ONLY.involves_agent
        assert not ExecutorClass.DETERMINISTIC_AUTOMATION.involves_agent


class TestCooperationContract:
    def _assessment(self, **kw) -> CooperationAssessment:
        defaults = dict(
            assessment_id="a-001", workflow_id="wf", step_id="publish-post",
            recommended_executor=ExecutorClass.AGENT_PREPARED_HUMAN_APPROVED,
            rationale="Irreversible effect: a human must authorize.",
            assessed_factors=StepCharacteristics(reversibility=Reversibility.IRREVERSIBLE),
            safety_floor=SafetyFloor.IRREVERSIBLE,
            supervision_mode=SupervisionMode.APPROVAL_REQUIRED,
            automation_readiness=AutomationReadiness.PILOT,
        )
        return CooperationAssessment(**{**defaults, **kw})

    def test_assessment_echoes_the_factors_it_judged(self):
        a = self._assessment()
        assert a.assessed_factors.reversibility is Reversibility.IRREVERSIBLE
        assert a.is_floored
        assert a.effective_executor is ExecutorClass.AGENT_PREPARED_HUMAN_APPROVED

    def test_override_wins_and_requires_rationale_and_actor(self):
        a = self._assessment()
        a.override = ExecutorOverride(
            overridden_to=ExecutorClass.HUMAN_ONLY,
            rationale="Editor insists on doing this personally.",
            actor="operator",
        )
        assert a.effective_executor is ExecutorClass.HUMAN_ONLY
        with pytest.raises(ValidationError):
            ExecutorOverride(overridden_to=ExecutorClass.HUMAN_ONLY, rationale="", actor="op")
        with pytest.raises(ValidationError):
            ExecutorOverride(overridden_to=ExecutorClass.HUMAN_ONLY, rationale="r", actor="")

    def test_rank_comparison_can_express_the_one_directional_rule(self):
        # The contract must make the phase-4 safety rule checkable: an override
        # on a floored step may not increase autonomy.
        a = self._assessment()
        toward_human = ExecutorClass.HUMAN_ONLY
        toward_autonomy = ExecutorClass.BOUNDED_AUTONOMOUS_AGENT
        assert toward_human.autonomy_rank < a.recommended_executor.autonomy_rank
        assert toward_autonomy.autonomy_rank > a.recommended_executor.autonomy_rank

    def test_assignment_requires_human_owner_and_escalation(self):
        with pytest.raises(ValidationError):
            StepAssignment(
                step_id="a", executor_class=ExecutorClass.DETERMINISTIC_AUTOMATION,
                human_owner="", escalation_target="op",
            )
        with pytest.raises(ValidationError):
            StepAssignment(
                step_id="a", executor_class=ExecutorClass.DETERMINISTIC_AUTOMATION,
                human_owner="op", escalation_target="",
            )

    def test_fallback_defaults_toward_a_human(self):
        a = StepAssignment(
            step_id="a", executor_class=ExecutorClass.BOUNDED_AUTONOMOUS_AGENT,
            human_owner="op", escalation_target="op",
        )
        assert a.fallback_executor is ExecutorClass.HUMAN_ONLY

    def test_cooperative_workflow_approval_and_lookup(self):
        cw = CooperativeWorkflow(
            workflow_id="wf", name="W",
            assignments=[
                StepAssignment(
                    step_id="a", executor_class=ExecutorClass.HUMAN_ONLY,
                    human_owner="op", escalation_target="op",
                ),
                StepAssignment(
                    step_id="b", executor_class=ExecutorClass.AGENT_PREPARED_HUMAN_APPROVED,
                    human_owner="op", escalation_target="op", executor_identity="writer-agent",
                ),
            ],
        )
        assert not cw.approved
        assert cw.assignment("b").executor_identity == "writer-agent"
        assert [a.step_id for a in cw.agent_assigned_steps] == ["b"]
        with pytest.raises(KeyError):
            cw.assignment("missing")
        cw.approved_by = "operator"
        assert cw.approved

    def test_cooperative_workflow_requires_at_least_one_assignment(self):
        with pytest.raises(ValidationError):
            CooperativeWorkflow(workflow_id="wf", name="W", assignments=[])


class TestSchemaVersioning:
    def test_every_new_contract_carries_a_schema_version(self):
        for name, model in EXPORTED_CONTRACTS.items():
            if name in {"workflow-step", "step-assignment", "risk-acceptance"}:
                continue  # nested pieces version with their parent artifact
            assert "schema_version" in model.model_fields, f"{name} lacks schema_version"

    def test_schema_version_defaults_to_current(self):
        assert HumanWorkflowDraft(workflow_id="w", name="W").schema_version == SCHEMA_VERSION
        assert ValidationReport(workflow_id="w").schema_version == SCHEMA_VERSION


class TestExportedJsonSchemaIsStable:
    """The substituted D1 obligation: exported, documented, golden-pinned."""

    def test_every_contract_exports(self):
        schemas = all_schemas()
        assert set(schemas) == set(EXPORTED_CONTRACTS)
        for name, schema in schemas.items():
            assert schema.get("properties"), f"{name} exported no properties"

    def test_export_is_deterministic(self):
        assert schema_json("human-workflow-draft") == schema_json("human-workflow-draft")

    def test_unknown_contract_name_raises_with_the_roster(self):
        with pytest.raises(KeyError, match="available"):
            schema_json("no-such-contract")

    def test_enum_values_appear_in_exported_schema(self):
        # A generated consumer must see the exact persisted strings.
        blob = json.dumps(all_schemas())
        for value in ("BOUNDED_AUTONOMOUS_AGENT", "NOT_READY_FOR_AUTOMATION", "OBSERVED", "VALIDATED"):
            assert value in blob

    def test_write_schemas_emits_one_file_per_contract(self, tmp_path):
        written = write_schemas(tmp_path)
        assert len(written) == len(EXPORTED_CONTRACTS)
        assert all(p.exists() and p.read_text(encoding="utf-8").strip() for p in written)
        # Sorted-key JSON so the artifacts are diffable and stable.
        first = json.loads(written[0].read_text(encoding="utf-8"))
        assert isinstance(first, dict)


class TestFrozenSchemaFingerprints:
    """ADR-002 tripwire. A failure here means a frozen schema changed.

    Graph signatures and hash-pinned resumes are computed over the serialized
    model, defaults included. If this fails, do not update the expected hash —
    stop and escalate, because every ``.sig`` in the field just broke.
    """

    #: Recorded 2026-07-25 against the frozen GraphSpec. These are the exact
    #: bytes existing signatures were made over. Changing GraphSpec changes
    #: these — which is the breakage this test exists to catch.
    GOLDEN = {
        "q2c-pipeline-graph": "33baa1b0e17de253ccc990d86b784e1eebaf42938935c7db1d1dc9e8e2b90428",
        "oldowan-pipeline-graph": "dabc63992323ef8ee891cec06e957150e35cfa3ab1714bd744da17790253b9ce",
    }

    def test_example_graph_fingerprints_are_unchanged(self):
        actual = {
            (g := load_graph(p)).graph_id: graph_fingerprint(g) for p in EXAMPLE_GRAPHS
        }
        assert actual == self.GOLDEN, (
            "A frozen schema or example graph changed. Do NOT update these "
            "hashes to make the test pass: every .sig sidecar in the field and "
            "every hash-pinned graph resume just broke. Stop and escalate "
            "(ADR-002, directive §7)."
        )

    def test_fingerprint_is_sensitive_to_any_field_change(self):
        # Proves the tripwire actually trips: a one-field edit must change the
        # hash, which is why adding a field to GraphSpec is a breaking change.
        graph = load_graph(EXAMPLE_GRAPHS[0])
        before = graph_fingerprint(graph)
        mutated = graph.model_copy(update={"description": graph.description + " "})
        assert graph_fingerprint(mutated) != before
