# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Phase 8 hardening — the two release constraints nothing was checking.

Both are stated plainly somewhere and enforced nowhere, which is the specific
kind of gap this phase exists to close:

* **Offline.** "No network calls during runtime execution" (CLAUDE.md) and "no
  undocumented network dependency is required" (master handoff §2.2). The whole
  authoritative lifecycle — validate, promote, assess, build, export — must run
  with the network physically unavailable. The one module that legitimately
  reaches out, `src/kernel/models.py`, is the optional model-adapter layer and
  is not on any authoritative path.

* **Old persisted data.** §15.4 requires "old-version load behaviour" to be
  tested. There is only one schema version today, which is exactly when this is
  cheap to write and exactly when nobody writes it. What matters is not that an
  old payload loads — it is that the behaviour is *defined* and the failure is
  legible rather than a traceback from three layers down.
"""

import socket
from pathlib import Path

import pytest
import yaml

from src.governance.cooperation import assess_workflow
from src.governance.workflow_rules import validate_workflow
from src.runtime.ledger import RunLedger
from src.schemas.human_workflow import HumanWorkflowDraft

ROOT = Path(__file__).resolve().parent.parent
PILOT = ROOT / "examples" / "workflows" / "substack-publication"
REPAIRED = PILOT / "repaired-workflow.yaml"


def _draft() -> HumanWorkflowDraft:
    return HumanWorkflowDraft.model_validate(
        yaml.safe_load(REPAIRED.read_text(encoding="utf-8"))
    )


@pytest.fixture()
def no_network(monkeypatch):
    """Make every outbound socket raise, for the duration of one test.

    Patched at `socket.socket` rather than at a higher level on purpose: it
    catches anything reaching the network by any route, including a library
    doing it indirectly. A test that only patched `urllib` would pass while
    something used `http.client` underneath it.
    """

    class Blocked(socket.socket):
        def __init__(self, *args, **kwargs):
            raise AssertionError(
                "the authoritative lifecycle opened a socket; it must run offline"
            )

    monkeypatch.setattr(socket, "socket", Blocked)
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("the authoritative lifecycle opened a connection")
        ),
    )


class TestOffline:
    """The authoritative paths never touch the network."""

    def test_validation_runs_offline(self, no_network):
        report = validate_workflow(_draft())
        assert report.promotion_ready

    def test_the_whole_lifecycle_runs_offline(self, no_network, tmp_path):
        from src.foundry.workflow_export import (
            build_cooperative_workflow,
            export_workflow,
        )
        from src.governance.workflow_promotion import promote

        ledger = RunLedger(str(tmp_path / "offline.db"))
        draft = _draft()

        # OBSERVED -> MAPPED -> ACCOUNTABLE
        for _ in range(2):
            report = validate_workflow(draft)
            outcome = promote(ledger, draft, report, promoted_by="tester")
            draft.maturity = outcome.to_maturity

        accountable = ledger.load_accountable_workflow(draft.workflow_id)
        assessments = assess_workflow(accountable, systems=list(draft.systems))
        cooperative = build_cooperative_workflow(
            accountable, assessments, approved_by="tester"
        )
        brief = export_workflow(cooperative, accountable)

        assert brief.states, "export produced no states"
        assert len(assessments) == len(accountable.steps)

    def test_the_guard_itself_works(self, no_network):
        # A test that cannot fail proves nothing. This asserts the fixture
        # really does block the network, so the two tests above mean something.
        with pytest.raises(AssertionError, match="offline|connection"):
            socket.socket()

    def test_only_the_model_adapter_reaches_the_network(self):
        # Documents the one legitimate exception, and fails if a second appears
        # anywhere under src/ — including on an authoritative path.
        import ast

        offenders = {}
        for path in (ROOT / "src").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names |= {a.name for a in node.names}
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names.add(node.module)
            reaching = {
                n for n in names
                if n.split(".")[0] in {"urllib", "http", "socket", "requests", "httpx"}
            }
            if reaching:
                offenders[str(path.relative_to(ROOT))] = sorted(reaching)

        assert offenders == {
            "src/kernel/models.py": ["urllib.error", "urllib.request"]
        }, (
            f"network imports moved: {offenders}. The model adapter is the only "
            f"module allowed to reach out, and it is not on an authoritative path."
        )


class TestOldPersistedData:
    """§15.4 — what happens to data written by an older version."""

    def test_the_current_version_is_what_we_think(self):
        from src.schemas.human_workflow import SCHEMA_VERSION

        assert SCHEMA_VERSION == "1", (
            "the schema version moved; add a migration case below before "
            "shipping, per docs/migration-notes.md"
        )

    def test_a_draft_with_no_schema_version_still_loads(self):
        """Data written before the field existed must not become unreadable.

        `schema_version` has a default, which is what makes this work. The test
        exists because that default is load-bearing and deleting it would look
        like tidying.
        """
        raw = yaml.safe_load(REPAIRED.read_text(encoding="utf-8"))
        raw.pop("schema_version", None)
        draft = HumanWorkflowDraft.model_validate(raw)
        assert draft.schema_version == "1"
        assert validate_workflow(draft).promotion_ready

    def test_a_future_schema_version_is_accepted_and_recorded(self):
        """A newer payload loads rather than being refused.

        This is a deliberate choice and worth stating: the version is recorded
        so an audit can see what wrote it, but it does not gate reading. A hard
        refusal would make a forward-compatible field addition into an outage,
        and the additive-only policy (ADR-002) is what makes that safe.
        """
        raw = yaml.safe_load(REPAIRED.read_text(encoding="utf-8"))
        raw["schema_version"] = "99"
        draft = HumanWorkflowDraft.model_validate(raw)
        assert draft.schema_version == "99"

    def test_an_unknown_field_is_refused_loudly(self):
        """The other half: `extra="forbid"` across every contract.

        These are hand-written YAML files. A mistyped field name that is
        silently ignored is exactly the invisible drift this product exists to
        catch, so the refusal names the field.
        """
        from pydantic import ValidationError

        raw = yaml.safe_load(REPAIRED.read_text(encoding="utf-8"))
        raw["claimed_outcomes"] = "a typo of claimed_outcome"
        with pytest.raises(ValidationError) as exc:
            HumanWorkflowDraft.model_validate(raw)
        assert "claimed_outcomes" in str(exc.value)

    def test_a_draft_persisted_today_reloads_identically(self, tmp_path):
        """Round trip through the ledger, which is where old data actually lives."""
        ledger = RunLedger(str(tmp_path / "roundtrip.db"))
        original = _draft()
        ledger.save_workflow_draft(original)
        reloaded = ledger.load_workflow_draft(original.workflow_id)
        assert reloaded.model_dump(mode="json") == original.model_dump(mode="json")

    def test_findings_are_stable_across_a_persist_reload_cycle(self, tmp_path):
        # The property that matters for old data: the same workflow must
        # validate the same way after a storage round trip, or a stored report
        # and a fresh one would disagree about the same file.
        ledger = RunLedger(str(tmp_path / "stability.db"))
        original = _draft()
        before = [f.finding_id for f in validate_workflow(original).findings]
        ledger.save_workflow_draft(original)
        after = [
            f.finding_id
            for f in validate_workflow(ledger.load_workflow_draft(original.workflow_id)).findings
        ]
        assert before == after
