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

    def test_json_survives_a_narrow_terminal_and_a_label_full_of_brackets(
        self, store_path
    ):
        """--json is for a program, so the terminal's width must not reach it.

        Two failures hide behind a short label on a wide terminal. A console
        that wraps to the window splits a long string mid-literal, and a
        console that reads markup eats the brackets out of a stored label. So
        this drives a 60-column window with a label longer than that, and
        checks the label comes back byte-for-byte as it sits in the file.
        """
        stored = "The workshop machine in the back room [red] by the window"
        seed(store_path, label=stored)
        result = CliRunner(env={"COLUMNS": "60"}).invoke(
            app, ["node", "list", "--json"]
        )
        payload = json.loads(result.output)
        assert payload["nodes"][0]["label"] == stored


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

    def test_json_events_stay_one_per_line_on_a_narrow_terminal(
        self, store_path, monkeypatch
    ):
        """The design calls --json a stream: one object per line, always.

        A message can be longer than the window and can carry brackets, since
        part of it is a model name read off another computer. Neither may
        break a line in two or alter a character.
        """
        from src.nodes.discovery import DiscoveryEvent

        message = "Biggest is a model with a very long name [red] indeed here"

        def fake(scope, host="", **kw):
            yield DiscoveryEvent("biggest", message)
            yield DiscoveryEvent("done", "Found 1 computer.", finished=True)

        monkeypatch.setattr("src.cli._discover", fake)
        result = CliRunner(env={"COLUMNS": "60"}).invoke(
            app, ["node", "scan", "--scope", "this-machine", "--yes", "--json"]
        )
        assert result.exit_code == 0, result.output
        lines = [ln for ln in result.output.splitlines() if ln.strip()]
        events = [json.loads(ln) for ln in lines]
        assert events[0]["message"] == message
        assert events[-1]["finished"] is True


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


class TestSquareBracketsInStoredText:
    """Text that arrives from outside is text, never formatting.

    A label is typed by a person and a model name is read off another
    computer, so both can contain square brackets. Rich reads square brackets
    as markup, and a stray one aborts the print. That would be bad enough
    while adding; the worse half is that the value is already on disk by then,
    so every later read of the file hits the same abort and the command that
    lists the computers stops working for good.
    """

    HOSTILE = "Box [/dim] X"

    def test_adding_listing_and_showing_all_survive_a_bracketed_label(
        self, store_path
    ):
        runner = CliRunner()
        added = runner.invoke(app, [
            "node", "add", "--label", self.HOSTILE, "--kind", "ollama",
            "--url", "http://10.0.0.9:11434",
        ])
        assert added.exit_code == 0, added.output

        nodes, _ = NodeStore(store_path).load()
        assert nodes[0].label == self.HOSTILE

        listed = runner.invoke(app, ["node", "list"])
        assert listed.exit_code == 0, listed.output

        shown = runner.invoke(app, ["node", "show", nodes[0].node_id])
        assert shown.exit_code == 0, shown.output

    def test_the_panel_survives_a_bracketed_label_on_a_reachable_computer(
        self, store_path
    ):
        """The panel names every reachable computer, so labels reach it too."""
        seed(store_path, label=self.HOSTILE)
        result = CliRunner().invoke(app, ["node", "list"])
        assert result.exit_code == 0, result.output

    def test_a_bracketed_model_name_does_not_abort_the_card(self, store_path):
        """Model names come from another computer. Treat them as hostile.

        ``[b]`` happens to be a real Rich tag, so this one does not abort —
        it silently swallows the brackets and prints a name the other
        computer never reported. Printing an altered name is its own bug, so
        the name is checked character for character.
        """
        seed(store_path, models=[ModelCapability(name="a[b]c:8b",
                                                 context_length=8192)])
        result = CliRunner().invoke(app, ["node", "show", "home-pc"])
        assert result.exit_code == 0, result.output
        assert "a[b]c:8b" in result.output

    def test_a_bracketed_finding_does_not_abort_the_scan(
        self, store_path, monkeypatch
    ):
        """A discovery line quotes a remote model name. Same rule applies."""
        from src.nodes.discovery import DiscoveryEvent

        def fake(scope, host="", **kw):
            yield DiscoveryEvent("biggest", "Biggest is a[/dim]b")
            yield DiscoveryEvent("done", "Found 1 computer.", finished=True)

        monkeypatch.setattr("src.cli._discover", fake)
        result = CliRunner().invoke(
            app, ["node", "scan", "--scope", "this-machine", "--yes"]
        )
        assert result.exit_code == 0, result.output

    def test_a_bracketed_name_is_quoted_back_when_nothing_matches(
        self, store_path
    ):
        """The two "nothing stored called X" paths echo what was typed.

        Exit 1 alone is not evidence here: a markup abort also surfaces as
        exit 1 through the runner. So the sentence itself has to be on
        screen, quoting the name back as it was typed.
        """
        runner = CliRunner()
        for command in ("show", "forget"):
            result = runner.invoke(app, ["node", command, "a[/dim]b"])
            assert result.exit_code == 1, result.output
            assert "Nothing stored called 'a[/dim]b'." in result.output


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
