# tests/test_gui_nodes.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""The desktop's half of node management. Tk-free, always runs.

Two things in this file are deliberate and easy to mistake for clutter.

**Nothing here may open a socket.** The autouse ``no_sockets`` fixture below
replaces ``urllib.request.urlopen`` with something that raises, so a scan that
reaches the network fails loudly instead of quietly. That matters more than
usual: ``probe_ollama`` swallows ``OSError`` at every stage, so a real
connection attempt that is refused looks exactly like a stand-in that declined
to answer. The Task 4 review found a fake blind to POST for precisely this
reason. An ``AssertionError`` is not an ``OSError`` and is not swallowed.

**The copy rules are imported, not re-stated.** ``judgements_in`` and
``ownership_in`` come from ``tests/test_node_cli.py`` so the two front ends are
policed by one word list. A second copy would drift, and the first thing to
drift out of it would be the awkward case the list exists to handle.
"""

import pathlib
import urllib.request

import pytest

from src.gui.services import nodes as service
from src.nodes.backends import PORTS
from src.nodes.store import NodeStore
from src.schemas.node import (
    HostCapability,
    InferenceNode,
    ModelCapability,
    NodeKind,
    Provenance,
    ScanScope,
)
from tests.test_node_cli import judgements_in, ownership_in

#: Every address ``THIS_MACHINE`` is allowed to reach. Anything else appearing
#: in a recorder's log is a scan that went further than it was permitted. Taken
#: from the port table rather than typed out, so adding a backend cannot make
#: the assertion pass by describing a scan nobody performs.
LOOPBACK = {f"127.0.0.1:{port}" for port, _kind in PORTS}


@pytest.fixture(autouse=True)
def no_sockets(monkeypatch):
    """Make any real network call in this file a loud failure.

    Patched at ``urllib.request.urlopen`` rather than at the two helpers in
    ``src.nodes.backends``, on purpose: patching the helpers would ALSO hide a
    service that forgot to forward its stand-in, which is the defect these
    tests exist to catch.
    """

    def explode(*_args, **_kwargs):
        raise AssertionError("a test opened a socket")

    monkeypatch.setattr(urllib.request, "urlopen", explode)


class Recorder:
    """A fetcher and poster that record every URL asked for, by either verb.

    The same shape as ``tests/test_node_discovery.py``'s recorder, and for the
    same reason: GETs and POSTs land in one list, so a scope assertion over
    ``hosts()`` polices both verbs rather than only the one that is easy to
    fake.
    """

    def __init__(self, answering: set[str] | None = None):
        self.asked: list[str] = []
        self.answering = answering if answering is not None else {"127.0.0.1:11434"}

    def __call__(self, url: str, timeout: float = 0.0) -> dict:
        self.asked.append(url)
        if not any(host in url for host in self.answering):
            raise OSError("connection refused")
        if url.endswith("/api/version"):
            return {"version": "0.5.4"}
        if url.endswith("/api/tags"):
            return {"models": [{"name": "llama3.1:8b", "size": 1,
                                "details": {"family": "llama"}}]}
        if url.endswith("/api/ps"):
            return {"models": []}
        return {"model_info": {"llama.context_length": 8192}, "capabilities": []}

    def post(self, url: str, payload: dict, timeout: float = 0.0) -> dict:
        """Record and answer a POST the way ``/api/show`` would."""
        self.asked.append(url)
        if not any(host in url for host in self.answering):
            raise OSError("connection refused")
        return {"model_info": {"llama.context_length": 8192}, "capabilities": []}

    def hosts(self) -> set[str]:
        """Every distinct host:port attempted, by either verb."""
        return {u.split("//", 1)[1].split("/", 1)[0] for u in self.asked}


@pytest.fixture()
def store(tmp_path) -> NodeStore:
    return NodeStore(tmp_path / "nodes.yaml")


def seed(store: NodeStore) -> None:
    store.upsert(InferenceNode(
        node_id="home-pc", label="Home PC", kind=NodeKind.OLLAMA,
        url="http://localhost:11434", reachable=True,
        models=[ModelCapability(name="llama3.1:8b", context_length=8192)],
        host=HostCapability(gpu_present=True, vram_bytes=6_000_000_000,
                            tokens_per_second=53.0),
        provenance={
            "models": Provenance.DETECTED,
            "url": Provenance.DETECTED,
            "host.vram_bytes": Provenance.DETECTED,
            "host.tokens_per_second": Provenance.MEASURED,
        },
    ))


class TestListing:
    def test_empty_store_is_not_a_failure(self, store):
        result = service.list_nodes(store)
        assert result.ok
        assert result.rows == []
        assert "do not require a computer" in result.consequence

    def test_rows_carry_plain_language_sources(self, store):
        seed(store)
        row = service.list_nodes(store).rows[0]
        assert row.label == "Home PC"
        fields = {f.label: f for f in row.fields}
        assert fields["Longest input"].source == "found it"
        assert fields["Longest input"].value == "about 6,100 words"
        assert fields["Speed"].source == "measured"

    def test_the_name_and_address_are_editable_and_the_figures_are_not(self, store):
        """Only what a person can meaningfully type is offered for editing.

        Marking a measured figure editable would invite somebody to type over
        a reading and have it come back as "you told me" — the source column
        would be honest and the number would be fiction.
        """
        seed(store)
        row = service.list_nodes(store).rows[0]
        editable = {f.label for f in row.fields if f.editable}
        assert editable == {"Call it", "Address"}

    def test_the_panel_rows_come_through(self, store):
        """§3.6's panel is the reason to capture any of this."""
        seed(store)
        result = service.list_nodes(store)
        labels = [label for label, _value in result.summary_rows]
        assert "Agent steps can run on" in labels
        assert dict(result.summary_rows)["Agent steps can run on"] == "Home PC"


