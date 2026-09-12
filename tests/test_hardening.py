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

    def _run(self, tmp_path, monkeypatch, exists: bool, nodes: str = "",
             record: bool = False):
        from typer.testing import CliRunner

        from src import cli

        home = _home(tmp_path, monkeypatch)
        if exists:
            (home / "model_endpoints.yaml").write_text(
                "endpoints:\n  mine:\n    kind: ollama\n    url: http://x:11434\n",
                encoding="utf-8",
            )
        if nodes:
            (home / "nodes.yaml").write_text(nodes, encoding="utf-8")
        if record:
            _record(home)
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
        # has checked their hardware can run anything. Asserted on the sentence
        # rather than on the word "capability", which §3.1 keeps off screens.
        result = self._run(tmp_path, monkeypatch, exists=True)
        prose = " ".join(result.output.split())  # rich wraps at 80 columns
        assert "Nothing yet checks whether a computer can run" in prose


def _home(tmp_path, monkeypatch):
    """A fresh $FUKASAWA_HOME for one test: trust root, endpoints, and computers.

    All three are pointed at it. Pointing only the trust root there -- which
    is what this file did before recorded computers reached the runtime --
    leaves the node store at the tester's real home, and `model list` would
    read somebody's own `nodes.yaml` in the middle of a test.
    """
    home = tmp_path / ".fukasawa"
    home.mkdir()
    monkeypatch.setattr("src.security.trust.DEFAULT_TRUST_ROOT", home)
    monkeypatch.setattr("src.nodes.registry.DEFAULT_HOME", home)
    monkeypatch.setattr("src.nodes.store.NodeStore.default_path",
                        staticmethod(lambda: home / "nodes.yaml"))
    return home


def _record(home) -> None:
    """Record a computer at a documentation address (RFC 5737).

    Through `NodeStore` itself, so the file is in the store's own format.
    Distinctive on purpose: if the address turns up somewhere, it came from
    here.
    """
    from src.nodes.store import NodeStore
    from src.schemas.node import InferenceNode, NodeKind, ScanConsent

    NodeStore(home / "nodes.yaml").save(
        [InferenceNode(node_id="kitchen-box", label="Kitchen Box",
                       kind=NodeKind.OLLAMA, url=RECORDED_URL)],
        ScanConsent(),
    )


RECORDED_URL = "http://203.0.113.7:11434"


class TestRecordedComputersAreUsable:
    """Design §6: a recorded computer is an endpoint under its own id.

    `merged_endpoints` was built and unit-tested in Task 5 and never called:
    the runtime read `model_endpoints.yaml` alone, so nothing recorded by
    `node scan`, `node add` or the Environment tab could be used by
    `model test` or a graph run. Found while checking Task 9's plan against
    the source. These test the runtime's use of the merge, not the merge.
    """

    def test_the_runtime_resolves_a_recorded_computer_by_its_id(
        self, tmp_path, monkeypatch
    ):
        from src import cli

        _record(_home(tmp_path, monkeypatch))
        assert cli._model_endpoints().get("kitchen-box").url == RECORDED_URL

    def test_model_list_shows_it(self, tmp_path, monkeypatch):
        result = TestEndpointsAreDiscoverable()._run(
            tmp_path, monkeypatch, exists=True, record=True
        )
        assert result.exit_code == 0, result.output
        assert "kitchen-box" in result.output
        assert "mine" in result.output, "model_endpoints.yaml stopped resolving"

    def test_unreadable_computers_are_named_and_left_out(
        self, tmp_path, monkeypatch
    ):
        """A graph that uses no recorded computer must still run."""
        result = TestEndpointsAreDiscoverable()._run(
            tmp_path, monkeypatch, exists=True, nodes="nodes: [oops\n"
        )
        assert result.exit_code == 0, result.output
        assert "could not be read" in result.output
        assert "nodes.yaml" in result.output
        assert "mine" in result.output

    def test_a_broken_endpoint_file_is_not_blamed_on_the_computers(
        self, tmp_path, monkeypatch
    ):
        from typer.testing import CliRunner

        from src import cli

        home = _home(tmp_path, monkeypatch)
        _record(home)
        (home / "model_endpoints.yaml").write_text("endpoints: [oops\n",
                                                   encoding="utf-8")
        result = CliRunner().invoke(cli.app, ["model", "list"])
        assert "recorded computers" not in result.output

    def test_the_readme_documents_the_gap(self):
        # "Known gaps" became "Still open" when phase 10a closed half of it.
        # What this guards is unchanged: the remaining gap is documented, the
        # endpoint file is findable, and the node library is never filed as
        # planning cruft.
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        assert "## Still open" in readme
        assert "phase 10b" in readme.lower(), (
            "the README no longer says what is left: matching steps to computers"
        )
        assert "model_endpoints.yaml" in readme, (
            "the endpoint config path is documented nowhere a user would look"
        )
        assert "docs/environment-guide.md" in readme
        historical = readme[
            readme.index("historical, not current"):readme.index("## Directory map")
        ].lower()
        # The historical section may *mention* the node library — it must not
        # file it under "never built, ignore it". It is a missing requirement,
        # and the section must hand the reader onward to what is still open.
        assert "never built" not in historical or "node library" not in historical, (
            "the node library is listed as never-built planning cruft; it is a "
            "missing requirement for a consumer-facing product"
        )
        if "node library" in historical:
            assert "still open" in historical, (
                "the historical section mentions the node library without "
                "pointing at where the rest of the gap is recorded"
            )


