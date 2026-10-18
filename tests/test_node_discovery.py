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

from src.nodes.discovery import (
    MALFORMED_ADDRESS,
    USERINFO_REFUSED,
    ConsentRefused,
    DiscoveryEvent,
    address_for,
    address_problem,
    candidate_addresses,
    discover,
    has_userinfo,
    redact_userinfo,
    scrub_userinfo,
)
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


class TestTypedAddresses:
    """Where a typed-in computer is recorded, before anything contacts it."""

    def test_a_bare_host_gets_the_port_of_the_program_named(self):
        assert address_for("box", NodeKind.OLLAMA) == "http://box:11434"
        assert address_for("box", NodeKind.LLAMACPP) == "http://box:8081"

    def test_a_port_that_was_typed_is_kept(self):
        assert address_for("box:9000", NodeKind.OLLAMA) == "http://box:9000"

    def test_a_full_url_is_kept_as_typed(self):
        assert address_for(" https://box:9000/ ", NodeKind.LLAMACPP) == (
            "https://box:9000"
        )

    #: Ways a person really types an address. The trailing-slash and
    #: capitalised forms are what a browser's address bar hands over; the
    #: bracketed one is how an IPv6 address is written in a URL. The last
    #: two carry a path and a query with no port named -- a port appended
    #: after the whole string, rather than into the host, landed on the
    #: path instead (m2): ``http://box/v1`` became ``http://box/v1:11434``,
    #: which both names no real port and changes again on a second read.
    #: Re-review nits (r4's report, #2): a fragment, userinfo, an empty
    #: port, and a bare (unbracketed) IPv6 host, each with no port named.
    TYPED = ["box", "box:9000", "http://box:9000/", "box/", "box:9000/",
             "HTTP://box:9000", "Http://box/", "[::1]", "[::1]:9000",
             "box/v1", "box?x=1", "box#frag", "user:pw@box",
             "user:pw@box:9000", "box:", "[::1]:", "::1", "[::1]/v1"]

    def test_a_trailing_slash_does_not_become_part_of_the_host(self):
        """``10.0.0.9/`` once became ``http://10.0.0.9/:11434`` -- a path, not
        a port -- which was stored, and which a look sent to port 80."""
        assert address_for("10.0.0.9/", NodeKind.OLLAMA) == "http://10.0.0.9:11434"
        assert [url for url, _ in candidate_addresses(ScanScope.NAMED_HOST, "box/")] == [
            "http://box:11434", "http://box:8081",
        ]

    def test_the_scheme_is_recognised_however_it_is_capitalised(self):
        assert address_for("HTTP://box", NodeKind.OLLAMA) == "http://box:11434"

    def test_an_ipv6_address_is_not_mistaken_for_one_naming_a_port(self):
        assert address_for("[::1]", NodeKind.OLLAMA) == "http://[::1]:11434"
        assert address_for("[::1]:9000", NodeKind.OLLAMA) == "http://[::1]:9000"

    def test_a_port_is_inserted_into_the_host_not_appended_after_a_path(self):
        """m2: ``http://box/v1`` named no port, so one was appended after the
        whole string -- ``http://box/v1:11434`` -- which is a port on the
        path, reaches nothing on 11434, and still goes to port 80."""
        assert address_for("box/v1", NodeKind.OLLAMA) == "http://box:11434/v1"

    def test_a_port_is_inserted_before_a_query_not_appended_after_it(self):
        assert address_for("box?x=1", NodeKind.OLLAMA) == "http://box:11434?x=1"

    def test_a_port_is_inserted_before_a_fragment_not_appended_after_it(self):
        """Re-review nit: ``#`` was not a boundary mark, so a fragment with
        no ``/`` or ``?`` anywhere (``http://box#frag``) read as part of
        the host, the same class of bug ``?`` alone was."""
        assert address_for("box#frag", NodeKind.OLLAMA) == "http://box:11434#frag"

    def test_userinfo_s_colon_is_not_mistaken_for_a_port(self):
        """Re-review nit: ``user:pw@box`` was read as naming a port -- the
        one in ``user:pw`` -- so no real port was appended and a look went
        to port 80. Userinfo is split off before the host is read, and put
        back afterwards rather than dropped or refused."""
        assert address_for("user:pw@box", NodeKind.OLLAMA) == (
            "http://user:pw@box:11434"
        )
        assert address_for("user:pw@box:9000", NodeKind.OLLAMA) == (
            "http://user:pw@box:9000"
        )

    def test_an_empty_port_gets_the_default_not_a_dangling_colon(self):
        """Re-review nit: ``box:`` and ``[::1]:`` were read as already
        naming a port -- an empty one -- and kept the dangling colon with
        nothing after it instead of filling in the default."""
        assert address_for("box:", NodeKind.OLLAMA) == "http://box:11434"
        assert address_for("[::1]:", NodeKind.OLLAMA) == "http://[::1]:11434"

    def test_a_bare_ipv6_host_is_bracketed_before_a_port_is_added(self):
        """Re-review nit: an unbracketed ``::1`` is full of colons with no
        brackets, so it named no port by this function's own rule, but
        appending one unbracketed (``::1:11434``) is not a usable address."""
        assert address_for("::1", NodeKind.OLLAMA) == "http://[::1]:11434"

    @pytest.mark.parametrize("typed", TYPED)
    @pytest.mark.parametrize("kind", list(NodeKind))
    def test_an_address_reads_the_same_the_second_time(self, typed, kind):
        """Read twice, an address must not change.

        The store matches records by address, and an address is read once
        when it is saved and again when a look is aimed at it. A reading
        that moved on the second pass -- as a trailing slash once did --
        files the finding under a second record and leaves the first
        reading "not answering".
        """
        once = address_for(typed, kind)
        assert address_for(once, kind) == once

    @pytest.mark.parametrize("typed", TYPED)
    @pytest.mark.parametrize("kind", list(NodeKind))
    def test_a_later_look_at_that_address_reaches_the_same_record(self, typed, kind):
        """The store matches a finding to a record by address, exactly.

        So the address saved for a typed-in computer has to be one that a look
        at it tries, character for character. If the two ever read a typed
        host differently, checking the computer later would save a second row
        beside the first instead of filling it in.
        """
        saved = address_for(typed, kind)
        tried = [url for url, _kind in candidate_addresses(ScanScope.NAMED_HOST, saved)]
        assert saved in tried

    def test_an_at_sign_in_a_path_is_not_mistaken_for_userinfo(self):
        """Final re-review regression: finding the authority's end before
        looking for ``@`` must not stop at the first one in the whole
        string -- it has to look only inside the authority. A path or
        query character that happens to be ``@`` (``http://box/p@x``) was
        split off as if it were a user name, which also meant no real
        port was ever appended (m2's bug, one character later)."""
        assert address_for("box/p@x", NodeKind.OLLAMA) == "http://box:11434/p@x"
        assert address_for("box?a=@b", NodeKind.OLLAMA) == "http://box:11434?a=@b"