class TestEditing:
    def test_editing_a_field_marks_it_as_typed(self, store):
        seed(store)
        assert service.update_field("home-pc", "label", "Kitchen Box", store).ok
        nodes, _ = store.load()
        assert nodes[0].label == "Kitchen Box"
        assert nodes[0].source_of("label") is Provenance.DECLARED

    def test_editing_an_unknown_computer_is_a_refusal_not_a_crash(self, store):
        result = service.update_field("nope", "label", "x", store)
        assert not result.ok
        assert "nope" in result.refusal

    def test_an_unknown_field_is_refused(self, store):
        seed(store)
        result = service.update_field("home-pc", "bogus", "x", store)
        assert not result.ok
        assert "bogus" in result.refusal

    def test_an_unknown_kind_is_refused_and_nothing_is_written(self, store):
        seed(store)
        result = service.update_field("home-pc", "kind", "tealeaves", store)
        assert not result.ok
        nodes, _ = store.load()
        assert nodes[0].kind is NodeKind.OLLAMA

    def test_a_known_kind_is_stored_as_the_enum(self, store):
        seed(store)
        assert service.update_field("home-pc", "kind", "llamacpp", store).ok
        nodes, _ = store.load()
        assert nodes[0].kind is NodeKind.LLAMACPP


class TestAddingByHand:
    def test_a_typed_computer_is_stored_and_marked_as_typed(self, store):
        assert service.add_node("Kitchen Box", "ollama",
                                "http://10.0.0.9:11434", store).ok
        nodes, _ = store.load()
        assert nodes[0].label == "Kitchen Box"
        assert nodes[0].source_of("url") is Provenance.DECLARED

    @pytest.mark.parametrize("label,url", [("", "http://x:11434"), ("X", "  ")])
    def test_a_missing_name_or_address_is_refused(self, store, label, url):
        result = service.add_node(label, "ollama", url, store)
        assert not result.ok
        nodes, _ = store.load()
        assert nodes == []

    def test_an_unknown_kind_is_refused(self, store):
        result = service.add_node("X", "tealeaves", "http://x:11434", store)
        assert not result.ok
        assert "tealeaves" in result.refusal

    def test_forgetting_removes_one(self, store):
        seed(store)
        assert service.forget_node("home-pc", store).ok
        nodes, _ = store.load()
        assert nodes == []

    def test_forgetting_something_unstored_is_a_refusal(self, store):
        result = service.forget_node("nope", store)
        assert not result.ok
        assert "nope" in result.refusal