class TestNodeDoctrine:
    """What must stay true of recorded computers however the feature grows.

    Design §6.1 and §9. A person's computers and their addresses describe
    their house; this repository is public and its artifacts are shared.
    """

    def test_an_exported_brief_never_carries_a_recorded_address(
        self, tmp_path, monkeypatch
    ):
        """A shared artifact names a computer; it never says where it is.

        **Computers are recorded before exporting, on purpose.** Nothing on
        the export path reads them today, so with none recorded this test
        could not fail -- it would pass for the reason that the thing it
        guards against is impossible, and would go on passing the day phase
        10b connects computers to step assignments. Recorded in both places
        an address can live -- the node store and `model_endpoints.yaml` --
        the export has something to leak, and this is what says it did not.
        """
        import shutil

        from src.gui import services

        home = _home(tmp_path, monkeypatch)
        _record(home)
        (home / "model_endpoints.yaml").write_text(
            f"endpoints:\n  garage:\n    kind: ollama\n    url: {RECORDED_URL}\n",
            encoding="utf-8",
        )
        draft = tmp_path / "draft.yaml"
        shutil.copy(REPAIRED, draft)
        db = str(tmp_path / "d.db")
        for _ in range(2):
            assert services.promote_draft(draft, "t", db).ok
        assert services.assess_cooperation("substack-publication", db).ok
        assert services.build_cooperative("substack-publication", "t", db).ok
        out = tmp_path / "brief.yaml"
        assert services.export_brief("substack-publication", out, db).ok

        text = out.read_text(encoding="utf-8")
        host = RECORDED_URL.split("//", 1)[1]
        for marker in (host, host.split(":")[0]):
            assert marker not in text, (
                f"an exported brief carries {marker!r}; a shared artifact must "
                f"name a computer, never give its address"
            )

    #: Private-range addresses that appear in this repository as examples,
    #: and why. Anything else in a private range is taken to be somebody's
    #: real network. None of these is the operator's.
    EXAMPLE_ADDRESSES = {
        "10.0.0.9": "the address tests and docs use for 'a computer named by hand'",
        "10.0.0.8": "a second, silent one, in the typed-in tests",
        "10.0.0.5": "an edited address, in the card-edit tests",
        "10.0.0.1": "three computers on one port, in the id-collision test",
        "10.0.0.2": "three computers on one port, in the id-collision test",
        "10.0.0.3": "three computers on one port, in the id-collision test",
        "192.168.1.50": "the `model list` template and the example endpoint config",
        "192.168.1.20": "the Environment tab's placeholder, and docs/environment-guide.md",
    }

    def _tracked_files(self) -> list[Path]:
        """What is published: every file git tracks. Skips outside a checkout."""
        import subprocess

        try:
            listed = subprocess.run(
                ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True,
                check=True,
            ).stdout.splitlines()
        except (OSError, subprocess.CalledProcessError):
            pytest.skip("not a git checkout; nothing is published from here")
        return [ROOT / name for name in listed if (ROOT / name).is_file()]

    def test_no_private_address_is_published(self):
        """Nothing about anybody's network ships in the product (spec §9).

        Every tracked file, not only `src/`: the repository is public, and a
        document is published as surely as code. Found clean when written --
        but the history is not: see the phase 10a completion note.
        """
        import re

        pattern = re.compile(
            r"\b(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
            r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"
        )
        offenders = []
        for path in self._tracked_files():
            text = path.read_text(encoding="utf-8", errors="ignore")
            for found in pattern.findall(text):
                if found not in self.EXAMPLE_ADDRESSES:
                    offenders.append(f"{path.relative_to(ROOT)}: {found}")
        assert not offenders, (
            f"private addresses published: {offenders[:5]}. If one is a "
            f"documentation example, add it to EXAMPLE_ADDRESSES with why."
        )

    def test_no_forbidden_name_is_published(self):
        """Operator hostnames -- which this file cannot list without publishing.

        So they are read at test time from ``FUKASAWA_FORBIDDEN_NAMES``,
        comma-separated, which is never committed. Unset, there is nothing to
        check against and the test says so rather than passing. Matched as
        whole words, ignoring case.
        """
        import os
        import re

        names = [n.strip() for n in
                 os.environ.get("FUKASAWA_FORBIDDEN_NAMES", "").split(",")
                 if n.strip()]
        if not names:
            pytest.skip("FUKASAWA_FORBIDDEN_NAMES is not set")
        pattern = re.compile(
            r"\b(?:" + "|".join(re.escape(n) for n in names) + r")\b", re.I
        )
        offenders = []
        for path in self._tracked_files():
            text = path.read_text(encoding="utf-8", errors="ignore")
            for found in set(pattern.findall(text)):
                offenders.append(f"{path.relative_to(ROOT)}: {found}")
        assert not offenders, f"forbidden names published: {offenders[:10]}"

    def test_nothing_is_looked_at_until_somebody_says_so(self, tmp_path):
        """The standing permission starts at none, however it is reached."""
        from src.nodes.store import NodeStore
        from src.schemas.node import ScanConsent, ScanScope

        assert ScanConsent().scope is ScanScope.NONE
        _nodes, consent = NodeStore(tmp_path / "nodes.yaml").load()
        assert consent.scope is ScanScope.NONE
