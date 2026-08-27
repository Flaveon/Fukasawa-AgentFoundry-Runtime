# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Phase 7 tests — the desktop lifecycle, the Gate F evidence.

Four layers, and the ordering is deliberate:

* ``TestImportLaw`` — the R3 guard, and the only one that matters most.
  It parses the source rather than importing it, so it runs **with or without a
  display**. Risk R3 is "the desktop grows a second validator"; a guard that
  skips on a developer's plain `pytest` is a guard that is not there. This is
  ADR-007 §2 made executable.
* ``TestServices`` — the lifecycle services, Tk-free, always run.
* ``TestParity`` — the desktop and the CLI reach the same answers, because
  they call the same functions. Gate F asks for parity; this is what proves it.
* ``TestView`` — behaviour of the widgets, display-gated. CI runs
  `xvfb-run -a pytest`, so these execute there; locally they skip.

The services are exercised against the real pilot and a real SQLite ledger in
tmp_path. Nothing is mocked.
"""

import ast
import shutil
from pathlib import Path

import pytest

from src.gui import services

ROOT = Path(__file__).resolve().parent.parent
PILOT_DIR = ROOT / "examples" / "workflows" / "substack-publication"
GUI_DIR = ROOT / "src" / "gui"


@pytest.fixture()
def draft(tmp_path) -> Path:
    """The pilot's repaired draft, copied so tests never touch the repo copy."""
    target = tmp_path / "repaired.yaml"
    shutil.copy(PILOT_DIR / "repaired-workflow.yaml", target)
    return target


@pytest.fixture()
def db(tmp_path) -> str:
    """A fresh ledger per test."""
    return str(tmp_path / "gui.db")


def accountable(draft: Path, db: str) -> None:
    """Walk the pilot up to ACCOUNTABLE."""
    assert services.promote_draft(draft, "tester", db).ok
    assert services.promote_draft(draft, "tester", db).ok


def assessed(draft: Path, db: str) -> None:
    """Reach stored assessments."""
    accountable(draft, db)
    assert services.assess_cooperation("substack-publication", db).ok


# --------------------------------------------------------------- the R3 guard