class TestConsent:
    def test_consent_is_recorded(self, store):
        assert service.save_consent(ScanScope.THIS_MACHINE, "sam", store).ok
        _nodes, consent = store.load()
        assert consent.scope is ScanScope.THIS_MACHINE
        assert consent.granted_by == "sam"

    def test_a_permission_nothing_can_act_on_is_not_written_down(self, store):
        """The whole-network sweep is not built, so granting it is refused.

        Same call the CLI made (`src/cli.py`, the LOCAL_NETWORK branch of
        `node scan`) and for the same reason: a stored permission that every
        later scan refuses is worse than no permission, because the screen
        then says the reach was granted while nothing acts on it.
        """
        result = service.save_consent(ScanScope.LOCAL_NETWORK, "sam", store)
        assert not result.ok
        assert result.refusal
        _nodes, consent = store.load()
        assert consent.scope is ScanScope.NONE


class TestScanning:
    def test_scanning_without_permission_refuses_and_opens_nothing(self, store):
        recorder = Recorder()
        events = list(service.scan(ScanScope.NONE, store=store,
                                   fetch=recorder, post=recorder.post))
        assert recorder.asked == [], "NONE must not open a single connection"
        assert events[-1].finished
        assert not events[-1].ok

    def test_the_whole_network_sweep_is_refused_rather_than_raised(self, store):
        """`candidate_addresses` raises ConsentRefused for this scope.

        Letting that exception reach a view is a crash on a button press. The
        service answers in words instead, and opens nothing on the way.
        """
        recorder = Recorder()
        events = list(service.scan(ScanScope.LOCAL_NETWORK, store=store,
                                   fetch=recorder, post=recorder.post))
        assert recorder.asked == []
        assert events[-1].finished
        assert not events[-1].ok
        assert "not built yet" in events[-1].message

    def test_a_named_host_with_no_address_is_refused(self, store):
        """Without this the scan reaches for `http://:11434`, which is nothing."""
        recorder = Recorder()
        events = list(service.scan(ScanScope.NAMED_HOST, "  ", store=store,
                                   fetch=recorder, post=recorder.post))
        assert recorder.asked == []
        assert events[-1].finished and not events[-1].ok

    def test_events_are_view_shaped_and_findings_are_saved(self, store):
        """Every stage discovery emitted, in the order it emitted them.

        `assert all(hasattr(e, "message") for e in events)` used to stand
        here. It is true by construction for any `ScanEventView` — a
        dataclass with a `message` field — so it could not fail, whatever the
        service did with the stream. The stage sequence can.
        """
        recorder = Recorder()
        events = list(service.scan(ScanScope.THIS_MACHINE, store=store,
                                   fetch=recorder, post=recorder.post))
        assert [e.stage for e in events] == [
            "trying", "reachable", "backend", "models", "biggest",
            "context", "hardware", "trying", "done",
        ]
        nodes, _ = store.load()
        assert nodes, "a discovered computer was not saved"

    def test_what_discovery_said_reaches_the_view_unaltered(self, store):
        """`ok`, `finished` and `message` are passed through untouched.

        None of the three was pinned before, and the assertions that looked
        like they pinned them sat where they could not fail: `events[-1]
        .finished` stays true when *every* event is forced finished, and `ok`
        and `message` on this path were not asserted at all. Replacing any of
        the three with a constant left all thirty-three tests passing.

        A recorder that answers nothing is the case where all three vary
        across one stream — two attempts that are ok and unfinished, then one
        closing event that is neither — so the shape of the whole sequence is
        what gets asserted, not the last element of it. The discovery
        passthrough is the only path where these can vary at all; the stops
        before looking build their own literals.
        """
        recorder = Recorder(answering=set())
        events = list(service.scan(ScanScope.THIS_MACHINE, store=store,
                                   fetch=recorder, post=recorder.post))
        assert [e.finished for e in events] == [False, False, True]
        assert [e.ok for e in events] == [True, True, False]
        assert [e.message for e in events] == [
            "Looking on port 11434...",
            "Looking on port 8081...",
            "Didn't find anything answering. You can type it in instead.",
        ]

    def test_a_computer_found_is_written_down_once(self, store, monkeypatch):
        """`discover` attaches the same node to six events, not one.

        Upserting on each of them rewrote the whole file six times per
        computer found. The command line collects and writes after the loop;
        so does this. Counting `save` rather than `upsert` is deliberate —
        `upsert` calls `load` and `save`, and it is the write that costs.
        """
        writes: list[int] = []
        original = NodeStore.save

        def counting(self, nodes, consent):
            writes.append(len(nodes))
            return original(self, nodes, consent)

        monkeypatch.setattr(NodeStore, "save", counting)
        recorder = Recorder()
        list(service.scan(ScanScope.THIS_MACHINE, store=store,
                          fetch=recorder, post=recorder.post))
        assert writes == [1], writes

    def test_each_finding_says_which_computer_it_belongs_to(self, store):
        """§3.4: the desktop fills a card row by row.

        A scan finding two computers yields one interleaved stream of prose,
        and without this the only way to tell which card a row belongs to is
        the order it arrived in. Ordering is not a key: a row that fails
        costs one line rather than the whole scan, so the stream is not
        guaranteed to be the same length per computer.
        """
        recorder = Recorder()
        events = list(service.scan(ScanScope.THIS_MACHINE, store=store,
                                   fetch=recorder, post=recorder.post))
        described = {e.stage: e.node_id for e in events if e.node_id}
        assert set(described) == {"reachable", "backend", "models", "biggest",
                                  "context", "hardware"}
        assert set(described.values()) == {"ollama-127-0-0-1-11434"}
        # A row about no computer in particular says so, rather than
        # inheriting whichever one came last.
        assert [e.node_id for e in events if e.stage in ("trying", "done")] == \
            ["", "", ""]

    def test_progress_reaches_the_view(self, store):
        """The tab draws a bar from these; both halves have to arrive."""
        recorder = Recorder()
        events = list(service.scan(ScanScope.THIS_MACHINE, store=store,
                                   fetch=recorder, post=recorder.post))
        trying = [e for e in events if e.stage == "trying"]
        assert trying and all(e.total == 2 for e in trying)
        assert [e.done for e in trying] == [1, 2]

    def test_the_scan_forwards_the_poster_it_was_given(self, store):
        """The one assertion the Task 4 defect would have failed.

        `probe_ollama` POSTs to `/api/show` once per model listed. A `scan`
        that forwards only `fetch` leaves `post` defaulting to the real
        `http_post_json`, so this recorder would see no POST at all — and the
        `no_sockets` fixture would catch the real one going out.
        """
        recorder = Recorder()
        list(service.scan(ScanScope.THIS_MACHINE, store=store,
                          fetch=recorder, post=recorder.post))
        assert any(u.endswith("/api/show") for u in recorder.asked)

    def test_what_the_poster_answered_is_kept(self, store):
        """The POST is the only source of a model's longest input."""
        recorder = Recorder()
        list(service.scan(ScanScope.THIS_MACHINE, store=store,
                          fetch=recorder, post=recorder.post))
        nodes, _ = store.load()
        assert nodes[0].max_context_length == 8192

    def test_this_machine_reaches_no_further_by_either_verb(self, store):
        recorder = Recorder()
        list(service.scan(ScanScope.THIS_MACHINE, store=store,
                          fetch=recorder, post=recorder.post))
        assert recorder.hosts() <= LOOPBACK, recorder.asked

    def test_a_named_host_is_the_only_host_touched(self, store):
        recorder = Recorder(answering={"10.0.0.9:11434"})
        list(service.scan(ScanScope.NAMED_HOST, "10.0.0.9", store=store,
                          fetch=recorder, post=recorder.post))
        assert {h.split(":")[0] for h in recorder.hosts()} == {"10.0.0.9"}
        nodes, _ = store.load()
        assert nodes and nodes[0].url == "http://10.0.0.9:11434"