class TestUserinfoAndMalformedAddresses:
    """Final re-review (1): a typed user name and password are refused, not
    kept -- `urllib` never turns "user:pw@host" into Basic auth (no
    ``Authorization`` header is sent), so keeping it bought no function and
    cost a plaintext secret saved to `nodes.yaml`, printed by every listing,
    and copied into a failed run's ledger note.
    """

    def test_userinfo_is_refused_without_echoing_it(self):
        problem = address_problem("alice:s3cret@10.0.0.9")
        assert problem == USERINFO_REFUSED
        assert "alice" not in problem
        assert "s3cret" not in problem

    def test_a_plain_address_has_no_problem(self):
        assert address_problem("10.0.0.9") is None
        assert address_problem("box:9000") is None
        assert address_problem("box:") is None
        assert address_problem("[::1]") is None
        assert address_problem("[::1]:9000") is None
        assert address_problem("::1") is None
        assert address_problem("2001:db8::1") is None

    @pytest.mark.parametrize("bad", [
        "box:abc",          # a port that is not a number
        "10.0.0.9:11434:1",  # more than one port
        "[::1]x",            # something after "]" that is not ":<port>"
        "[::1",               # an unclosed bracket
    ])
    def test_a_malformed_address_is_refused_not_guessed(self, bad):
        assert address_problem(bad) == MALFORMED_ADDRESS

    def test_has_userinfo_reads_a_stored_address_the_same_way(self):
        assert has_userinfo("http://alice:s3cret@10.0.0.9:11434") is True
        assert has_userinfo("http://10.0.0.9:11434") is False

    def test_redaction_hides_the_secret_but_keeps_the_host(self):
        redacted = redact_userinfo("http://alice:s3cret@10.0.0.9:11434")
        assert "alice" not in redacted
        assert "s3cret" not in redacted
        assert "10.0.0.9:11434" in redacted

    def test_redaction_keeps_a_path_after_the_host(self):
        redacted = redact_userinfo("http://alice:s3cret@10.0.0.9:11434/v1")
        assert "alice" not in redacted
        assert redacted.endswith("/v1")

    def test_redaction_leaves_a_clean_address_unchanged(self):
        assert redact_userinfo("http://10.0.0.9:11434") == "http://10.0.0.9:11434"

    def test_redaction_is_idempotent(self):
        once = redact_userinfo("http://alice:s3cret@10.0.0.9:11434")
        assert redact_userinfo(once) == once

    @pytest.mark.parametrize("text", [
        "it has the single value 'http://alice:s3cret@10.0.0.9'",
        "input_value='http://alice:s3cret@10.0.0.9'",
        "input_value=['http://alice:s3cret@10.0.0.9']",
        'while scanning ... tp://alice:s3cret@10.0.0.9:11434: x',
        "nodes: http://alice:s3cret@10.0.0.9",
        "consent: http://alice:s3cret@10.0.0.9",
    ])
    def test_scrub_userinfo_removes_it_from_arbitrary_text(self, text):
        """Final re-review's residual leak: a *malformed* file's own
        content, or a pydantic/YAML exception's message, can still quote a
        secret back -- this is swept over free text rather than one known
        address field, because by the time a message like this is built
        there is no single field left to read it from."""
        scrubbed = scrub_userinfo(text)
        assert "alice" not in scrubbed
        assert "s3cret" not in scrubbed

    def test_scrub_userinfo_leaves_ordinary_text_alone(self):
        assert scrub_userinfo("10.0.0.9:11434 should start with `nodes:`") == (
            "10.0.0.9:11434 should start with `nodes:`"
        )