def _imported_modules(path: Path) -> set[str]:
    """Fully-qualified paths a file imports, from its AST.

    `from src.gui import services` resolves to ``src.gui.services``, not
    ``src.gui`` — otherwise a legal import of the service package reads as an
    import of the whole GUI package and the law cannot tell them apart.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


#: Every view module, discovered rather than listed. A hardcoded list is a
#: guard with a hole in it: the next view file someone adds is not covered by
#: it, and nothing fails to say so. Views are everything directly under
#: `src/gui/` — the `services/` package is the other side of the law.
VIEW_FILES = sorted(p.name for p in GUI_DIR.glob("*.py") if p.name != "__init__.py")

#: Every service module, discovered the same way and for the same reason.
SERVICE_FILES = sorted(
    f"services/{p.name}" for p in (GUI_DIR / "services").glob("*.py")
)


class TestImportLaw:
    """ADR-007 §2, enforced mechanically. Runs without a display."""

    #: What a view is allowed to reach for. Anything else is business logic
    #: creeping into the UI, which is exactly risk R3. Sibling views are
    #: allowed because one view composing another is still a view.
    VIEW_ALLOWED_PREFIXES = (
        "src.gui.services",
        "customtkinter",
        "tkinter",
    )

    def test_the_guard_covers_every_file(self):
        # The guard discovers its own subjects; this fails if src/gui/ is ever
        # restructured such that the globs find nothing.
        assert "app.py" in VIEW_FILES and "workflow_views.py" in VIEW_FILES
        assert "services/workflow.py" in SERVICE_FILES

    @pytest.mark.parametrize("name", VIEW_FILES)
    def test_views_import_only_services_stdlib_and_ctk(self, name):
        import sys

        siblings = tuple(f"src.gui.{v[:-3]}" for v in VIEW_FILES)
        offenders = []
        for module in _imported_modules(GUI_DIR / name):
            if module.startswith(self.VIEW_ALLOWED_PREFIXES + siblings):
                continue
            root = module.split(".")[0]
            if root in sys.stdlib_module_names:
                continue
            offenders.append(module)
        assert not offenders, (
            f"{name} imports {offenders}; a view may only reach "
            f"src.gui.services, stdlib, and customtkinter (ADR-007 §2)"
        )

    def test_views_never_import_the_runtime_directly(self):
        # The specific failure R3 describes: a view calling governance itself.
        for name in VIEW_FILES:
            modules = _imported_modules(GUI_DIR / name)
            for forbidden in (
                "src.governance",
                "src.runtime",
                "src.foundry",
                "src.schemas",
                "src.kernel",
            ):
                assert not any(m.startswith(forbidden) for m in modules), (
                    f"{name} imports {forbidden} directly — it must go through services"
                )

    @pytest.mark.parametrize("name", SERVICE_FILES)
    def test_services_never_import_widgets(self, name):
        modules = _imported_modules(GUI_DIR / name)
        for widget_lib in ("customtkinter", "tkinter"):
            assert not any(m.split(".")[0] == widget_lib for m in modules), (
                f"{name} imports {widget_lib}; services must stay Tk-free so the "
                f"runtime is usable with no display (ADR-007 §1)"
            )

    def test_services_do_not_print(self):
        # A service that prints has decided how to present something, which is
        # the view's job — and is invisible in a GUI anyway.
        for name in SERVICE_FILES:
            tree = ast.parse((GUI_DIR / name).read_text(encoding="utf-8"))
            calls = [
                n.func.id
                for n in ast.walk(tree)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            ]
            assert "print" not in calls, f"{name} prints; services return data"

    def test_no_classification_or_rule_logic_in_the_gui(self):
        # Directive §6.3: no rule, promotion decision, or executor
        # classification anywhere under src/gui/.
        for path in GUI_DIR.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            for marker in ("_base_recommendation", "_FLOOR_CEILINGS", "_SUPERVISION"):
                assert marker not in source, f"{path.name} contains {marker}"

    def test_the_package_split_kept_the_import_surface(self):
        # ADR-007's consequence note: services may become a package, but views'
        # import surface must not change.
        from src.gui.services import build_workflow, validate_brief_file  # noqa: F401

        assert services.validate_brief_file is not None
        assert services.build_workflow is not None


# ------------------------------------------------------------------ services


class TestServices:
    def test_create_writes_a_loadable_skeleton(self, tmp_path):
        out = tmp_path / "new.yaml"
        assert services.create_draft("demo-flow", out).ok
        assert out.exists()
        # Deliberately incomplete, but it must parse — capture comes first.
        result = services.validate_draft(out, str(tmp_path / "d.db"))
        assert result.ok
        assert not result.promotion_ready

    def test_create_refuses_a_bad_slug(self, tmp_path):
        result = services.create_draft("Not A Slug", tmp_path / "x.yaml")
        assert not result.ok
        assert "not a valid workflow id" in result.refusal

    def test_create_refuses_to_clobber(self, tmp_path):
        out = tmp_path / "new.yaml"
        services.create_draft("demo-flow", out)
        assert not services.create_draft("demo-flow", out).ok
        assert services.create_draft("demo-flow", out, overwrite=True).ok

    def test_import_and_reload_round_trip(self, draft, db):
        assert services.import_draft(draft, db).ok
        reloaded = services.reload_draft("substack-publication", db)
        assert reloaded.ok
        assert "8 step(s)" in reloaded.summary

    def test_import_saves_a_draft_with_blocking_findings(self, tmp_path):
        # Saving must never depend on the draft being complete.
        skeleton = tmp_path / "new.yaml"
        services.create_draft("new-flow", skeleton)
        db = str(tmp_path / "d.db")
        assert services.import_draft(skeleton, db).ok
        assert services.reload_draft("new-flow", db).ok

    def test_reload_of_an_unknown_workflow_is_a_refusal_not_a_crash(self, db):
        result = services.reload_draft("never-heard-of-it", db)
        assert not result.ok
        assert result.refusal

    def test_bad_files_come_back_as_messages(self, tmp_path, db):
        missing = services.validate_draft(tmp_path / "absent.yaml", db)
        assert not missing.ok and "No such file" in missing.refusal

        broken = tmp_path / "bad.yaml"
        broken.write_text("this: [is\n  broken\n", encoding="utf-8")
        assert "Not valid YAML" in services.validate_draft(broken, db).refusal

        wrong = tmp_path / "wrong.yaml"
        wrong.write_text("- a\n- list\n", encoding="utf-8")
        assert not services.validate_draft(wrong, db).ok

    def test_list_workflows(self, draft, db):
        assert services.list_workflows(db).workflows == []
        services.import_draft(draft, db)
        listing = services.list_workflows(db)
        assert [w.workflow_id for w in listing.workflows] == ["substack-publication"]

    def test_validate_reports_findings_without_failing(self, draft, db):
        result = services.validate_draft(draft, db)
        assert result.ok
        assert result.promotion_ready
        assert result.findings
        assert all(f.rule_id.startswith("HW-") for f in result.findings)

    def test_accept_records_and_survives_revalidation(self, draft, db):
        report = services.validate_draft(draft, db)
        advisory = next(f for f in report.findings if not f.blocking)
        assert services.accept_finding(draft, advisory.finding_id, "tester", "known", db).ok
        again = services.validate_draft(draft, db)
        assert [f.finding_id for f in again.findings if f.accepted] == [advisory.finding_id]

    def test_accept_requires_actor_and_reason(self, draft, db):
        report = services.validate_draft(draft, db)
        advisory = next(f for f in report.findings if not f.blocking)
        assert not services.accept_finding(draft, advisory.finding_id, "", "why", db).ok
        assert not services.accept_finding(draft, advisory.finding_id, "who", "", db).ok

    def test_accept_refuses_a_blocking_finding(self, tmp_path):
        skeleton = tmp_path / "new.yaml"
        services.create_draft("new-flow", skeleton)
        db = str(tmp_path / "d.db")
        report = services.validate_draft(skeleton, db)
        blocking = next(f for f in report.findings if f.blocking)
        result = services.accept_finding(skeleton, blocking.finding_id, "t", "no", db)
        assert not result.ok
        assert "blocking" in result.refusal

    def test_promotion_advances_rather_than_repeating(self, draft, db):
        # at_recorded_maturity, reached through the service layer.
        first = services.promote_draft(draft, "tester", db)
        second = services.promote_draft(draft, "tester", db)
        assert first.to_maturity == "MAPPED"
        assert second.to_maturity == "ACCOUNTABLE"

    def test_promotion_requires_an_actor(self, draft, db):
        assert not services.promote_draft(draft, "  ", db).ok

    def test_promotion_blocked_by_findings_reports_them(self, tmp_path):
        skeleton = tmp_path / "new.yaml"
        services.create_draft("new-flow", skeleton)
        result = services.promote_draft(skeleton, "tester", str(tmp_path / "d.db"))
        assert not result.ok
        assert result.blocking
        assert all(f.blocking for f in result.blocking)

    def test_assess_requires_an_accountable_workflow(self, db):
        result = services.assess_cooperation("never-promoted", db)
        assert not result.ok
        assert "ACCOUNTABLE" in result.refusal

    def test_assessment_matches_the_published_table(self, draft, db):
        accountable(draft, db)
        result = services.assess_cooperation("substack-publication", db)
        by_step = {a.step_id: a.effective_executor for a in result.assessments}
        assert by_step["publish-post"] == "AGENT_PREPARED_HUMAN_APPROVED"
        assert by_step["archive-notes"] == "DETERMINISTIC_AUTOMATION"
        assert by_step["review-and-approve"] == "HUMAN_ONLY"

    def test_override_toward_human_is_allowed(self, draft, db):
        assessed(draft, db)
        result = services.override_executor(
            "substack-publication", "archive-notes", "HUMAN_ONLY",
            "tester", "by hand for now", db,
        )
        assert result.ok
        by_step = {a.step_id: a for a in result.assessments}
        assert by_step["archive-notes"].effective_executor == "HUMAN_ONLY"
        assert by_step["archive-notes"].overridden

    def test_override_across_a_safety_floor_is_refused(self, draft, db):
        assessed(draft, db)
        result = services.override_executor(
            "substack-publication", "review-and-approve", "BOUNDED_AUTONOMOUS_AGENT",
            "tester", "skip the gate", db,
        )
        assert not result.ok
        assert "IRREVERSIBLE" in result.refusal

    def test_override_requires_actor_and_reason(self, draft, db):
        assessed(draft, db)
        assert not services.override_executor(
            "substack-publication", "archive-notes", "HUMAN_ONLY", "", "why", db
        ).ok
        assert not services.override_executor(
            "substack-publication", "archive-notes", "HUMAN_ONLY", "who", "", db
        ).ok

    def test_override_rejects_unknown_step_and_class(self, draft, db):
        assessed(draft, db)
        assert not services.override_executor(
            "substack-publication", "no-such-step", "HUMAN_ONLY", "t", "x", db
        ).ok
        assert not services.override_executor(
            "substack-publication", "archive-notes", "MAGIC_ROBOT", "t", "x", db
        ).ok

    def test_reassessment_carries_a_recorded_override(self, draft, db):
        assessed(draft, db)
        services.override_executor(
            "substack-publication", "archive-notes", "HUMAN_ONLY", "t", "by hand", db
        )
        again = services.assess_cooperation("substack-publication", db)
        assert "archive-notes" in again.carried_overrides
        by_step = {a.step_id: a for a in again.assessments}
        assert by_step["archive-notes"].effective_executor == "HUMAN_ONLY"
        assert by_step["archive-notes"].recommended_executor == "DETERMINISTIC_AUTOMATION"

    def test_build_requires_assessments(self, draft, db):
        accountable(draft, db)
        result = services.build_cooperative("substack-publication", db=db)
        assert not result.ok
        assert "assessments" in result.refusal

    def test_build_reports_steps_kept_human(self, draft, db):
        assessed(draft, db)
        result = services.build_cooperative("substack-publication", db=db)
        assert result.ok
        assert result.steps_kept_human
        assert not result.approved

    def test_export_refuses_an_unapproved_workflow(self, draft, db):
        assessed(draft, db)
        services.build_cooperative("substack-publication", db=db)
        result = services.export_brief("substack-publication", db=db)
        assert not result.ok
        assert "approved" in result.refusal

    def test_export_splits_the_gated_step(self, draft, db):
        assessed(draft, db)
        services.build_cooperative("substack-publication", "tester", db)
        result = services.export_brief("substack-publication", db=db)
        assert result.ok
        assert "publish-post-pending-approval" in result.states
        assert result.status == "approved"

    def test_export_writes_a_file_when_asked(self, draft, db, tmp_path):
        assessed(draft, db)
        services.build_cooperative("substack-publication", "tester", db)
        out = tmp_path / "brief.yaml"
        result = services.export_brief("substack-publication", out, db)
        assert result.written_path == str(out)

        from src.runtime.state_machine import WorkflowRuntime

        assert WorkflowRuntime.load_brief(out).id == "substack-publication"

    def test_lifecycle_status_never_refuses(self, db):
        result = services.lifecycle_status("never-heard-of-it", db)
        assert result.ok
        assert all(not s.present for s in result.stages)

    def test_lifecycle_status_tracks_progress(self, draft, db):
        def reached():
            return {s.stage: s.present for s in services.lifecycle_status(
                "substack-publication", db
            ).stages}

        assert not reached()["accountable"]
        accountable(draft, db)
        assert reached()["accountable"]
        assert not reached()["assessed"]
        services.assess_cooperation("substack-publication", db)
        assert reached()["assessed"]

    def test_every_stage_is_reported(self, db):
        result = services.lifecycle_status("anything", db)
        assert [s.stage for s in result.stages] == list(services.STAGES)


# ------------------------------------------------------------- step editor
#
# §16.3. The editor's whole claim is that it is *guided* — that the advice
# beside a box is the sentence the validator will use if the box is wrong.
# These tests are mostly about that claim, and about not losing work.


class TestStepEditorService:
    """The service behind the guided step editor."""

    def test_every_cited_rule_exists_in_the_registry(self):
        # The field→rule map is presentation, so nothing else would catch a
        # citation left pointing at a retired or renumbered rule.
        from src.governance.workflow_rules import RULES

        cited = {g.rule_id for g in services.step_field_guidance() if g.rule_id}
        assert cited <= set(RULES), f"editor cites unknown rules: {cited - set(RULES)}"

    def test_guidance_quotes_the_live_remediation(self):
        from src.governance.workflow_rules import RULES

        actor = next(g for g in services.step_field_guidance() if g.name == "actor")
        assert actor.rule_id == "HW-003"
        assert RULES["HW-003"].remediation in actor.hint
        assert actor.blocking is True

    def test_every_field_has_a_kind_the_view_can_render(self):
        kinds = {g.kind for g in services.step_field_guidance()}
        assert kinds <= {"text", "lines", "records", "choice"}

    def test_choice_fields_offer_every_contract_value(self):
        from src.schemas.human_workflow import RiskLevel

        risk = next(g for g in services.step_field_guidance() if g.name == "risk")
        assert risk.choices == [m.value for m in RiskLevel]

    def test_step_id_is_not_editable(self):
        # Renaming it from a form would silently break next_steps, exception
        # paths and gate references that point at it.
        assert "step_id" not in {g.name for g in services.step_field_guidance()}

    def test_read_defaults_to_the_first_step(self, draft):
        result = services.read_step(draft)
        assert result.ok
        assert result.step.step_id == result.step_ids[0]

    def test_read_reports_only_this_step_s_findings(self, tmp_path):
        skeleton = tmp_path / "new.yaml"
        services.create_draft("new-flow", skeleton)
        result = services.read_step(skeleton)
        assert result.ok
        assert result.step.findings
        assert all(f.location == result.step.step_id for f in result.step.findings)

    def test_read_refuses_an_unknown_step(self, draft):
        result = services.read_step(draft, "no-such-step")
        assert not result.ok
        assert "no-such-step" in result.refusal
        assert result.step_ids  # still tells the operator what does exist

    def test_read_of_a_bad_file_is_a_message_not_a_crash(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("steps: [", encoding="utf-8")
        assert not services.read_step(bad).ok

    def test_editing_a_field_fixes_its_finding(self, tmp_path):
        skeleton = tmp_path / "new.yaml"
        services.create_draft("new-flow", skeleton)
        db = str(tmp_path / "d.db")
        opened = services.read_step(skeleton, db=db)
        assert any(f.rule_id == "HW-003" for f in opened.step.findings)

        saved = services.write_step(
            skeleton, opened.step.step_id, {"actor": "the editor"}, db
        )
        assert saved.ok
        assert not any(f.rule_id == "HW-003" for f in saved.step.findings)

    def test_a_save_round_trips_every_field_unchanged(self, draft, db):
        opened = services.read_step(draft, db=db)
        saved = services.write_step(draft, opened.step.step_id, opened.step.values, db)
        assert saved.ok
        assert saved.step.values == opened.step.values

    def test_records_round_trip_through_text(self, draft, db):
        opened = services.read_step(draft, "publish-post", db=db)
        text = opened.step.values["outputs"]
        assert services.SEPARATOR in text
        saved = services.write_step(draft, "publish-post", {"outputs": text}, db)
        assert saved.ok
        assert saved.step.values["outputs"] == text

    def test_a_partial_record_line_keeps_what_was_known(self, tmp_path):
        skeleton = tmp_path / "new.yaml"
        services.create_draft("new-flow", skeleton)
        db = str(tmp_path / "d.db")
        step = services.read_step(skeleton, db=db).step.step_id
        saved = services.write_step(
            skeleton, step, {"exception_paths": "the source is unreachable"}, db
        )
        assert saved.ok
        assert "the source is unreachable" in saved.step.values["exception_paths"]

    def test_an_ambiguous_required_flag_is_refused_not_guessed(self, tmp_path):
        skeleton = tmp_path / "new.yaml"
        services.create_draft("new-flow", skeleton)
        db = str(tmp_path / "d.db")
        step = services.read_step(skeleton, db=db).step.step_id
        result = services.write_step(
            skeleton, step, {"inputs": "a brief | the editor | maybe"}, db
        )
        assert not result.ok
        assert "maybe" in result.refusal
        # And the file was not touched.
        assert "maybe" not in skeleton.read_text(encoding="utf-8")

    def test_an_edit_that_breaks_the_contract_is_refused(self, draft, db):
        opened = services.read_step(draft, db=db)
        before = draft.read_text(encoding="utf-8")
        result = services.write_step(
            draft, opened.step.step_id, {"judgment_load": "ENORMOUS"}, db
        )
        assert not result.ok
        assert draft.read_text(encoding="utf-8") == before, "a refused edit wrote anyway"

    def test_a_save_backs_the_file_up_first(self, draft, db):
        before = draft.read_text(encoding="utf-8")
        saved = services.write_step(draft, "publish-post", {"notes": "checked"}, db)
        assert saved.ok
        assert Path(saved.backup_path).read_text(encoding="utf-8") == before
        assert "not preserved" in saved.summary

    def test_a_save_reaches_the_ledger(self, draft, db):
        services.write_step(draft, "publish-post", {"notes": "from the editor"}, db)
        assert services.reload_draft("substack-publication", db).ok

    def test_choice_fields_persist_to_the_characteristics_block(self, draft, db):
        saved = services.write_step(draft, "publish-post", {"risk": "HIGH"}, db)
        assert saved.ok
        assert saved.step.values["risk"] == "HIGH"
        assert services.read_step(draft, "publish-post", db=db).step.values["risk"] == "HIGH"

    def test_editing_characteristics_moves_the_cooperation_recommendation(
        self, tmp_path, draft, db
    ):
        # The reason characteristics are editable at all: they decide who may
        # execute the step. An editor that could not reach them would leave the
        # most consequential fields to YAML. `archive-notes` is the pilot's one
        # fully automated step, so recording that it is in fact irreversible and
        # high-risk should pull it back toward a person — which is the whole
        # safety-floor mechanism, reached from a form.
        accountable(draft, db)
        before = {
            a.step_id: a.effective_executor
            for a in services.assess_cooperation("substack-publication", db).assessments
        }
        assert before["archive-notes"] == "DETERMINISTIC_AUTOMATION"
        services.write_step(
            draft, "archive-notes", {"risk": "HIGH", "reversibility": "IRREVERSIBLE"}, db
        )
        after_draft = tmp_path / "after.yaml"
        after_draft.write_text(draft.read_text(encoding="utf-8"), encoding="utf-8")
        after_db = str(tmp_path / "after.db")
        accountable(after_draft, after_db)
        after = {
            a.step_id: a.effective_executor
            for a in services.assess_cooperation("substack-publication", after_db).assessments
        }
        assert after["archive-notes"] != before["archive-notes"]
        # And it moved toward the human, never away.
        assert after["archive-notes"] in {
            "HUMAN_ONLY",
            "HUMAN_LED_AI_ASSISTED",
            "AGENT_PREPARED_HUMAN_APPROVED",
            "NOT_READY_FOR_AUTOMATION",
        }


# ------------------------------------------------------- versions and grouping


class TestVisibleVersions:
    """§16.14 — the rule and schema versions a decision was made under."""

    def test_validation_carries_the_rule_set_version(self, draft, db):
        from src.schemas.findings import RULE_SET_VERSION

        result = services.validate_draft(draft, db)
        assert result.rule_set_version == RULE_SET_VERSION
        assert result.schema_version

    def test_lifecycle_carries_the_versions_and_the_maturity(self, draft, db):
        accountable(draft, db)
        result = services.lifecycle_status("substack-publication", db)
        assert result.maturity == "ACCOUNTABLE"
        assert result.rule_set_version
        assert result.schema_version

    def test_maturity_is_empty_for_an_unknown_workflow(self, db):
        assert services.lifecycle_status("never-seen", db).maturity == ""

    def test_maturity_comes_from_the_ledger_not_the_file(self, tmp_path, db):
        # A maturity typed into the YAML by hand must not make the status lie.
        skeleton = tmp_path / "new.yaml"
        services.create_draft("new-flow", skeleton)
        text = skeleton.read_text(encoding="utf-8").replace(
            "maturity: OBSERVED", "maturity: RUNTIME_READY"
        )
        skeleton.write_text(text, encoding="utf-8")
        services.import_draft(skeleton, db)
        # The draft records what it claims, but nothing was promoted, so no
        # accountable artifact exists to vouch for it.
        result = services.lifecycle_status("new-flow", db)
        assert [s.stage for s in result.stages if s.present] == ["draft"]


class TestFindingGrouping:
    """§16.4 — findings grouped by severity and workflow location."""

    def test_findings_carry_their_grouping_keys(self, draft, db):
        findings = services.validate_draft(draft, db).findings
        assert all(f.severity in {"ERROR", "WARNING", "INFO"} for f in findings)
        assert all(f.finding_type for f in findings)

    def test_severity_groups_are_contiguous_and_worst_first(self, tmp_path):
        skeleton = tmp_path / "new.yaml"
        services.create_draft("new-flow", skeleton)
        findings = services.validate_draft(skeleton, str(tmp_path / "d.db")).findings
        order = ["ERROR", "WARNING", "INFO"]
        seen = [f.severity for f in findings]
        assert seen == sorted(seen, key=order.index), "severity groups are interleaved"

    def test_locations_are_contiguous_within_a_severity(self, tmp_path):
        skeleton = tmp_path / "new.yaml"
        services.create_draft("new-flow", skeleton)
        findings = services.validate_draft(skeleton, str(tmp_path / "d.db")).findings
        for severity in {f.severity for f in findings}:
            locations = [f.location for f in findings if f.severity == severity]
            assert locations == sorted(locations), f"{severity} locations interleaved"


# -------------------------------------------------------------------- parity


class TestParity:
    """The desktop and the CLI reach the same answers (Gate F).

    Not by comparing implementations — by both calling the same governance
    functions. These tests would catch a future change that gave one surface
    its own copy of a rule.
    """

    def test_assessment_matches_the_cli(self, draft, db, tmp_path):
        from typer.testing import CliRunner

        from src.cli import app

        cli_db = str(tmp_path / "cli.db")
        runner = CliRunner()
        for _ in range(2):
            runner.invoke(app, ["workflow", "promote", str(draft), "--by", "t", "--db", cli_db])
        cli_out = runner.invoke(
            app, ["workflow", "assess-cooperation", "substack-publication", "--db", cli_db, "--json"]
        )
        import json

        cli_rows = {
            a["step_id"]: a["effective_executor"]
            for a in json.loads(cli_out.output)["assessments"]
        }

        accountable(draft, db)
        gui = services.assess_cooperation("substack-publication", db)
        gui_rows = {a.step_id: a.effective_executor for a in gui.assessments}

        assert gui_rows == cli_rows

    def test_export_matches_the_cli(self, draft, db, tmp_path):
        import json

        from typer.testing import CliRunner

        from src.cli import app

        cli_db = str(tmp_path / "cli.db")
        runner = CliRunner()
        for _ in range(2):
            runner.invoke(app, ["workflow", "promote", str(draft), "--by", "t", "--db", cli_db])
        runner.invoke(app, ["workflow", "assess-cooperation", "substack-publication", "--db", cli_db])
        runner.invoke(
            app,
            ["workflow", "build-cooperative", "substack-publication", "--db", cli_db,
             "--approve-by", "t"],
        )
        cli_out = runner.invoke(
            app, ["workflow", "export-agent-brief", "substack-publication", "--db", cli_db, "--json"]
        )
        cli = json.loads(cli_out.output)

        assessed(draft, db)
        services.build_cooperative("substack-publication", "t", db)
        gui = services.export_brief("substack-publication", db=db)

        assert gui.states == cli["states"]
        assert gui.transition_count == cli["transitions"]
        assert [a.agent_name for a in gui.agents] == [a["agent_name"] for a in cli["agents"]]
        assert gui.steps_kept_human == cli["steps_kept_human"]

    def test_both_surfaces_refuse_the_same_override(self, draft, db, tmp_path):
        from typer.testing import CliRunner

        from src.cli import app

        cli_db = str(tmp_path / "cli.db")
        runner = CliRunner()
        for _ in range(2):
            runner.invoke(app, ["workflow", "promote", str(draft), "--by", "t", "--db", cli_db])
        runner.invoke(app, ["workflow", "assess-cooperation", "substack-publication", "--db", cli_db])
        cli_result = runner.invoke(
            app,
            ["workflow", "assess-cooperation", "substack-publication", "--db", cli_db,
             "--override", "review-and-approve=BOUNDED_AUTONOMOUS_AGENT",
             "--by", "t", "--why", "no"],
        )

        assessed(draft, db)
        gui_result = services.override_executor(
            "substack-publication", "review-and-approve", "BOUNDED_AUTONOMOUS_AGENT",
            "t", "no", db,
        )

        assert cli_result.exit_code == 3
        assert not gui_result.ok
        assert "IRREVERSIBLE" in gui_result.refusal


# ---------------------------------------------------------------- the view


def pump(tab, captured: list, timeout: float = 5.0) -> None:
    """Wait for a worker to deliver, draining the queue directly.

    Deliberately does **not** spin ``window.update()``. Hammering ``update()``
    in a tight loop is a test-only pathology — real code runs ``mainloop()`` —
    and under Xvfb it segfaulted inside Tk's event dispatch, because the loop
    processes queued events against action buttons the view had already
    destroyed and rebuilt.

    Draining the queue is also the more honest test: it exercises the actual
    mechanism (worker → queue → ``drain`` → callback) rather than relying on
    the poller's timer to have fired within an arbitrary window. ``drain`` is
    public for exactly this reason.
    """
    import time

    deadline = time.monotonic() + timeout
    while not captured and time.monotonic() < deadline:
        time.sleep(0.01)
        tab.drain()


@pytest.fixture(scope="module")
def _shared_window():
    """One Tk root for this whole module, or skip when there is no display.

    **Module-scoped on purpose.** Tk expects one root per process;
    customtkinter keeps global appearance and scaling trackers that hold
    references to live windows, and creating then destroying a root per test
    made the suite segfault intermittently once this file added ten more view
    tests to the four that already existed. Sharing one window is both the
    stable arrangement and the way the toolkit is designed to be used.

    Tests must therefore leave no state behind that another test would read;
    `app_window` resets the tab between them.
    """
    pytest.importorskip("customtkinter")
    import tkinter

    from src.gui.app import FukasawaApp

    try:
        window = FukasawaApp()
    except tkinter.TclError as exc:
        pytest.skip(f"no display for GUI test: {exc}")
    yield window
    window.destroy()


@pytest.fixture()
def app_window(_shared_window):
    """The shared window, reset to a known state for each test."""
    tab = _shared_window.workflow_tab
    tab.select_stage("draft")
    tab.set_fields(workflow_entry="", draft_entry="", db_entry="")
    tab.results.delete("1.0", "end")
    return _shared_window


class TestView:
    """Widget behaviour. Display-gated; CI runs these under xvfb."""

    def test_the_workflow_tab_is_mounted_first(self, app_window):
        assert hasattr(app_window, "workflow_tab")

    def test_every_stage_has_a_button(self, app_window):
        assert list(app_window.workflow_tab.stage_buttons) == list(services.STAGES)

    def test_selecting_a_stage_changes_the_actions(self, app_window):
        tab = app_window.workflow_tab
        assert tab.selected_stage == "draft"
        tab.select_stage("exported")
        assert tab.selected_stage == "exported"

    def test_the_lifecycle_drives_end_to_end(self, app_window, draft, db):
        tab = app_window.workflow_tab
        tab.set_fields(
            workflow_entry="substack-publication",
            draft_entry=str(draft),
            db_entry=db,
        )
        assert tab.run_import().ok
        assert tab.run_validate().ok
        assert tab.run_promote().to_maturity == "MAPPED"
        assert tab.run_promote().to_maturity == "ACCOUNTABLE"
        assert tab.run_assess().ok
        assert not tab.run_export().ok  # nothing built yet
        assert tab.run_build(approved=True).ok
        assert tab.run_export().ok

    def test_stage_markers_follow_progress(self, app_window, draft, db):
        tab = app_window.workflow_tab
        tab.set_fields(
            workflow_entry="substack-publication", draft_entry=str(draft), db_entry=db
        )
        before = {s.stage: s.present for s in tab.refresh_stages().stages}
        assert not before["accountable"]
        tab.run_promote()
        tab.run_promote()
        after = {s.stage: s.present for s in tab.refresh_stages().stages}
        assert after["accountable"]

    def test_a_refusal_is_rendered_as_a_refusal(self, app_window, draft, db):
        tab = app_window.workflow_tab
        tab.set_fields(
            workflow_entry="substack-publication", draft_entry=str(draft), db_entry=db
        )
        tab.run_promote()
        tab.run_promote()
        tab.run_assess()
        tab.run_build(approved=False)
        tab._show(tab.run_export())
        shown = tab.shown()
        assert "Refused:" in shown
        assert "approved" in shown

    def test_findings_are_rendered_with_remediation(self, app_window, draft, db):
        # Phase 7 asserted this against the text log. §16.4 replaced the log
        # with a grouped table, so the assertion moved to the table — the
        # property is unchanged and the coverage is wider: every rule id and
        # every remediation, not one of each.
        tab = app_window.workflow_tab
        tab.set_fields(
            workflow_entry="substack-publication", draft_entry=str(draft), db_entry=db
        )
        result = tab.run_validate()
        tab._show(result)
        rendered = " ".join(cell for row in tab.findings_table.rendered() for cell in row)
        assert "HW-013" in rendered
        assert "→" in rendered
        assert all(f.rule_id in rendered for f in result.findings)
        assert all(f.remediation in rendered for f in result.findings)

    def test_kept_human_is_always_stated(self, app_window, draft, db):
        tab = app_window.workflow_tab
        tab.set_fields(
            workflow_entry="substack-publication", draft_entry=str(draft), db_entry=db
        )
        tab.run_promote()
        tab.run_promote()
        tab.run_assess()
        tab._show(tab.run_build(approved=True))
        assert "stay with a person" in tab.shown()

    def test_a_worker_error_surfaces_instead_of_vanishing(self, app_window):
        # An exception on a worker thread otherwise dies with the thread,
        # leaving a window that looks like it did nothing.
        tab = app_window.workflow_tab
        captured = []

        def boom():
            raise RuntimeError("simulated failure")

        tab._in_worker(boom, captured.append)
        pump(tab, captured)
        assert captured, "worker result never arrived"
        assert not captured[0].ok
        assert "simulated failure" in captured[0].refusal

    def test_the_ui_thread_is_not_blocked_while_working(self, app_window, draft, db):
        tab = app_window.workflow_tab
        tab.set_fields(
            workflow_entry="substack-publication", draft_entry=str(draft), db_entry=db
        )
        captured = []
        tab._in_worker(tab.run_import, captured.append)
        # The call returned before the work finished — that is the property.
        # A blocking implementation would have delivered before this line.
        assert not captured
        pump(tab, captured)
        assert captured and captured[0].ok

    def test_the_poller_is_armed_and_rearms(self, app_window):
        # The queue only helps if something drains it. `drain` is called by
        # `_poll`, which must keep re-arming itself.
        tab = app_window.workflow_tab
        assert tab._poll_id is not None
        first = tab._poll_id
        tab._poll()
        assert tab._poll_id is not None
        assert tab._poll_id != first


# ------------------------------------------------------ the §16 completions
#
# Six capabilities the phase 7 note scored as partial or missing. Each test
# names the item it covers, because "the desktop is done" is a claim these
# either support or do not.


class TestGuidedStepEditor:
    """§16.3 — per-field editing of a step, with the rules alongside."""

    def test_the_editor_exposes_every_guided_field(self, app_window):
        editor = app_window.workflow_tab.editor
        assert editor.field_labels() == [g.name for g in services.step_field_guidance()]
        assert "actor" in editor.field_labels()
        assert "decision_authority" in editor.field_labels()

    def test_opening_a_step_fills_the_form(self, app_window, draft, db):
        tab = app_window.workflow_tab
        tab.set_fields(
            workflow_entry="substack-publication", draft_entry=str(draft), db_entry=db
        )
        tab.on_edit_steps()
        assert tab.shown_pane == "editor"
        assert tab.editor.step_id
        assert tab.editor.values()["actor"], "the form did not load the step's actor"

    def test_the_editor_shows_this_step_s_findings(self, app_window, tmp_path):
        tab = app_window.workflow_tab
        skeleton = tmp_path / "new.yaml"
        services.create_draft("new-flow", skeleton)
        tab.set_fields(
            workflow_entry="new-flow",
            draft_entry=str(skeleton),
            db_entry=str(tmp_path / "d.db"),
        )
        tab.on_edit_steps()
        assert "HW-003" in tab.editor.shown_findings()

    def test_saving_from_the_form_fixes_the_finding(self, app_window, tmp_path):
        tab = app_window.workflow_tab
        skeleton = tmp_path / "new.yaml"
        services.create_draft("new-flow", skeleton)
        tab.set_fields(
            workflow_entry="new-flow",
            draft_entry=str(skeleton),
            db_entry=str(tmp_path / "d.db"),
        )
        tab.on_edit_steps()
        tab.editor._set("actor", "the editor")
        result = tab.editor.save()
        assert result.ok
        assert "HW-003" not in tab.editor.shown_findings()

    def test_the_editor_refuses_without_a_draft_path(self, app_window):
        tab = app_window.workflow_tab
        tab.set_fields(workflow_entry="x", draft_entry="", db_entry="")
        tab.on_edit_steps()
        assert not tab.editor.last_result.ok

    def test_a_refused_save_says_why(self, app_window, draft, db):
        tab = app_window.workflow_tab
        tab.set_fields(
            workflow_entry="substack-publication", draft_entry=str(draft), db_entry=db
        )
        tab.on_edit_steps()
        tab.editor._set("inputs", "a brief | the editor | perhaps")
        result = tab.editor.save()
        assert not result.ok
        assert "perhaps" in result.refusal


class TestFindingsTable:
    """§16.4 — findings grouped by severity and workflow location."""

    def test_validation_renders_a_table_not_a_log(self, app_window, tmp_path):
        tab = app_window.workflow_tab
        skeleton = tmp_path / "new.yaml"
        services.create_draft("new-flow", skeleton)
        tab.set_fields(
            workflow_entry="new-flow",
            draft_entry=str(skeleton),
            db_entry=str(tmp_path / "d.db"),
        )
        tab._show(tab.run_validate())
        assert tab.shown_pane == "findings"
        assert tab.findings_table.rendered(), "no rows rendered"
        assert tab.findings_table.columns[0] == "Rule"

    def test_every_finding_reaches_a_row(self, app_window, tmp_path):
        tab = app_window.workflow_tab
        skeleton = tmp_path / "new.yaml"
        services.create_draft("new-flow", skeleton)
        tab.set_fields(
            workflow_entry="new-flow",
            draft_entry=str(skeleton),
            db_entry=str(tmp_path / "d.db"),
        )
        result = tab.run_validate()
        tab._show(result)
        assert len(tab.findings_table.rendered()) == len(result.findings)

    def test_remediation_travels_with_the_finding(self, app_window, tmp_path):
        # §16.5 — still met now that the renderer changed.
        tab = app_window.workflow_tab
        skeleton = tmp_path / "new.yaml"
        services.create_draft("new-flow", skeleton)
        tab.set_fields(
            workflow_entry="new-flow",
            draft_entry=str(skeleton),
            db_entry=str(tmp_path / "d.db"),
        )
        result = tab.run_validate()
        tab._show(result)
        remediations = {f.remediation for f in result.findings}
        rendered = " ".join(cell for row in tab.findings_table.rendered() for cell in row)
        assert all(r in rendered for r in remediations)

    def test_a_row_reports_the_finding_it_came_from(self, app_window, tmp_path):
        # Not the strings it was rendered into: the accept dialog needs the
        # finding_id, and parsing it back out of a label would be a way to lie.
        tab = app_window.workflow_tab
        skeleton = tmp_path / "new.yaml"
        services.create_draft("new-flow", skeleton)
        tab.set_fields(
            workflow_entry="new-flow",
            draft_entry=str(skeleton),
            db_entry=str(tmp_path / "d.db"),
        )
        tab._show(tab.run_validate())
        row = tab.findings_table.rows[0]
        tab.findings_table.select(row)
        assert tab.findings_table.selected_source() is row.source
        assert tab.findings_table.selected_source().finding_id


class TestAssessmentTable:
    """§16.8 — the cooperation assessment as a table."""

    def test_assessment_renders_a_table(self, app_window, draft, db):
        tab = app_window.workflow_tab
        tab.set_fields(
            workflow_entry="substack-publication", draft_entry=str(draft), db_entry=db
        )
        accountable(draft, db)
        result = tab.run_assess()
        tab._show(result)
        assert tab.shown_pane == "assessments"
        assert len(tab.assessment_table.rendered()) == len(result.assessments)

    def test_floored_steps_are_grouped_apart(self, app_window, draft, db):
        tab = app_window.workflow_tab
        tab.set_fields(
            workflow_entry="substack-publication", draft_entry=str(draft), db_entry=db
        )
        accountable(draft, db)
        result = tab.run_assess()
        tab._show(result)
        floored = [a.step_id for a in result.assessments if a.floored]
        rows = tab.assessment_table.rendered()
        assert floored, "the pilot should have at least one floored step"
        # The floored group is rendered last, so the floored steps are the tail.
        assert [r[0] for r in rows][-len(floored):] == floored

    def test_the_table_states_the_supervision_and_readiness(self, app_window, draft, db):
        tab = app_window.workflow_tab
        tab.set_fields(
            workflow_entry="substack-publication", draft_entry=str(draft), db_entry=db
        )
        accountable(draft, db)
        result = tab.run_assess()
        tab._show(result)
        by_step = {r[0]: r for r in tab.assessment_table.rendered()}
        one = result.assessments[0]
        assert by_step[one.step_id][2] == one.supervision_mode
        assert by_step[one.step_id][3] == one.automation_readiness


class TestReasonDialogs:
    """§16.6 and §16.9 — the two places a person overrules the runtime."""

    def _dialog(self, app_window, **kwargs):
        from src.gui.dialogs import ReasonDialog

        defaults = dict(title="t", subject="s")
        defaults.update(kwargs)
        return ReasonDialog(app_window, **defaults)

    def test_confirm_is_disabled_until_a_reason_is_given(self, app_window):
        dialog = self._dialog(app_window, actor="someone")
        try:
            assert dialog.confirm_button.cget("state") == "disabled"
            dialog.reason_box.insert("1.0", "we checked with the editor")
            dialog.refresh()
            assert dialog.confirm_button.cget("state") == "normal"
        finally:
            dialog.cancel()

    def test_confirm_is_disabled_without_a_name(self, app_window):
        dialog = self._dialog(app_window)
        try:
            dialog.reason_box.insert("1.0", "a reason")
            dialog.refresh()
            assert dialog.confirm_button.cget("state") == "disabled"
        finally:
            dialog.cancel()

    def test_confirming_while_incomplete_does_nothing(self, app_window):
        # The button being disabled is the courtesy; this is the guarantee.
        dialog = self._dialog(app_window)
        try:
            dialog.confirm()
            assert dialog.result is None
            assert dialog.winfo_exists()
        finally:
            dialog.cancel()

    def test_cancelling_yields_no_decision(self, app_window):
        dialog = self._dialog(app_window, actor="a")
        dialog.reason_box.insert("1.0", "b")
        dialog.cancel()
        assert dialog.result is None

    def test_the_override_dialog_offers_every_executor_class(self, app_window):
        dialog = self._dialog(
            app_window, choices=list(services.EXECUTOR_CLASSES), choice_label="Executor"
        )
        try:
            assert dialog.choice() in services.EXECUTOR_CLASSES
            assert len(services.EXECUTOR_CLASSES) == 7
        finally:
            dialog.cancel()

    def test_accept_without_a_selection_explains_itself(self, app_window, draft, db):
        tab = app_window.workflow_tab
        tab.set_fields(
            workflow_entry="substack-publication", draft_entry=str(draft), db_entry=db
        )
        tab.findings_table.clear()
        tab.on_accept_risk()
        assert "click the finding" in tab.shown()

    def test_accept_refuses_a_blocking_finding_before_opening(self, app_window, tmp_path):
        # No dialog at all for a blocking finding: it is fixed, not accepted.
        tab = app_window.workflow_tab
        skeleton = tmp_path / "new.yaml"
        services.create_draft("new-flow", skeleton)
        tab.set_fields(
            workflow_entry="new-flow",
            draft_entry=str(skeleton),
            db_entry=str(tmp_path / "d.db"),
        )
        tab._show(tab.run_validate())
        blocking = next(r for r in tab.findings_table.rows if r.source.blocking)
        tab.findings_table.select(blocking)
        tab.on_accept_risk()
        assert "cannot be accepted" in tab.shown()

    def test_accepting_an_advisory_finding_records_it(self, app_window, draft, db):
        # The service path the dialog calls, driven without the modal.
        tab = app_window.workflow_tab
        tab.set_fields(
            workflow_entry="substack-publication", draft_entry=str(draft), db_entry=db
        )
        result = tab.run_validate()
        advisory = next(f for f in result.findings if not f.blocking)
        assert tab.run_accept(advisory.finding_id, "operator", "known and watched").ok
        again = tab.run_validate()
        assert any(f.accepted for f in again.findings)

    def test_override_without_a_selection_explains_itself(self, app_window, draft, db):
        tab = app_window.workflow_tab
        tab.set_fields(
            workflow_entry="substack-publication", draft_entry=str(draft), db_entry=db
        )
        tab.assessment_table.clear()
        tab.on_override()
        assert "Assess cooperation first" in tab.shown()

    def test_override_through_the_tab_refuses_crossing_a_floor(self, app_window, draft, db):
        tab = app_window.workflow_tab
        tab.set_fields(
            workflow_entry="substack-publication", draft_entry=str(draft), db_entry=db
        )
        accountable(draft, db)
        tab.run_assess()
        refused = tab.run_override(
            "review-and-approve", "BOUNDED_AUTONOMOUS_AGENT", "operator", "faster"
        )
        assert not refused.ok
        allowed = tab.run_override(
            "request-artwork", "HUMAN_ONLY", "operator", "the illustrator prefers it"
        )
        assert allowed.ok


class TestVisibleVersionBar:
    """§16.13 and §16.14 — maturity and versions, always on screen."""

    def test_the_bar_states_the_rule_set_version(self, app_window, draft, db):
        tab = app_window.workflow_tab
        tab.set_fields(
            workflow_entry="substack-publication", draft_entry=str(draft), db_entry=db
        )
        tab.refresh_stages()
        assert "rule set v" in tab.version_bar.cget("text")
        assert "schema v" in tab.version_bar.cget("text")

    def test_the_bar_follows_the_maturity(self, app_window, draft, db):
        tab = app_window.workflow_tab
        tab.set_fields(
            workflow_entry="substack-publication", draft_entry=str(draft), db_entry=db
        )
        tab.run_import()
        tab.refresh_stages()
        assert "OBSERVED" in tab.version_bar.cget("text")
        tab.run_promote()
        tab.run_promote()
        tab.refresh_stages()
        assert "ACCOUNTABLE" in tab.version_bar.cget("text")
