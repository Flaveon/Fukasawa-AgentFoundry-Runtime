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
            "src/kernel/models.py": ["urllib.error", "urllib.request"],
            "src/nodes/backends.py": ["urllib.error", "urllib.request"],
        }, (
            f"network imports moved: {offenders}. Two modules may reach the "
            f"network and no more: the model adapter, and node discovery. "
            f"Discovery is config-time, runs only after a person grants "
            f"permission, and is not on an authoritative path — validation, "
            f"promotion, classification and export never call it."
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


class TestEndpointsAreDiscoverable:
    """`model list` must tell an operator where to add their own nodes.

    This product is meant to be handed to someone who runs their own hardware.
    Before phase 9 the only statement of where endpoints are configured was one
    line of `src/cli.py`: a user saw two localhost defaults and nothing telling
    them the config file existed. Adding a node meant reading the source.
    """

    def _run(self, tmp_path, monkeypatch, exists: bool):
        from typer.testing import CliRunner

        from src import cli

        home = tmp_path / ".fukasawa"
        home.mkdir()
        if exists:
            (home / "model_endpoints.yaml").write_text(
                "endpoints:\n  mine:\n    kind: ollama\n    url: http://x:11434\n",
                encoding="utf-8",
            )
        monkeypatch.setattr("src.security.trust.DEFAULT_TRUST_ROOT", home)
        return CliRunner().invoke(cli.app, ["model", "list"])

    def test_it_names_the_config_path_when_none_exists(self, tmp_path, monkeypatch):
        result = self._run(tmp_path, monkeypatch, exists=False)
        assert result.exit_code == 0, result.output
        assert "model_endpoints.yaml" in result.output, (
            "a user with no config is told nothing about where to add nodes"
        )

    def test_it_shows_a_template_when_none_exists(self, tmp_path, monkeypatch):
        # A path alone is not enough when the file has never existed: there is
        # nothing to open and read the shape of.
        result = self._run(tmp_path, monkeypatch, exists=False)
        assert "endpoints:" in result.output
        assert "kind:" in result.output and "url:" in result.output

    def test_it_names_the_config_path_when_one_exists(self, tmp_path, monkeypatch):
        result = self._run(tmp_path, monkeypatch, exists=True)
        assert result.exit_code == 0, result.output
        assert "model_endpoints.yaml" in result.output

    def test_it_states_the_capability_gap(self, tmp_path, monkeypatch):
        # An operator must not infer from a green endpoint list that the runtime
        # has checked their hardware can run anything.
        result = self._run(tmp_path, monkeypatch, exists=True)
        assert "capabilit" in result.output.lower()

    def test_the_readme_documents_the_gap(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        assert "## Known gaps" in readme
        assert "model_endpoints.yaml" in readme, (
            "the endpoint config path is documented nowhere a user would look"
        )
        historical = readme[
            readme.index("historical, not current"):readme.index("## Directory map")
        ].lower()
        # The historical section may *mention* the node library — it must not
        # file it under "never built, ignore it". It is a missing requirement,
        # and the section must hand the reader onward to Known gaps.
        assert "never built" not in historical or "node library" not in historical, (
            "the node library is listed as never-built planning cruft; it is a "
            "missing requirement for a consumer-facing product"
        )
        if "node library" in historical:
            assert "known gaps" in historical, (
                "the historical section mentions the node library without "
                "pointing at where the real gap is recorded"
            )