class TestTheStream:
    def test_events_arrive_before_the_scan_finishes(self):
        fetch = Recorder()
        stream = discover(ScanScope.THIS_MACHINE, fetch=fetch, post=fetch.post)
        first = next(stream)
        assert isinstance(first, DiscoveryEvent)
        assert not first.finished, "the first event must not be the last"

    def test_the_program_is_named_as_a_person_reads_it(self):
        """§3.4: "It's Ollama 0.5.4" -- the program's name, not the enum's."""
        fetch = Recorder()
        lines = [e.message for e in discover(ScanScope.THIS_MACHINE, fetch=fetch,
                                             post=fetch.post) if e.stage == "backend"]
        assert lines == ["It's Ollama 0.5.4"]

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

    def test_two_different_hosts_on_the_same_port_get_different_ids(self):
        # The id is derived from host:port, not port alone, so two machines
        # both answering on the default Ollama port do not collide by
        # construction (NodeStore.upsert handles any collision that still
        # reaches it, e.g. a hand-typed id).
        fetch_a = Recorder(answering={"10.0.0.9:11434"})
        events_a = list(
            discover(ScanScope.NAMED_HOST, "10.0.0.9", fetch=fetch_a, post=fetch_a.post)
        )
        fetch_b = Recorder(answering={"10.0.0.5:11434"})
        events_b = list(
            discover(ScanScope.NAMED_HOST, "10.0.0.5", fetch=fetch_b, post=fetch_b.post)
        )
        node_a = next(e.node for e in events_a if e.node is not None)
        node_b = next(e.node for e in events_b if e.node is not None)
        assert node_a.node_id != node_b.node_id
        assert node_a.node_id == "ollama-10-0-0-9-11434"
        assert node_b.node_id == "ollama-10-0-0-5-11434"