class TestTellingARefusalFromAnAnswer:
    """`ok=False and finished` does not identify a refusal, and never did.

    `src/nodes/discovery.py` ends a scan that ran to completion, opened every
    permitted address and found nothing with exactly that shape — which is the
    most common outcome of a first scan, and is not a refusal. A view matching
    on the shape would render "Didn't find anything answering" in a refusal
    treatment and could not tell "we looked and found nothing" apart from "we
    did not look". The stage strings already separate the two.
    """

    def test_a_scan_that_found_nothing_is_not_a_refusal(self, store):
        """The exact event this list exists to keep out of a refusal panel."""
        recorder = Recorder(answering=set())
        events = list(service.scan(ScanScope.THIS_MACHINE, store=store,
                                   fetch=recorder, post=recorder.post))
        last = events[-1]
        assert not last.ok and last.finished, "the shape that used to mean refusal"
        assert last.message.startswith("Didn't find anything answering")
        assert last.stage == "done"
        assert last.stage not in service.REFUSAL_STAGES

    def test_a_scan_that_found_something_ends_on_the_same_stage(self, store):
        """`done` is one stage for both outcomes, so neither may be on the list."""
        recorder = Recorder()
        events = list(service.scan(ScanScope.THIS_MACHINE, store=store,
                                   fetch=recorder, post=recorder.post))
        assert events[-1].stage == "done"
        assert events[-1].stage not in service.REFUSAL_STAGES

    @pytest.mark.parametrize("scope,host", [
        (ScanScope.NONE, ""),
        (ScanScope.LOCAL_NETWORK, ""),
        (ScanScope.NAMED_HOST, "  "),
    ])
    def test_every_stop_before_looking_is_on_the_list(self, store, scope, host):
        recorder = Recorder()
        events = list(service.scan(scope, host, store=store,
                                   fetch=recorder, post=recorder.post))
        assert recorder.asked == []
        assert events[-1].stage in service.REFUSAL_STAGES

    def test_a_file_that_cannot_be_used_is_on_the_list_too(self, tmp_path):
        """Not a refusal on doctrine, but it stops the scan the same way."""
        path = tmp_path / "nodes.yaml"
        path.write_text("nodes: [unclosed\n", encoding="utf-8")
        recorder = Recorder()
        events = list(service.scan(ScanScope.THIS_MACHINE, store=NodeStore(path),
                                   fetch=recorder, post=recorder.post))
        assert events[-1].stage in service.REFUSAL_STAGES

    def test_the_list_is_exported_so_the_view_matches_a_constant(self):
        """Task 8 imports this; a retyped string drifts and nothing notices."""
        from src.gui import services

        assert services.REFUSAL_STAGES is service.REFUSAL_STAGES
        assert services.NOT_BUILT is service.NOT_BUILT


