# tests/test_node_cli.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""The command line, in the same voice as the desktop.

Not terse. A person who reached for a terminal still deserves sentences, and
the copy rules of the design apply here exactly as they do on screen.
"""

import json
import re

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

#: The words design §3.1.1 forbids, in its own order. Every one of them
#: characterises the reader's hardware instead of reporting a figure, and the
#: whole point of the rule is that whether five words a second is slow depends
#: on work this program knows nothing about.
#:
#: This is the spec's list and nothing else. "weak" used to sit here and does
#: not appear in §3.1.1; a test that invents its own rules stops being
#: evidence about the rules that exist.
JUDGEMENT = [
    "slow", "fast", "good", "poor", "powerful", "limited", "adequate",
    "sufficient", "plenty", "only",
]

#: The phrases design §3.1.2 forbids. Each asserts an ownership nobody
#: established: the person reading may be setting a machine up for somebody
#: else, and this runtime already names a step's performer in its own data.
#: Singular entries catch their plurals as substrings.
OWNERSHIP = [
    "stays with you", "your workflow", "your model", "off your hands",
    "my network",
]

#: Copy the spec writes out and approves, which nonetheless contains a word on
#: the JUDGEMENT list. These are removed from the output before the words are
#: hunted for, and nothing else is.
#:
#: WHY THIS EXISTS, so the next reader does not delete it as clutter: §3.1.1
#: forbids "only" as a verdict about hardware — "8 GB is only..." — and the
#: same goes for "plenty" and "limited". It does not forbid the ordinary
#: adverb of restriction, and the spec's own approved copy uses it, twice, to
#: promise a person that nothing will be examined beyond what they permitted.
#: A plain `word in output` check would fail on the exact sentences the spec
#: endorses, and the two ways out of that — quietly dropping "only" from the
#: list, or quietly rewriting approved copy until the test goes green — both
#: throw away the rule instead of enforcing it.
#:
#: So: allow the endorsed phrase, then match what is left on word boundaries.
#: Boundaries matter on their own. "fastest measured speed" (§3.6) is a
#: comparison between figures, not a verdict on any of them, and \bfast\b
#: leaves it alone while still catching "that will be fast".
ENDORSED = [
    'only checks this computer',   # §3.2, the empty Environment tab
    'i check that one only',       # §3.3, the second rung of the permission
]


def judgements_in(output: str) -> list[str]:
    """Every forbidden verdict in this output, ignoring copy the spec endorses."""
    remaining = output.lower()
    for phrase in ENDORSED:
        remaining = remaining.replace(phrase, " ")
    return [w for w in JUDGEMENT if re.search(rf"\b{w}\b", remaining)]


def ownership_in(output: str) -> list[str]:
    """Every phrase in this output that claims someone owns something."""
    lowered = output.lower()
    return [p for p in OWNERSHIP if p in lowered]


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
        result = CliRunner().invoke(app, ["node", "scan"], input="4\n")
        assert result.exit_code == 3, result.output
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
        (["node", "add", "--label", "Kitchen Box", "--kind", "ollama",
          "--url", "http://10.0.0.9:11434"], None),
        (["node", "forget", "home-pc"], None),
        (["node", "scan", "--scope", "this-machine", "--yes"], None),
        (["node", "scan", "--scope", "none", "--yes"], None),
        (["node", "scan", "--scope", "local-network", "--yes"], None),
        (["node", "scan"], "1\n"),
        (["node", "scan"], "3\n"),
        (["node", "scan"], "4\n"),
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