class TestUserinfoWhateverTheScheme:
    """Review of PR #33: only `http` and `https` were recognised as schemes,
    so `ftp://alice:s3cret@host` read as a host called "ftp" -- the
    userinfo was never seen, the address was accepted, saved, and then
    shown in clear by every listing. Userinfo is found before any scheme
    decision, and a scheme this program cannot use is refused outright.
    """

    TAINTED = [
        "ftp://alice:s3cret@10.0.0.9",
        "ssh://alice:s3cret@10.0.0.9:22",
        "git+ssh://alice:s3cret@10.0.0.9",
        "svn+https://alice:s3cret@10.0.0.9/repo",
        "//alice:s3cret@10.0.0.9",
        "http:/alice:s3cret@10.0.0.9",
        "HTTPS://alice:s3cret@10.0.0.9",
        "mailto:alice:s3cret@10.0.0.9",
    ]

    @pytest.mark.parametrize("url", TAINTED)
    def test_userinfo_is_seen_in_any_scheme(self, url):
        assert has_userinfo(url) is True

    @pytest.mark.parametrize("url", TAINTED)
    def test_redaction_hides_it_in_any_scheme(self, url):
        redacted = redact_userinfo(url)
        assert "alice" not in redacted
        assert "s3cret" not in redacted
        assert "10.0.0.9" in redacted

    @pytest.mark.parametrize("url", TAINTED)
    def test_a_typed_one_is_refused_without_echoing_it(self, url):
        problem = address_problem(url)
        assert problem is not None
        assert "alice" not in problem
        assert "s3cret" not in problem

    @pytest.mark.parametrize("url", [
        "ftp://10.0.0.9", "ssh://10.0.0.9:22", "file:///etc/hosts",
        "//10.0.0.9", "http:/10.0.0.9",
    ])
    def test_a_scheme_this_program_cannot_use_is_refused(self, url):
        assert address_problem(url) == MALFORMED_ADDRESS

    @pytest.mark.parametrize("url", [
        "http://10.0.0.9", "https://10.0.0.9:443", "HTTP://box:9000",
        "10.0.0.9", "box",
    ])
    def test_http_https_and_bare_hosts_are_still_fine(self, url):
        assert address_problem(url) is None
        assert has_userinfo(url) is False

    def test_an_at_sign_anywhere_counts(self):
        """Fourth review: parsing where the authority ends was wrong four
        different ways in four rounds. A base address never needs an
        ``@``, so any one -- path and query included -- now counts."""
        assert has_userinfo("ftp://10.0.0.9/p@x") is True
        assert has_userinfo("http://box?a=@b") is True


class TestUserinfoWhateverPrecedesTheAuthority:
    """Second review of 97fd856: the authority was taken off only after a
    *valid* scheme, so anything else before ``://`` -- a pasted BOM or
    zero-width space, ``1ftp``, a space, a control character, a backslash
    -- left the userinfo unseen in a *stored* record, which was then shown
    and resolved. A fullwidth ``＠`` did the same; urllib itself reads it
    as ``@`` once normalised."""

    STORED = [
        "\ufeffhttp://alice:s3cret@10.0.0.9:11434",
        "\u200bhttp://alice:s3cret@10.0.0.9:11434",
        "1ftp://alice:s3cret@10.0.0.9",
        "_x://alice:s3cret@10.0.0.9",
        "-://alice:s3cret@10.0.0.9",
        "://alice:s3cret@10.0.0.9",
        "http ://alice:s3cret@10.0.0.9",
        "ht tp://alice:s3cret@10.0.0.9",
        "\x00ftp://alice:s3cret@10.0.0.9",
        "\x01http://alice:s3cret@10.0.0.9",
        "http:\\/alice:s3cret@10.0.0.9",
        "http:\\\\alice:s3cret@10.0.0.9",
        "http://alice:s3cret\uff2010.0.0.9:11434",
    ]

    @pytest.mark.parametrize("url", STORED)
    def test_it_is_seen(self, url):
        assert has_userinfo(url) is True

    @pytest.mark.parametrize("url", STORED)
    def test_it_is_redacted(self, url):
        redacted = redact_userinfo(url)
        assert "s3cret" not in redacted
        assert "alice" not in redacted

    @pytest.mark.parametrize("url", STORED)
    def test_it_is_refused_when_typed(self, url):
        problem = address_problem(url)
        assert problem is not None
        assert "s3cret" not in problem

    @pytest.mark.parametrize("url", [
        "http://10.0.0.9:11434", "box", "[::1]:9000", "localhost:11434",
        "https://box:443/v1", "::1", "box.lan:11434",
    ])
    def test_ordinary_addresses_are_unaffected(self, url):
        assert has_userinfo(url) is False


