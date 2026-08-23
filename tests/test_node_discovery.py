# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Scanning: what it may touch, and how it reports what it finds.

Permission is this feature's privacy promise, so it is tested rather than
trusted. Every test records which addresses were attempted and asserts the
exact set.

``Recorder`` fakes both HTTP verbs the scanner can use — ``fetch`` (GET) and
``post`` (POST) — into the same ``asked`` list. ``probe_ollama`` POSTs to
``/api/show`` once per model it lists, so a fake that only covered GET would
leave that traffic invisible to every "permission is honoured" assertion in
this file: a bug that made the POST path reach an unpermitted host would pass
silently. Every ``discover(...)`` call below passes both fakes for that
reason, even where a single stage answers deterministically.
"""

import pytest

from src.nodes.discovery import ConsentRefused, DiscoveryEvent, candidate_addresses, discover
from src.schemas.node import NodeKind, ScanScope


class Recorder:
    """A fetcher and poster that record every URL asked for and answer as Ollama."""

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
        """Record and answer a POST the same way ``/api/show`` would.

        Recording into the same ``asked`` list as ``__call__`` means
        ``hosts()`` reflects every address attempted by either verb, so the
        scope assertions police GETs and POSTs alike.
        """
        self.asked.append(url)
        if not any(host in url for host in self.answering):
            raise OSError("connection refused")
        return {"model_info": {"llama.context_length": 8192}, "capabilities": []}

    def hosts(self) -> set[str]:
        """Every distinct host:port attempted, by either verb."""
        return {u.split("//", 1)[1].split("/", 1)[0] for u in self.asked}


class TestPermissionIsHonoured:
    def test_none_opens_nothing_at_all(self):
        fetch = Recorder()
        events = list(discover(ScanScope.NONE, fetch=fetch, post=fetch.post))
        assert fetch.asked == [], "NONE must not open a single connection"
        assert events[-1].finished

    def test_none_yields_a_permission_stage_event(self):
        """Pins the outer ``NONE`` guard in ``discover()`` specifically.

        ``candidate_addresses()`` carries its own, independent ``NONE`` guard
        as defence in depth -- deleting either guard alone still leaves no
        socket opened, so a test that only checks "nothing was fetched"
        cannot tell whether the outer guard exists at all. This asserts the
        outer guard's own behaviour (a ``permission``-stage event) so a
        future refactor that deletes it is caught even though the redundant
        guard would otherwise hide the regression.
        """
        fetch = Recorder()
        events = list(discover(ScanScope.NONE, fetch=fetch, post=fetch.post))
        assert events[0].stage == "permission"

    def test_this_machine_touches_only_loopback(self):
        fetch = Recorder()
        list(discover(ScanScope.THIS_MACHINE, fetch=fetch, post=fetch.post))
        for host in fetch.hosts():
            assert host.startswith("127.0.0.1"), f"left the machine: {host}"

    def test_this_machine_tries_both_known_ports(self):
        fetch = Recorder()
        list(discover(ScanScope.THIS_MACHINE, fetch=fetch, post=fetch.post))
        assert fetch.hosts() == {"127.0.0.1:11434", "127.0.0.1:8081"}

    def test_named_host_touches_only_that_host(self):
        fetch = Recorder(answering={"10.0.0.9:11434"})
        list(discover(ScanScope.NAMED_HOST, "10.0.0.9", fetch=fetch, post=fetch.post))
        for host in fetch.hosts():
            assert host.startswith("10.0.0.9"), f"touched something else: {host}"

    def test_a_named_host_with_a_port_is_honoured_exactly(self):
        fetch = Recorder(answering={"10.0.0.9:9999"})
        list(discover(ScanScope.NAMED_HOST, "10.0.0.9:9999", fetch=fetch, post=fetch.post))
        assert fetch.hosts() == {"10.0.0.9:9999"}

    def test_no_permitted_scope_posts_to_an_unpermitted_host(self):
        """A regression guard for the POST path specifically.

        ``probe_ollama`` POSTs to ``/api/show`` for every model it lists. If
        that call ever reached a host outside what was granted, it would be
        invisible to a fake that only substituted GET -- this fails loudly on
        exactly that traffic instead.
        """
        fetch = Recorder(answering={"10.0.0.9:11434"})
        list(discover(ScanScope.NAMED_HOST, "10.0.0.9", fetch=fetch, post=fetch.post))
        for host in fetch.hosts():
            assert host.startswith("10.0.0.9"), (
                f"a call (GET or POST) reached an unpermitted host: {host}"
            )


class TestCandidates:
    def test_none_has_no_candidates(self):
        assert candidate_addresses(ScanScope.NONE, "") == []

    def test_this_machine_is_loopback_on_both_ports(self):
        assert candidate_addresses(ScanScope.THIS_MACHINE, "") == [
            ("http://127.0.0.1:11434", NodeKind.OLLAMA),
            ("http://127.0.0.1:8081", NodeKind.LLAMACPP),
        ]

    def test_a_bare_named_host_tries_both_ports(self):
        assert candidate_addresses(ScanScope.NAMED_HOST, "box") == [
            ("http://box:11434", NodeKind.OLLAMA),
            ("http://box:8081", NodeKind.LLAMACPP),
        ]

    def test_a_full_url_is_taken_as_given(self):
        assert candidate_addresses(ScanScope.NAMED_HOST, "http://box:1234") == [
            ("http://box:1234", NodeKind.OLLAMA),
            ("http://box:1234", NodeKind.LLAMACPP),
        ]

    def test_local_network_is_refused_legibly(self):
        """LOCAL_NETWORK is declared but not implemented in this task: it must
        raise a legible, named refusal rather than crash or silently scan
        nothing.
        """
        with pytest.raises(ConsentRefused, match="LOCAL_NETWORK"):
            candidate_addresses(ScanScope.LOCAL_NETWORK, "")


class TestTheStream:
    def test_events_arrive_before_the_scan_finishes(self):
        fetch = Recorder()
        stream = discover(ScanScope.THIS_MACHINE, fetch=fetch, post=fetch.post)
        first = next(stream)
        assert isinstance(first, DiscoveryEvent)
        assert not first.finished, "the first event must not be the last"

    def test_each_event_carries_a_human_message(self):
        fetch = Recorder()
        for event in discover(ScanScope.THIS_MACHINE, fetch=fetch, post=fetch.post):
            assert event.message, f"stage {event.stage} produced no message"
            assert "provenance" not in event.message.lower()
            assert "endpoint" not in event.message.lower()

    def test_a_found_computer_is_carried_on_the_event(self):
        fetch = Recorder()
        events = list(discover(ScanScope.THIS_MACHINE, fetch=fetch, post=fetch.post))
        found = [e for e in events if e.node is not None]
        assert found, "nothing was reported despite a server answering"
        assert found[-1].node.reachable
        assert found[-1].node.models

    def test_the_last_event_is_marked_finished(self):
        fetch = Recorder()
        events = list(discover(ScanScope.THIS_MACHINE, fetch=fetch, post=fetch.post))
        assert events[-1].finished
        assert sum(1 for e in events if e.finished) == 1

    def test_a_stage_failure_keeps_what_was_already_found(self):
        class HalfBroken(Recorder):
            def __call__(self, url, timeout=0.0):
                if url.endswith("/api/tags"):
                    self.asked.append(url)
                    raise OSError("boom")
                return super().__call__(url, timeout)

        fetch = HalfBroken()
        events = list(discover(ScanScope.THIS_MACHINE, fetch=fetch, post=fetch.post))
        nodes = [e.node for e in events if e.node is not None]
        assert nodes, "a listing failure discarded the whole scan"
        assert nodes[-1].reachable, "the server answered and must still be recorded"

    def test_nothing_found_still_finishes_cleanly(self):
        fetch = Recorder(answering=set())
        events = list(discover(ScanScope.THIS_MACHINE, fetch=fetch, post=fetch.post))
        assert events[-1].finished
        assert all(e.node is None for e in events)
        assert "didn't find" in events[-1].message.lower()
