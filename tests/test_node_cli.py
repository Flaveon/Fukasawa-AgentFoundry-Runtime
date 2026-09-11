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
    HostCapability,
    InferenceNode,
    ModelCapability,
    NodeKind,
    ScanConsent,
    ScanScope,
)
from tests.copy_rules import judgements_in, ownership_in


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


class TestShow:
    """One computer's card: every figure with its unit, and no verdict."""

    def test_the_figures_are_rendered_in_words_a_reader_can_use(self, store_path):
        seed(store_path, host=HostCapability(gpu_present=True,
                                             vram_bytes=6_000_000_000,
                                             tokens_per_second=53.0))
        result = CliRunner().invoke(app, ["node", "show", "home-pc"])
        assert result.exit_code == 0, result.output
        assert "Home PC" in result.output
        assert "about 40 words a second" in result.output
        assert "6 GB or more" in result.output
        assert "llama3.1:8b" in result.output
        assert "about 6,100 words" in result.output

    def test_figures_never_measured_read_as_not_sure(self, store_path):
        """Zero is not a reading. Nothing was established, and it says so."""
        seed(store_path)
        result = CliRunner().invoke(app, ["node", "show", "home-pc"])
        assert result.exit_code == 0, result.output
        assert result.output.count("not sure") == 2

    def test_a_computer_with_no_models_still_renders(self, store_path):
        seed(store_path, models=[])
        result = CliRunner().invoke(app, ["node", "show", "home-pc"])
        assert result.exit_code == 0, result.output
        assert "Home PC" in result.output

    def test_asking_for_something_absent_names_what_was_asked_for(
        self, store_path
    ):
        seed(store_path)
        result = CliRunner().invoke(app, ["node", "show", "garage-pc"])
        assert result.exit_code == 1, result.output
        assert "garage-pc" in result.output


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

        The scan here FINDS something, and that is the point. A scan that
        finds nothing never reaches the summary panel, so a stand-in that
        yields no node cannot see whether human text is being written into
        the stream -- which is the same blind spot, in the same command, that
        the wrapping bug hid behind. Every line is parsed, blanks included:
        one object per line means no decoration before, between, or after.
        """
        from src.nodes.discovery import DiscoveryEvent

        message = "Biggest is a model with a very long name [red] indeed here"
        found = InferenceNode(
            node_id="found-pc", label="Found PC", kind=NodeKind.OLLAMA,
            url="http://127.0.0.1:11434", reachable=True,
            models=[ModelCapability(name="llama3.1:8b", context_length=8192)],
        )

        def fake(scope, host="", **kw):
            yield DiscoveryEvent("biggest", message)
            yield DiscoveryEvent(
                "done", "Found 1 computer.", node=found, finished=True
            )

        monkeypatch.setattr("src.cli._discover", fake)
        result = CliRunner(env={"COLUMNS": "60"}).invoke(
            app, ["node", "scan", "--scope", "this-machine", "--yes", "--json"]
        )
        assert result.exit_code == 0, result.output
        events = [json.loads(ln) for ln in result.output.splitlines()]
        assert events[0]["message"] == message
        assert events[-1]["finished"] is True

    def test_a_scan_that_finds_something_shows_a_person_the_summary(
        self, store_path, monkeypatch
    ):
        """The other half of the rule above: withheld from a stream, kept here.

        Nothing else in this file asserts that the summary panel is ever
        printed, so the guard that keeps it out of --json would read exactly
        like a guard that removed it altogether, and every test would still
        pass. This is the assertion that tells those two apart.
        """
        from src.nodes.discovery import DiscoveryEvent

        found = InferenceNode(
            node_id="found-pc", label="Found PC", kind=NodeKind.OLLAMA,
            url="http://127.0.0.1:11434", reachable=True,
            models=[ModelCapability(name="llama3.1:8b", context_length=8192)],
        )

        def fake(scope, host="", **kw):
            yield DiscoveryEvent(
                "done", "Found 1 computer.", node=found, finished=True
            )

        monkeypatch.setattr("src.cli._discover", fake)
        result = CliRunner().invoke(
            app, ["node", "scan", "--scope", "this-machine", "--yes"]
        )
        assert result.exit_code == 0, result.output
        assert "What this means when steps run" in result.output
        # A figure with its unit, per §3.1.1 -- not a verdict about the box.
        assert "8,192 tokens" in result.output


class TestTheConsentPrompt:
    """Nothing opens a socket until somebody has said how far to look.

    That question is the whole privacy story of this feature, and every
    other test here hands it a flag so it never appears. These drive it the
    way a person does. The stand-in for discovery is substituted on every
    path that would reach it: no test in this file touches a network.
    """

    @pytest.fixture()
    def asked(self, monkeypatch):
        """Record what discovery was asked to look at, without looking."""
        from src.nodes.discovery import DiscoveryEvent

        calls = []

        def fake(scope, host="", **kw):
            calls.append((scope, host))
            yield DiscoveryEvent("done", "Found 1 computer.", finished=True)

        monkeypatch.setattr("src.cli._discover", fake)
        return calls

    def test_the_four_choices_are_offered_in_sentences(self, store_path, asked):
        result = CliRunner().invoke(app, ["node", "scan"], input="1\n")
        assert "Where should I look?" in result.output
        assert "nothing leaves this machine" in result.output
        assert "I'll type it in" in result.output

    def test_choosing_this_computer_looks_only_here(self, store_path, asked):
        result = CliRunner().invoke(app, ["node", "scan"], input="1\n")
        assert result.exit_code == 0, result.output
        assert asked == [(ScanScope.THIS_MACHINE, "")]

    def test_choosing_a_named_computer_asks_for_the_address(
        self, store_path, asked
    ):
        result = CliRunner().invoke(app, ["node", "scan"], input="2\n10.0.0.9\n")
        assert result.exit_code == 0, result.output
        assert "Address of the computer" in result.output
        assert asked == [(ScanScope.NAMED_HOST, "10.0.0.9")]

    def test_choosing_the_whole_network_looks_at_nothing(self, store_path, asked):
        """Not built yet, so nothing is examined. Covered fully elsewhere."""
        result = CliRunner().invoke(app, ["node", "scan"], input="3\n")
        assert result.exit_code == 1, result.output
        assert asked == []

    def test_choosing_not_to_look_looks_at_nothing(self, store_path, asked):
        """A route this program offers, taken: success, and nothing contacted.

        Covered fully in TestTypingItIn. This one holds the menu's side of it.
        """
        result = CliRunner().invoke(
            app, ["node", "scan"], input="4\nKitchen Box\n10.0.0.9\n1\nn\n"
        )
        assert result.exit_code == 0, result.output
        assert asked == []

    def test_pressing_enter_takes_the_careful_route(self, store_path, asked):
        """The default has to be the one where nothing leaves the machine."""
        result = CliRunner().invoke(app, ["node", "scan"], input="\n")
        assert result.exit_code == 0, result.output
        assert asked == [(ScanScope.THIS_MACHINE, "")]

    def test_an_answer_off_the_menu_takes_the_careful_route_too(
        self, store_path, asked
    ):
        CliRunner().invoke(app, ["node", "scan"], input="9\n")
        assert asked == [(ScanScope.THIS_MACHINE, "")]

    def test_the_choice_is_remembered(self, store_path, asked):
        """Answered once, so a later scan does not ask again."""
        CliRunner().invoke(app, ["node", "scan"], input="2\n10.0.0.9\n")
        _nodes, consent = NodeStore(store_path).load()
        assert consent.scope is ScanScope.NAMED_HOST


class TestTypingItIn:
    """Menu choice 4, "Don't look — I'll type it in", as the operator ruled it.

    Four rulings (M8, handoffs/phase-10a-node-and-capability-handoff.md):
    success rather than "Refused"; a name and an address asked for and saved;
    typing an address is NOT permission to contact it; and the opening copy
    differs by whether anything is recorded yet.

    The permission ruling is the one worth guarding hardest, so every test
    here substitutes discovery with a recorder and says what it was asked to
    look at. "Nothing was contacted" is checked as an empty recording, not
    inferred from an exit code.
    """

    TYPED = "4\nKitchen Box\n10.0.0.9\n1\n"

    @pytest.fixture()
    def looked_at(self, monkeypatch):
        """Record every look, and answer one at 10.0.0.9 with a real finding.

        The finding carries a DIFFERENT id and name from the ones typed —
        what discovery really produces, since it names what it finds after
        the address. A stand-in reusing the typed name could not tell a merge
        into the typed record from a second record that happens to match.
        """
        from src.nodes.discovery import DiscoveryEvent

        calls = []

        def fake(scope, host="", **kw):
            calls.append((scope, host))
            if host == "http://10.0.0.9:11434":
                node = InferenceNode(
                    node_id="ollama-10-0-0-9-11434", label="Ollama on 10.0.0.9",
                    kind=NodeKind.OLLAMA, url=host, reachable=True,
                    models=[ModelCapability(name="llama3.1:8b",
                                            context_length=8192)],
                )
                yield DiscoveryEvent("done", "Found 1 computer.", node=node,
                                     finished=True)
            else:
                yield DiscoveryEvent("done", "Found 0 computers.", finished=True)

        monkeypatch.setattr("src.cli._discover", fake)
        return calls

    def test_declining_the_check_contacts_nothing_and_succeeds(
        self, store_path, looked_at
    ):
        result = CliRunner().invoke(app, ["node", "scan"], input=self.TYPED + "n\n")
        assert result.exit_code == 0, result.output
        assert looked_at == []
        assert "Refused" not in result.output

    def test_the_check_is_not_assumed(self, store_path, looked_at):
        """Pressing Enter at the question takes the answer that contacts nothing.

        Typing an address is not permission to contact it, so the default
        cannot be yes. Deleting ``default=False`` makes this red.
        """
        result = CliRunner().invoke(app, ["node", "scan"], input=self.TYPED + "\n")
        assert result.exit_code == 0, result.output
        assert looked_at == []

    def test_what_was_typed_is_saved_unchecked(self, store_path, looked_at):
        CliRunner().invoke(app, ["node", "scan"], input=self.TYPED + "n\n")
        nodes, _ = NodeStore(store_path).load()
        assert [(n.node_id, n.label, n.kind, n.url) for n in nodes] == [
            ("kitchen-box", "Kitchen Box", NodeKind.OLLAMA,
             "http://10.0.0.9:11434"),
        ]
        assert nodes[0].reachable is False
        for field in ("label", "url", "kind"):
            assert nodes[0].source_of(field).value == "DECLARED", field

    def test_a_bare_address_gets_the_port_of_the_program_named(
        self, store_path, looked_at
    ):
        CliRunner().invoke(
            app, ["node", "scan"], input="4\nKitchen Box\n10.0.0.9\n2\nn\n"
        )
        nodes, _ = NodeStore(store_path).load()
        assert (nodes[0].kind, nodes[0].url) == (
            NodeKind.LLAMACPP, "http://10.0.0.9:8081"
        )

    def test_an_answer_off_the_list_is_asked_again_not_guessed(
        self, store_path, looked_at
    ):
        """There is no careful default for which program is running.

        A guess would be saved as something the person told us, and nothing
        would ever contact the computer to correct it.
        """
        result = CliRunner().invoke(
            app, ["node", "scan"], input="4\nKitchen Box\n10.0.0.9\n7\n2\nn\n"
        )
        assert result.exit_code == 0, result.output
        assert "Choose 1 or 2" in result.output
        nodes, _ = NodeStore(store_path).load()
        assert nodes[0].kind is NodeKind.LLAMACPP

    def test_a_name_given_as_a_flag_is_offered_as_the_answer(
        self, store_path, looked_at
    ):
        CliRunner().invoke(
            app, ["node", "scan", "--label", "Garage"],
            input="4\n\n10.0.0.9\n1\nn\n",
        )
        nodes, _ = NodeStore(store_path).load()
        assert nodes[0].label == "Garage"

    def test_declining_leaves_the_permission_on_file_alone(
        self, store_path, looked_at
    ):
        """Nothing was looked at, so no permission to look was acted under."""
        seed(store_path)
        CliRunner().invoke(app, ["node", "scan"], input=self.TYPED + "n\n")
        _nodes, consent = NodeStore(store_path).load()
        assert consent.scope is ScanScope.THIS_MACHINE

    def test_saying_yes_looks_at_that_one_address_and_nothing_else(
        self, store_path, looked_at
    ):
        result = CliRunner().invoke(app, ["node", "scan"], input=self.TYPED + "y\n")
        assert result.exit_code == 0, result.output
        assert looked_at == [(ScanScope.NAMED_HOST, "http://10.0.0.9:11434")]

    def test_saying_yes_records_the_permission_it_looked_under(
        self, store_path, looked_at
    ):
        """The same rule `node scan` keeps (I6): the record says what was done."""
        seed(store_path)
        CliRunner().invoke(app, ["node", "scan"], input=self.TYPED + "y\n")
        _nodes, consent = NodeStore(store_path).load()
        assert consent.scope is ScanScope.NAMED_HOST

    def test_what_is_found_fills_in_the_record_that_was_typed(
        self, store_path, looked_at
    ):
        """One computer, keeping what the person typed, gaining what was found.

        Two failure shapes are ruled out: a second row for the same computer,
        and the typed name overwritten by the one discovery made up.
        """
        result = CliRunner().invoke(app, ["node", "scan"], input=self.TYPED + "y\n")
        nodes, _ = NodeStore(store_path).load()
        assert len(nodes) == 1
        assert (nodes[0].node_id, nodes[0].label) == ("kitchen-box", "Kitchen Box")
        assert nodes[0].reachable is True
        assert [m.name for m in nodes[0].models] == ["llama3.1:8b"]
        assert "What this means when steps run" in result.output

    def test_when_nothing_answers_the_computer_stays_saved(
        self, store_path, looked_at
    ):
        result = CliRunner().invoke(
            app, ["node", "scan"], input="4\nKitchen Box\n10.0.0.8\n1\ny\n"
        )
        assert result.exit_code == 0, result.output
        assert "is still saved" in result.output
        nodes, _ = NodeStore(store_path).load()
        assert [n.label for n in nodes] == ["Kitchen Box"]

    def test_a_computer_listed_unchecked_says_so(self, store_path, looked_at):
        """M5, option C: typed in and not looked at, it is counted, as unchecked."""
        runner = CliRunner()
        runner.invoke(app, ["node", "scan"], input=self.TYPED + "n\n")
        result = runner.invoke(app, ["node", "list"])
        assert "Kitchen Box (not checked yet)" in result.output
        assert "No step can be assigned" not in result.output

    def test_a_look_that_finds_nothing_is_recorded_as_a_look(
        self, store_path, looked_at
    ):
        """Discovery saves only what answers, so the record has to be stamped.

        Without it the record would still read "not checked yet" after it was
        checked -- and under M5 option C an unchecked computer is counted.
        What the person typed survives the stamp.
        """
        runner = CliRunner()
        runner.invoke(
            app, ["node", "scan"], input="4\nKitchen Box\n10.0.0.8\n1\ny\n"
        )
        nodes, _ = NodeStore(store_path).load()
        assert nodes[0].last_probed_at is not None
        assert nodes[0].reachable is False
        assert (nodes[0].label, nodes[0].source_of("label").value) == (
            "Kitchen Box", "DECLARED"
        )
        listing = runner.invoke(app, ["node", "list"]).output
        assert "not checked yet" not in listing

    def test_an_address_already_recorded_is_named_and_nothing_changes(
        self, store_path, looked_at
    ):
        """I5, on this path. The row there is not renamed and nothing is added.

        The seeded row carries no typed provenance, which is the case that
        used to be worst: the merge applied the typed name to it.
        """
        seed(store_path)
        result = CliRunner().invoke(
            app, ["node", "scan"], input="4\nKitchen Box\nlocalhost\n1\n"
        )
        assert result.exit_code == 1, result.output
        assert "Already recorded at that address as" in result.output
        assert "Home PC" in result.output
        assert "May I contact it" not in result.output
        nodes, _ = NodeStore(store_path).load()
        assert [(n.node_id, n.label) for n in nodes] == [("home-pc", "Home PC")]
        assert looked_at == []

    def test_with_nothing_recorded_the_copy_says_so(self, store_path, looked_at):
        result = CliRunner().invoke(app, ["node", "scan"], input=self.TYPED + "n\n")
        assert "No computers are recorded yet." in result.output
        assert "Recorded so far" not in result.output

    def test_with_computers_recorded_the_copy_names_them(
        self, store_path, looked_at
    ):
        """Somebody adding a fourth computer is not told they have none.

        The menu appears whenever a scan runs without flags, however many
        computers are recorded -- an assumption the handoff records as
        checked and found false.
        """
        seed(store_path)
        result = CliRunner().invoke(app, ["node", "scan"], input=self.TYPED + "n\n")
        assert "Recorded so far: Home PC." in result.output
        assert "No computers are recorded yet." not in result.output

    def test_the_copy_on_an_empty_store_obeys_both_rules(
        self, store_path, looked_at
    ):
        """TestCopyRules seeds a computer, so it never sees the empty branch."""
        for answer in ("n\n", "y\n"):
            output = CliRunner().invoke(
                app, ["node", "scan"], input=self.TYPED + answer
            ).output
            assert judgements_in(output) == []
            assert ownership_in(output) == []


class TestRefusingToLookStaysARefusal:
    """The other half of M8: the flag paths keep exit 3 and ask nothing."""

    def test_the_flag_is_still_refused(self, store_path):
        result = CliRunner().invoke(app, ["node", "scan", "--scope", "none", "--yes"])
        assert result.exit_code == 3, result.output
        assert "What should I call it?" not in result.output

    def test_none_on_file_with_yes_is_still_refused(self, store_path):
        """A bare --yes reading "none" off the file is not the menu choice."""
        NodeStore(store_path).save([], ScanConsent.granted(ScanScope.NONE, "sam"))
        result = CliRunner().invoke(app, ["node", "scan", "--yes"])
        assert result.exit_code == 3, result.output
        assert "What should I call it?" not in result.output


class TestSkippingThePrompts:
    """--yes says it skips the prompts, so it has to skip all of them."""

    def test_naming_a_computer_without_an_address_says_which_flag_is_missing(
        self, store_path
    ):
        """One prompt was left in, and it was the one --yes could not answer.

        Exit 1 on its own proves nothing: an unanswerable prompt on a closed
        input also ends at exit 1, having printed half a question. What is
        checked is that the question is not asked at all and the missing
        flag is named.
        """
        result = CliRunner().invoke(
            app, ["node", "scan", "--scope", "named-host", "--yes"]
        )
        assert result.exit_code == 1, result.output
        assert "Address of the computer" not in result.output
        assert "--host" in result.output

    def test_the_same_holds_when_the_permission_came_off_the_file(
        self, store_path
    ):
        """A bare --yes reads the stored permission and lands in the same place."""
        store = NodeStore(store_path)
        store.save([], ScanConsent.granted(ScanScope.NAMED_HOST, "sam"))
        result = CliRunner().invoke(app, ["node", "scan", "--yes"])
        assert result.exit_code == 1, result.output
        assert "--host" in result.output


class TestTheWholeNetworkIsNotBuiltYet:
    """Asking for the sweep of a whole network is answered, not crashed.

    The sweep is out of this plan's scope. The plan said so and said the
    refusal should be legible. Two things have to hold: the person is told
    what to do instead, and the permission is never written down, because a
    permission the program cannot act on turns one mistake into a permanent
    one — every later scan reads it back and hits the same wall.
    """

    def _assert_answered(self, result):
        assert result.exit_code == 1, result.output
        assert "not built yet" in result.output
        assert "named-host" in result.output

    def test_the_flag_is_answered_in_sentences(self, store_path):
        seed(store_path)
        self._assert_answered(CliRunner().invoke(
            app, ["node", "scan", "--scope", "local-network", "--yes"]
        ))

    def test_the_third_choice_on_the_menu_is_answered_the_same_way(
        self, store_path
    ):
        seed(store_path)
        self._assert_answered(
            CliRunner().invoke(app, ["node", "scan"], input="3\n")
        )

    def test_the_permission_on_file_is_left_alone(self, store_path):
        """Nothing unusable is stored, so the next scan is unaffected."""
        seed(store_path)
        CliRunner().invoke(app, ["node", "scan", "--scope", "local-network", "--yes"])
        _nodes, consent = NodeStore(store_path).load()
        assert consent.scope is ScanScope.THIS_MACHINE

    def test_a_later_scan_looks_where_the_permission_on_file_says(
        self, store_path, monkeypatch
    ):
        """The proof the mistake did not stick.

        The next bare scan has to look at this computer, which is what the
        file says. Exit code alone would not show that — the stand-in for
        discovery answers to anything — so the scope it is handed is what
        gets checked.
        """
        from src.nodes.discovery import DiscoveryEvent

        seed(store_path)
        runner = CliRunner()
        runner.invoke(app, ["node", "scan", "--scope", "local-network", "--yes"])

        asked = []

        def fake(scope, host="", **kw):
            asked.append(scope)
            yield DiscoveryEvent("done", "Found 1 computer.", finished=True)

        monkeypatch.setattr("src.cli._discover", fake)
        result = runner.invoke(app, ["node", "scan", "--yes"])
        assert result.exit_code == 0, result.output
        assert asked == [ScanScope.THIS_MACHINE]


class TestAddAndForget:
    def test_a_computer_can_be_added_by_hand(self, store_path):
        result = CliRunner().invoke(app, [
            "node", "add", "--label", "Kitchen Box", "--kind", "ollama",
            "--url", "http://10.0.0.9:11434",
        ])
        assert result.exit_code == 0, result.output
        # The name reported is the name stored. Nothing checked this until I5,
        # which was precisely a report naming a computer that was not stored.
        assert "Added Kitchen Box." in result.output
        nodes, _ = NodeStore(store_path).load()
        assert nodes[0].node_id == "kitchen-box"
        assert nodes[0].source_of("url").value == "DECLARED"

    def test_adding_at_an_address_already_recorded_changes_nothing(
        self, store_path
    ):
        """I5: the command used to say "Added Kitchen Box." and rename Home PC.

        `upsert` matches on address and merges, which is right for a rescan.
        The seeded row has no typed provenance -- the worst case, where the
        typed name and program were applied to the row already there. Every
        part of the lie is checked: the claim, the rename, the retype, and a
        count that did not move.
        """
        seed(store_path)
        result = CliRunner().invoke(app, [
            "node", "add", "--label", "Kitchen Box", "--kind", "llamacpp",
            "--url", "http://localhost:11434",
        ])
        assert result.exit_code == 1, result.output
        assert "Added" not in result.output
        assert "Home PC" in result.output
        assert "fukasawa node show home-pc" in result.output
        nodes, _ = NodeStore(store_path).load()
        assert [(n.node_id, n.label, n.kind) for n in nodes] == [
            ("home-pc", "Home PC", NodeKind.OLLAMA),
        ]

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

    def test_the_whole_network_permission_is_answered_not_recorded(
        self, store_path
    ):
        """`node scan` already refuses this reach. Granting it did not.

        Without this guard `node consent --set local-network` exited 0 and
        wrote the permission down, after which every scan read it back and
        hit the wall `node scan` puts up — and clearing it meant knowing to
        run a command nothing mentions. The two verbs have to agree, or the
        screen says the reach was granted while nothing acts on it.

        Exit 1, matching the `node scan` branch and for the reason stated
        there: nothing is being refused as a matter of doctrine, the sweep
        has not been written. src/cli.py documents 3 for the former.
        """
        seed(store_path)
        result = CliRunner().invoke(
            app, ["node", "consent", "--set", "local-network"]
        )
        assert result.exit_code == 1, result.output
        assert "not built yet" in result.output
        _nodes, consent = NodeStore(store_path).load()
        assert consent.scope is ScanScope.THIS_MACHINE

    def test_the_answer_names_a_permission_that_does_work(self, store_path):
        """A dead end with no exit is how a person ends up stuck."""
        seed(store_path)
        output = CliRunner().invoke(
            app, ["node", "consent", "--set", "local-network"]
        ).output
        assert "named-host" in output
        assert "this-machine" in output


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
    """Every one of the six commands, against both rules of design §3.1.

    All six, because a rule enforced on two of them is a rule two thirds
    unenforced, and the two left out were the ones printing the most figures
    and all of the permission copy.

    The scan cases below reach discovery through a stand-in, so the words
    checked are still the ones the product prints — the stand-in supplies the
    stream, not the sentences.
    """

    @pytest.fixture()
    def a_scan_that_finds_something(self, store_path, monkeypatch):
        """A scan that reports real findings about a real computer, offline.

        The lines come from discovery's own describing function, so this
        checks product copy rather than copy invented by this test.
        """
        from src.nodes.discovery import DiscoveryEvent, _describe

        node = InferenceNode(
            node_id="home-pc", label="Home PC", kind=NodeKind.OLLAMA,
            url="http://localhost:11434", reachable=True, backend_version="0.5.4",
            models=[ModelCapability(name="llama3.1:8b", context_length=8192,
                                    size_bytes=4_700_000_000)],
            host=HostCapability(gpu_present=True, vram_bytes=6_000_000_000,
                                tokens_per_second=53.0),
        )

        def fake(scope, host="", **kw):
            for stage, message in _describe(node):
                yield DiscoveryEvent(stage, message)
            yield DiscoveryEvent("done", "Found one computer.", node=node,
                                 finished=True)

        monkeypatch.setattr("src.cli._discover", fake)

    @pytest.mark.parametrize("argv,typed", [
        (["node", "list"], None),
        (["node", "show", "home-pc"], None),
        (["node", "consent"], None),
        (["node", "consent", "--set", "this-machine"], None),
        (["node", "consent", "--set", "local-network"], None),
        (["node", "add", "--label", "Kitchen Box", "--kind", "ollama",
          "--url", "http://10.0.0.9:11434"], None),
        # An address already recorded: the refusal naming who holds it.
        (["node", "add", "--label", "Kitchen Box", "--kind", "ollama",
          "--url", "http://localhost:11434"], None),
        (["node", "forget", "home-pc"], None),
        (["node", "scan", "--scope", "this-machine", "--yes"], None),
        (["node", "scan", "--scope", "none", "--yes"], None),
        (["node", "scan", "--scope", "local-network", "--yes"], None),
        (["node", "scan"], "1\n"),
        (["node", "scan"], "3\n"),
        # Choice 4 to the end, both answers to the check, and a collision.
        (["node", "scan"], "4\nKitchen Box\n10.0.0.9\n1\nn\n"),
        (["node", "scan"], "4\nKitchen Box\n10.0.0.9\n1\ny\n"),
        (["node", "scan"], "4\nKitchen Box\nlocalhost\n1\n"),
    ])
    def test_no_command_judges_or_assumes_ownership(
        self, store_path, a_scan_that_finds_something, argv, typed
    ):
        seed(store_path, host=HostCapability(gpu_present=True,
                                             vram_bytes=6_000_000_000,
                                             tokens_per_second=53.0))
        output = CliRunner().invoke(app, argv, input=typed).output
        assert judgements_in(output) == []
        assert ownership_in(output) == []

    def test_the_endorsed_use_of_only_is_told_apart_from_the_forbidden_one(self):
        """The allowlist has to discriminate, not just excuse the word.

        Without this, an allowlist that swallowed every "only" would look
        exactly as green as one that works.
        """
        assert judgements_in('"Look for it" only checks this computer.') == []
        assert judgements_in("8 GB is only enough for small models.") == ["only"]

    def test_a_comparison_between_figures_is_not_a_verdict_on_one(self):
        """Word boundaries, so §3.6's "Fastest measured speed" stays legal."""
        assert judgements_in("Fastest measured speed  40 words a second") == []
        assert judgements_in("This computer is fast.") == ["fast"]
