# tests/test_node_cli.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""The command line, in the same voice as the desktop.

Not terse. A person who reached for a terminal still deserves sentences, and
the copy rules of the design apply here exactly as they do on screen.
"""

import json

import pytest
from typer.testing import CliRunner

from src.cli import app
from src.nodes.store import NodeStore
from src.schemas.node import (
    InferenceNode,
    ModelCapability,
    NodeKind,
    ScanConsent,
    ScanScope,
)

JUDGEMENT = ["slow", "fast", "good", "poor", "powerful", "weak", "adequate"]
OWNERSHIP = ["stays with you", "your workflow", "your model", "off your hands"]


@pytest.fixture()
def store_path(tmp_path, monkeypatch):
    path = tmp_path / "nodes.yaml"
    monkeypatch.setattr("src.nodes.store.NodeStore.default_path",
                        staticmethod(lambda: path))
    return path


def seed(store_path, **kw):
    store = NodeStore(store_path)
    base = dict(node_id="home-pc", label="Home PC", kind=NodeKind.OLLAMA,
                url="http://localhost:11434", reachable=True,
                models=[ModelCapability(name="llama3.1:8b", context_length=8192)])
    base.update(kw)
    store.save([InferenceNode(**base)],
               ScanConsent.granted(ScanScope.THIS_MACHINE, "sam"))
    return store


class TestList:
    def test_nothing_configured_says_what_the_program_does(self, store_path):
        result = CliRunner().invoke(app, ["node", "list"])
        assert result.exit_code == 0
        assert "nothing yet" in result.output
        assert "do not require a computer" in result.output

    def test_a_stored_computer_is_shown_with_its_figures(self, store_path):
        seed(store_path)
        result = CliRunner().invoke(app, ["node", "list"])
        assert result.exit_code == 0
        assert "Home PC" in result.output
        assert "words" in result.output

    def test_json_output_is_machine_readable(self, store_path):
        seed(store_path)
        result = CliRunner().invoke(app, ["node", "list", "--json"])
        payload = json.loads(result.output)
        assert payload["nodes"][0]["node_id"] == "home-pc"


class TestScan:
    def test_scanning_without_permission_is_refused_not_crashed(self, store_path):
        result = CliRunner().invoke(app, ["node", "scan", "--scope", "none", "--yes"])
        assert result.exit_code == 3, result.output
        assert "permission" in result.output.lower()

    def test_an_unknown_scope_is_a_user_error(self, store_path):
        result = CliRunner().invoke(app, ["node", "scan", "--scope", "wat", "--yes"])
        assert result.exit_code == 1

    def test_a_scan_prints_each_finding_as_it_arrives(self, store_path, monkeypatch):
        from src.nodes.discovery import DiscoveryEvent

        def fake(scope, host="", **kw):
            yield DiscoveryEvent("trying", "Looking on port 11434...")
            yield DiscoveryEvent("reachable", "Something's listening on port 11434")
            yield DiscoveryEvent("done", "Found 1 computer.", finished=True)

        monkeypatch.setattr("src.cli._discover", fake)
        result = CliRunner().invoke(
            app, ["node", "scan", "--scope", "this-machine", "--yes"]
        )
        assert result.exit_code == 0, result.output
        assert "Looking on port 11434" in result.output
        assert "Found 1 computer." in result.output


class TestAddAndForget:
    def test_a_computer_can_be_added_by_hand(self, store_path):
        result = CliRunner().invoke(app, [
            "node", "add", "--label", "Kitchen Box", "--kind", "ollama",
            "--url", "http://10.0.0.9:11434",
        ])
        assert result.exit_code == 0, result.output
        nodes, _ = NodeStore(store_path).load()
        assert nodes[0].node_id == "kitchen-box"
        assert nodes[0].source_of("url").value == "DECLARED"

    def test_forgetting_something_absent_is_a_user_error(self, store_path):
        result = CliRunner().invoke(app, ["node", "forget", "nope"])
        assert result.exit_code == 1
        assert "nope" in result.output


class TestConsent:
    def test_the_current_permission_is_shown(self, store_path):
        seed(store_path)
        result = CliRunner().invoke(app, ["node", "consent"])
        assert result.exit_code == 0
        assert "this computer" in result.output.lower()

    def test_permission_can_be_changed(self, store_path):
        seed(store_path)
        result = CliRunner().invoke(app, ["node", "consent", "--set", "none"])
        assert result.exit_code == 0
        _nodes, consent = NodeStore(store_path).load()
        assert consent.scope is ScanScope.NONE


class TestCopyRules:
    @pytest.mark.parametrize("argv", [
        ["node", "list"],
        ["node", "consent"],
    ])
    def test_no_command_judges_or_assumes_ownership(self, store_path, argv):
        seed(store_path)
        output = CliRunner().invoke(app, argv).output.lower()
        assert not [w for w in JUDGEMENT if w in output]
        assert not [w for w in OWNERSHIP if w in output]