class TestAFileAPersonEdited:
    """A stored file that does not parse is answered, never raised.

    `src/schemas/node.py` says these files are hand-editable by design, so a
    malformed one is an expected outcome rather than an exotic one. The
    package states the rule at `src/gui/services/workflow.py` — "a traceback
    is not an error message" — and the Environment tab is the only route to
    the screen that would let somebody correct the file, so a traceback there
    is a dead end.
    """

    @pytest.fixture()
    def unparseable(self, tmp_path) -> NodeStore:
        """A file that is not YAML at all."""
        path = tmp_path / "nodes.yaml"
        path.write_text("nodes: [unclosed\n", encoding="utf-8")
        return NodeStore(path)

    @pytest.fixture()
    def off_contract(self, tmp_path) -> NodeStore:
        """Valid YAML that is not a computer."""
        path = tmp_path / "nodes.yaml"
        path.write_text("nodes:\n  home-pc:\n    kind: tealeaves\n"
                        "    url: http://x\n", encoding="utf-8")
        return NodeStore(path)

    @pytest.fixture()
    def unopenable(self, tmp_path) -> NodeStore:
        """A path that exists but cannot be read as a file."""
        path = tmp_path / "nodes.yaml"
        path.mkdir()
        return NodeStore(path)

    @pytest.fixture(params=["unparseable", "off_contract", "unopenable"])
    def broken(self, request) -> NodeStore:
        return request.getfixturevalue(request.param)

    def test_listing_reports_it_rather_than_raising(self, broken):
        result = service.list_nodes(broken)
        assert not result.ok
        assert str(broken.path) in result.refusal
        assert result.rows == []

    @pytest.mark.parametrize("name,args", [
        ("save_consent", (ScanScope.THIS_MACHINE, "sam")),
        ("add_node", ("Kitchen Box", "ollama", "http://10.0.0.9:11434")),
        ("forget_node", ("home-pc",)),
        ("update_field", ("home-pc", "label", "Kitchen Box")),
    ])
    def test_every_other_entry_point_reports_it_too(self, broken, name, args):
        result = getattr(service, name)(*args, store=broken)
        assert not result.ok
        assert str(broken.path) in result.refusal

    def test_the_message_names_the_file_and_a_way_out_of_it(self, broken):
        """A dead end with no exit is how a person ends up stuck on a screen."""
        refusal = service.list_nodes(broken).refusal
        assert "Correct that file" in refusal
        assert judgements_in(refusal) == [], refusal
        assert ownership_in(refusal) == [], refusal

    def test_a_scan_ends_on_a_stage_the_view_can_recognise(self, broken):
        recorder = Recorder()
        events = list(service.scan(ScanScope.THIS_MACHINE, store=broken,
                                   fetch=recorder, post=recorder.post))
        assert events[-1].stage == "store"
        assert not events[-1].ok and events[-1].finished
        assert str(broken.path) in events[-1].message