class TestALaterSchemeMarkerHidesNothing:
    """Third review: reading the authority after the *first* ``://`` let a
    ``://`` later in a path, query or fragment swallow the real userinfo
    in front of it. Every reasonable reading is now checked, and any one
    of them finding userinfo is enough."""

    LATER = [
        "alice:s3cret@10.0.0.9:11434/v1://",
        "alice:s3cret@10.0.0.9/x://y",
        "alice:s3cret@10.0.0.9?q=a://b",
        "alice:s3cret@10.0.0.9#://",
        "http:alice:s3cret@10.0.0.9/a://b",
        "//alice:s3cret@10.0.0.9/://",
        "http:/alice:s3cret@10.0.0.9/a://b",
        "http://alice:s3cret@10.0.0.9/x://bob:other@y",
    ]

    @pytest.mark.parametrize("url", LATER)
    def test_it_is_seen(self, url):
        assert has_userinfo(url) is True

    @pytest.mark.parametrize("url", LATER)
    def test_every_secret_is_redacted(self, url):
        redacted = redact_userinfo(url)
        assert "s3cret" not in redacted
        assert "other" not in redacted
        assert "alice" not in redacted

    @pytest.mark.parametrize("url", LATER)
    def test_it_is_refused_when_typed(self, url):
        assert address_problem(url) is not None


class TestAnyAtSignIsUserinfo:
    """Fourth review of the #33 fix: folding backslashes into slashes let
    ``http://al\\ice:pw@host`` through, typed and stored, and the readings
    used quadratic memory on many ``://``. Any ``@`` now counts."""

    @pytest.mark.parametrize("url", [
        "http://al\\ice:s3cret@10.0.0.9",
        "https://x\\y:s3cret@10.0.0.9/v1",
        "al\\ice:s3cret@10.0.0.9",
        "http://alice:SE\\CRET@10.0.0.9",
        "http://alice:SE://CRET@10.0.0.9",
        "http://alice:s3/cret@10.0.0.9",
        "http://alice:s3#cret@10.0.0.9",
    ])
    def test_it_is_seen_refused_and_fully_redacted(self, url):
        assert has_userinfo(url) is True
        assert address_problem(url) == USERINFO_REFUSED
        shown = redact_userinfo(url)
        for part in ("alice", "al", "s3", "SE", "CRET", "cret"):
            assert part not in shown.replace("10.0.0.9", ""), (part, shown)
        assert shown.endswith("10.0.0.9") or shown.endswith("10.0.0.9/v1")

    def test_huge_inputs_stay_linear(self):
        import time

        for text in ("http://box/" + "://" * 100_000, "a:pw@b://" * 30_000):
            started = time.perf_counter()
            has_userinfo(text)
            redact_userinfo(text)
            address_problem(text)
            assert time.perf_counter() - started < 1.0


def test_only_a_real_scheme_is_kept_in_front_of_a_redaction():
    """Review of 6511fc1: text before "://" was shown as if it were a
    scheme, so ``alice:s3cret://x@host`` displayed its secret."""
    shown = redact_userinfo("alice:s3cret://x@10.0.0.9")
    assert "s3cret" not in shown and "alice" not in shown
    assert redact_userinfo("http://alice:s3cret@10.0.0.9") == "http://…@10.0.0.9"