class TestCopyRules:
    """Design §3.1.1 and §3.1.2, over every string this service emits.

    The word lists are `tests/test_node_cli.py`'s — the spec's own, with the
    matcher that tells §3.2's endorsed "only checks this computer" apart from
    a verdict on somebody's hardware.
    """

    def _text_of(self, result) -> str:
        parts = [result.summary, result.refusal]
        parts += [getattr(result, "consequence", "")]
        for label, value in getattr(result, "summary_rows", []):
            parts += [label, value]
        for row in getattr(result, "rows", []):
            parts += [row.label, row.url]
            for f in row.fields:
                parts += [f.label, f.value, f.source]
        return "\n".join(parts)

    def test_listing_neither_judges_nor_assumes_ownership(self, store):
        seed(store)
        for text in (self._text_of(service.list_nodes(store)),
                     self._text_of(service.list_nodes(NodeStore(
                         store.path.parent / "empty.yaml")))):
            assert judgements_in(text) == []
            assert ownership_in(text) == []

    def test_every_refusal_neither_judges_nor_assumes_ownership(self, store):
        seed(store)
        results = [
            service.update_field("nope", "label", "x", store),
            service.update_field("home-pc", "bogus", "x", store),
            service.add_node("", "ollama", "", store),
            service.add_node("X", "tealeaves", "http://x:11434", store),
            service.forget_node("nope", store),
            service.save_consent(ScanScope.LOCAL_NETWORK, "sam", store),
        ]
        for result in results:
            text = self._text_of(result)
            assert judgements_in(text) == [], text
            assert ownership_in(text) == [], text

    @pytest.mark.parametrize("scope,host", [
        (ScanScope.NONE, ""),
        (ScanScope.LOCAL_NETWORK, ""),
        (ScanScope.NAMED_HOST, ""),
        (ScanScope.THIS_MACHINE, ""),
    ])
    def test_no_scan_message_judges_or_assumes_ownership(self, store, scope, host):
        recorder = Recorder()
        text = "\n".join(
            e.message for e in service.scan(scope, host, store=store,
                                            fetch=recorder, post=recorder.post)
        )
        assert judgements_in(text) == [], text
        assert ownership_in(text) == [], text


class TestServicesStayTkFree:
    def test_no_widget_import(self):
        """Read the file through the imported module, not through the cwd.

        `pathlib.Path("src/gui/services/nodes.py")` resolves only when pytest
        happens to be run from the repository root; from anywhere else this
        test either explodes or, worse, reads some other tree's file.
        """
        source = pathlib.Path(service.__file__).read_text(encoding="utf-8")
        assert "customtkinter" not in source
        assert "import tkinter" not in source
