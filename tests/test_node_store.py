# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Where what a person told us is kept, and how it reaches the runtime."""

import pytest
import yaml

from src.nodes.registry import legacy_endpoints, merged_endpoints
from src.nodes.store import AmbiguousAddressError, NodeStore, duplicate_groups, unusable_message
from src.schemas.node import (
    HostCapability,
    InferenceNode,
    ModelCapability,
    NodeKind,
    Provenance,
    ScanConsent,
    ScanScope,
)


def node(**kw) -> InferenceNode:
    base = dict(node_id="home-pc", label="Home PC", kind=NodeKind.OLLAMA,
                url="http://localhost:11434", reachable=True)
    base.update(kw)
    return InferenceNode(**base)


@pytest.fixture()
def store(tmp_path) -> NodeStore:
    return NodeStore(tmp_path / "nodes.yaml")


class TestEmptyStore:
    def test_a_missing_file_is_no_computers_and_no_permission(self, store):
        nodes, consent = store.load()
        assert nodes == []
        assert consent.scope is ScanScope.NONE

    def test_saving_creates_the_file(self, store):
        store.save([node()], ScanConsent())
        assert store.path.exists()


class TestRoundTrip:
    def test_a_computer_survives_save_and_load(self, store):
        original = node(models=[ModelCapability(name="m", context_length=8192)],
                        host=HostCapability(gpu_present=True, vram_bytes=6_000_000_000),
                        provenance={"models": Provenance.DETECTED})
        store.save([original], ScanConsent.granted(ScanScope.THIS_MACHINE, "sam"))
        loaded, consent = store.load()
        assert loaded == [original]
        assert consent.scope is ScanScope.THIS_MACHINE
        assert consent.granted_by == "sam"

    def test_the_file_is_readable_yaml(self, store):
        store.save([node()], ScanConsent())
        raw = yaml.safe_load(store.path.read_text(encoding="utf-8"))
        assert raw["nodes"]["home-pc"]["label"] == "Home PC"

    def test_an_unknown_field_is_refused_by_name(self, store):
        store.path.write_text(
            "schema_version: '1'\nnodes:\n  a:\n    label: x\n    kind: ollama\n"
            "    url: http://h\n    bogus: 1\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError) as exc:
            store.load()
        assert "bogus" in str(exc.value)


#: YAML that parses, but not into the shape of this file. Each one got past
#: every handler as an AttributeError or TypeError, because only a contract
#: failure was turned into the ValueError they catch (review finding 2).
#: Shared with the service and CLI tests.
WRONG_SHAPES = {
    "a list": "- one\n- two\n",
    "a bare word": "hello\n",
    "computers as a list": "nodes:\n  - label: x\n",
    "a computer with nothing under it": "nodes:\n  home-pc:\n",
    "the permission as a word": "consent: yes\n",
    # Review finding I3: a misspelled top-level key reads as *no* computers
    # rather than a refusal -- `raw.get("nodes")` is simply absent -- and the
    # next write, which only ever writes what `load()` handed back, erased
    # the ones a person wrote by hand under the misspelled key.
    "a misspelled top-level key": (
        "node:\n  garage:\n    label: Garage\n    kind: ollama\n"
        "    url: http://10.0.0.9:11434\n"
    ),
}


class TestAFileOfTheWrongShape:
    @pytest.mark.parametrize("text", WRONG_SHAPES.values(), ids=WRONG_SHAPES.keys())
    def test_it_is_refused_by_name(self, store, text):
        store.path.write_text(text, encoding="utf-8")
        with pytest.raises(ValueError) as exc:
            store.load()
        assert str(store.path) in str(exc.value)

    def test_a_quoted_scalar_naming_a_password_is_never_quoted_at_all(
        self, store
    ):
        """Last check's structural fix: `_what()` used to quote a
        hand-edited file's own scalar back verbatim, which could be a
        tainted url even though nothing here ever read it as an address --
        and a regex scrubber applied to that quote kept missing shapes it
        could not anchor on (a YAML fold, an unencoded ``/``, a ``'`` that
        flips `repr()` to double quotes, re-review rounds 2-4). `_what()`
        now never quotes the value at all, only its shape, so there is
        nothing left for any of those shapes to slip through."""
        store.path.write_text(
            "nodes:\n  box: http://alice:s3cret@10.0.0.9\n", encoding="utf-8"
        )
        with pytest.raises(ValueError) as exc:
            store.load()
        message = str(exc.value)
        assert "s3cret" not in message
        assert "alice" not in message
        assert "10.0.0.9" not in message
        assert "a single value" in message
        assert str(store.path) in message

    def test_an_unknown_top_level_key_names_it(self, store):
        """I3: a typo (`node:` for `nodes:`) must not read as "no computers".

        Without this, `raw.get("nodes")` is simply absent, the typo'd key is
        never looked at, and the next write erases whatever is written
        under it -- `save()` only ever writes what `load()` handed back.
        """
        store.path.write_text(
            "node:\n  garage:\n    label: Garage\n    kind: ollama\n"
            "    url: http://10.0.0.9:11434\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError) as exc:
            store.load()
        assert "node" in str(exc.value)

    def test_a_non_utf8_file_names_itself(self, store):
        """m5: without this, `str(UnicodeDecodeError)` reaches the person
        with no path in it at all -- every other refusal names the file."""
        store.path.write_bytes(b"nodes:\n  a:\n    label: \xff\n")
        with pytest.raises(ValueError) as exc:
            store.load()
        assert str(store.path) in str(exc.value)


class TestUpsert:
    def test_a_new_computer_is_added(self, store):
        store.upsert(node())
        assert [n.node_id for n in store.load()[0]] == ["home-pc"]

    def test_rediscovering_the_same_address_updates_in_place(self, store):
        store.upsert(node())
        store.upsert(node(node_id="other", label="Other",
                          backend_version="0.5.5"))
        nodes, _ = store.load()
        assert len(nodes) == 1, "the same URL must not become two computers"
        assert nodes[0].backend_version == "0.5.5"

    def test_a_rescan_preserves_what_a_person_typed(self, store):
        # This is what makes "Check again" safe to press.
        store.upsert(node(label="Kitchen Box",
                          provenance={"label": Provenance.DECLARED}))
        store.upsert(node(label="ollama on this computer", backend_version="0.6"))
        nodes, _ = store.load()
        assert nodes[0].label == "Kitchen Box", "a rescan overwrote a typed value"
        assert nodes[0].backend_version == "0.6", "a detected value was not refreshed"
        assert nodes[0].source_of("label") is Provenance.DECLARED, (
            "the value survived but its provenance reverted -- the next "
            "rescan would silently overwrite it"
        )

    def test_a_rescan_leaves_the_name_alone_however_it_was_saved(self, store):
        """§6.0: a rescan leaves ``node_id`` and ``label`` alone.

        Not only a name marked as typed. `node scan --label` saved its name
        with no source at all until review finding 4, and the next rescan
        renamed it back to "Ollama on this computer".
        """
        store.upsert(node(label="Home PC"))
        store.upsert(node(label="Ollama on this computer", backend_version="0.6"))
        nodes, _ = store.load()
        assert nodes[0].label == "Home PC"
        assert nodes[0].backend_version == "0.6"

    def test_a_dotted_declared_key_survives_a_rescan_without_raising(self, store):
        # "host.vram_bytes" is a documented provenance form (a person can, in
        # principle, declare a nested value) even though nothing in the
        # current UI produces one. The merge must not assume every DECLARED
        # key names a top-level attribute.
        store.upsert(node(provenance={"host.vram_bytes": Provenance.DECLARED}))
        store.upsert(node(backend_version="0.6"))
        nodes, _ = store.load()
        assert nodes[0].source_of("host.vram_bytes") is Provenance.DECLARED
        assert nodes[0].backend_version == "0.6"

    def test_a_rescan_with_label_does_not_claim_a_machine_made_name(self, store):
        """I1 (introduced by fix 4): the merge always keeps `existing.label`
        -- `node scan --label` over a record nobody has named yet must not
        mark *that* text as person-given. `--label`'s own DECLARED source
        was being written onto the kept, machine-made text regardless."""
        store.upsert(node(label="Ollama on this computer"))  # no provenance
        merged = store.upsert(node(label="Garage",
                                   provenance={"label": Provenance.DECLARED}))
        assert merged.label == "Ollama on this computer"
        assert merged.source_of("label") is not Provenance.DECLARED

    def test_a_rescan_with_label_leaves_a_person_given_name_declared(self, store):
        """The other half: a name already marked as given keeps that mark."""
        store.upsert(node(label="Kitchen Box",
                          provenance={"label": Provenance.DECLARED}))
        merged = store.upsert(node(label="Garage",
                                   provenance={"label": Provenance.DECLARED}))
        assert merged.label == "Kitchen Box"
        assert merged.source_of("label") is Provenance.DECLARED

    def test_forget_removes_one(self, store):
        store.upsert(node())
        assert store.forget("home-pc") is True
        assert store.load()[0] == []

    def test_forgetting_an_unknown_id_reports_it(self, store):
        assert store.forget("nope") is False


class TestAddressesSpelledDifferently:
    """One computer, however its address was written down.

    A record saved by an older build, by ``node add`` before it read
    addresses, or by hand in ``nodes.yaml`` can hold ``10.0.0.9:11434`` or
    ``http://10.0.0.9`` where a look produces ``http://10.0.0.9:11434``.
    Matched character for character, a look at it filed what it found as a
    second computer.
    """

    def test_a_finding_fills_in_a_record_saved_without_a_scheme(self, store):
        store.save([node(node_id="kitchen-box", label="Kitchen Box",
                         url="10.0.0.9:11434", reachable=False,
                         provenance={"label": Provenance.DECLARED,
                                     "url": Provenance.DECLARED})],
                   ScanConsent())
        merged = store.upsert(node(node_id="ollama-10-0-0-9-11434",
                                   label="Ollama on 10.0.0.9",
                                   url="http://10.0.0.9:11434"))
        nodes, _ = store.load()
        assert [(n.node_id, n.label) for n in nodes] == [("kitchen-box", "Kitchen Box")]
        assert merged.node_id == "kitchen-box"
        assert nodes[0].reachable is True

    def test_a_record_saved_without_a_port_matches_its_programs_port(self, store):
        store.save([node(node_id="kitchen-box", label="Kitchen Box",
                         url="http://10.0.0.9", reachable=False)], ScanConsent())
        store.upsert(node(node_id="ollama-10-0-0-9-11434", url="http://10.0.0.9:11434"))
        assert [n.node_id for n in store.load()[0]] == ["kitchen-box"]

    def test_a_different_program_on_another_port_is_another_computer(self, store):
        store.save([node(node_id="kitchen-box", url="http://10.0.0.9")], ScanConsent())
        store.upsert(node(node_id="llamacpp-10-0-0-9-8081", kind=NodeKind.LLAMACPP,
                          url="http://10.0.0.9:8081"))
        assert len(store.load()[0]) == 2


class TestAStoreAlreadyHoldingTwoAtOneAddress:
    """I2: the pair ``upsert`` exists to prevent, left behind by a pre-fix
    build (``node add`` then one scan) or a hand edit. ``load()`` accepts
    it -- refusing to load would also break ``node forget`` and ``node
    list`` on the one store that most needs them -- but a further write
    that would have to guess which of the two a finding belongs to is
    refused instead of guessing wrong.
    """

    @staticmethod
    def _seeded(store):
        """What finding 1 (pre-fix) left behind for ``http://10.0.0.9``."""
        store.save([
            node(node_id="kitchen-box", label="Kitchen Box",
                 url="http://10.0.0.9", reachable=False,
                 provenance={"label": Provenance.DECLARED,
                             "url": Provenance.DECLARED}),
            node(node_id="ollama-10-0-0-9-11434", label="Ollama on 10.0.0.9",
                 url="http://10.0.0.9:11434", reachable=True),
        ], ScanConsent())

    def test_loading_such_a_store_still_works(self, store):
        self._seeded(store)
        nodes, _ = store.load()
        assert {n.node_id for n in nodes} == {"kitchen-box", "ollama-10-0-0-9-11434"}

    def test_a_write_that_would_have_to_guess_is_refused_naming_both_ids(
        self, store
    ):
        self._seeded(store)
        with pytest.raises(ValueError) as exc:
            store.upsert(node(node_id="ollama-10-0-0-9-11434",
                              url="http://10.0.0.9:11434", backend_version="0.6"))
        message = str(exc.value)
        assert "kitchen-box" in message
        assert "ollama-10-0-0-9-11434" in message
        assert "forget" in message
        # Refused, not guessed: neither record was touched.
        nodes = {n.node_id: n for n in store.load()[0]}
        assert nodes["ollama-10-0-0-9-11434"].reachable is True
        assert nodes["kitchen-box"].reachable is False

    def test_forgetting_either_one_still_works(self, store):
        self._seeded(store)
        assert store.forget("kitchen-box") is True
        assert [n.node_id for n in store.load()[0]] == ["ollama-10-0-0-9-11434"]

    def test_unusable_message_gives_one_remedy_not_two(self, store):
        """Re-review nit: `unusable_message`'s generic "Correct that
        file..." tail is right after a shape error, but appended after
        this one it read as a second, different instruction -- the
        sentence above it already said what to do."""
        self._seeded(store)
        with pytest.raises(AmbiguousAddressError) as exc:
            store.upsert(node(node_id="ollama-10-0-0-9-11434",
                              url="http://10.0.0.9:11434"))
        message = unusable_message(store.path, exc.value)
        assert "forget" in message
        assert "Correct that file" not in message

    def test_the_pair_is_reported_as_a_duplicate_group(self, store):
        self._seeded(store)
        nodes, _ = store.load()
        assert duplicate_groups(nodes) == [
            ["kitchen-box", "ollama-10-0-0-9-11434"]
        ]

    def test_an_unrelated_write_is_not_affected(self, store):
        """The ambiguity is per-address. A different computer is unaffected."""
        self._seeded(store)
        store.upsert(node(node_id="garage-pc", label="Garage PC",
                          url="http://10.0.0.1:11434"))
        assert {n.node_id for n in store.load()[0]} == {
            "kitchen-box", "ollama-10-0-0-9-11434", "garage-pc",
        }


class TestMarkSilent:
    """A look that found nothing, recorded on the computer that was looked at.

    Named by id, not by address: the address is exactly what may be spelled
    differently in the record and in the look (see above), and the caller
    always knows which record it looked at.
    """

    def test_the_computer_reads_as_looked_at_and_not_answering(self, store):
        store.save([node()], ScanConsent.granted(ScanScope.THIS_MACHINE, "sam"))
        assert store.mark_silent("home-pc") is True
        stored = store.load()[0][0]
        assert stored.reachable is False
        assert stored.last_probed_at is not None

    def test_what_was_typed_and_found_is_kept(self, store):
        """Only the two facts a silent look established change."""
        store.save([node(
            label="Home PC",
            models=[ModelCapability(name="llama3.1:8b", context_length=8192)],
            provenance={"label": Provenance.DECLARED},
        )], ScanConsent.granted(ScanScope.THIS_MACHINE, "sam"))
        store.mark_silent("home-pc")
        stored, consent = store.load()
        # Without this line every assertion below also holds when the stamp
        # never lands, since then nothing changes at all.
        assert stored[0].last_probed_at is not None
        assert stored[0].label == "Home PC"
        assert stored[0].source_of("label") is Provenance.DECLARED
        assert [m.name for m in stored[0].models] == ["llama3.1:8b"]
        assert consent.scope is ScanScope.THIS_MACHINE

    def test_an_id_not_stored_changes_nothing(self, store):
        store.save([node()], ScanConsent())
        before = store.path.read_text()
        assert store.mark_silent("kitchen-box") is False
        assert store.path.read_text() == before


class TestNodeIdCollision:
    def test_two_different_computers_with_the_same_id_both_survive(self, store):
        # Discovery derives an id from host:port alone before this fix's
        # sibling change, and even after it two ids can still coincide (a
        # person can type one by hand). Whichever way it happens, the store
        # must never let a second computer at a different URL silently
        # displace the first when save() writes nodes keyed by id.
        first = store.upsert(node(node_id="ollama-11434", url="http://10.0.0.9:11434"))
        second = store.upsert(node(node_id="ollama-11434", url="http://10.0.0.5:11434"))
        nodes, _ = store.load()
        assert len(nodes) == 2, "one computer vanished on a node_id collision"
        assert {n.node_id for n in nodes} == {first.node_id, second.node_id}
        assert first.node_id != second.node_id
        assert {n.url for n in nodes} == {"http://10.0.0.9:11434", "http://10.0.0.5:11434"}

    def test_a_third_collision_gets_the_next_suffix(self, store):
        store.upsert(node(node_id="ollama-11434", url="http://10.0.0.1:11434"))
        store.upsert(node(node_id="ollama-11434", url="http://10.0.0.2:11434"))
        third = store.upsert(node(node_id="ollama-11434", url="http://10.0.0.3:11434"))
        assert third.node_id == "ollama-11434-3"


class TestNamesTheRuntimeAlreadyUses:
    """A computer is used by its id, in the same namespace as every other
    endpoint, and a computer's entry wins (design §6). An id taken from a
    name a graph already uses would silently send that graph to a different
    machine -- so a new computer gets a suffix instead (review finding 3)."""

    def test_a_built_in_name_is_not_taken(self, store):
        stored = store.upsert(node(node_id="local-ollama",
                                   url="http://10.0.0.9:11434"))
        assert stored.node_id == "local-ollama-2"
        # The endpoint file named explicitly: the default is the tester's own.
        endpoints = merged_endpoints(
            store, legacy_path=store.path.parent / "model_endpoints.yaml")
        assert endpoints["local-ollama"]["url"] == "http://localhost:11434"

    def test_a_name_in_the_endpoint_file_beside_it_is_not_taken(self, store):
        (store.path.parent / "model_endpoints.yaml").write_text(
            "endpoints:\n  gpu-box:\n    kind: ollama\n"
            "    url: http://10.0.0.5:11434\n", encoding="utf-8")
        stored = store.upsert(node(node_id="gpu-box", kind=NodeKind.LLAMACPP,
                                   url="http://10.0.0.9:8081"))
        assert stored.node_id == "gpu-box-2"
        endpoints = merged_endpoints(
            store, legacy_path=store.path.parent / "model_endpoints.yaml")
        assert endpoints["gpu-box"] == {"kind": "ollama", "url": "http://10.0.0.5:11434"}
        assert endpoints["gpu-box-2"]["url"] == "http://10.0.0.9:8081"

    def test_an_unreadable_endpoint_file_does_not_stop_a_computer_being_recorded(
        self, store
    ):
        """Its names are not in use -- the runtime leaves that file out too."""
        (store.path.parent / "model_endpoints.yaml").write_text(
            "endpoints: [oops\n", encoding="utf-8")
        assert store.upsert(node(node_id="gpu-box")).node_id == "gpu-box"

    def test_a_computer_already_stored_keeps_its_id(self, store):
        """Only a newcomer is renamed. An id already in graphs stays put."""
        store.save([node(node_id="local-ollama", url="http://10.0.0.9:11434")],
                   ScanConsent())
        merged = store.upsert(node(node_id="ollama-10-0-0-9-11434",
                                   url="http://10.0.0.9:11434"))
        assert merged.node_id == "local-ollama"

    def test_one_malformed_entry_does_not_un_reserve_the_others(self, store):
        """m1, review finding 3 reopened: a file with one bad entry used to
        reserve *no* names from it at all -- `legacy_endpoints` refuses the
        whole file, and the old `names_in_use` caught that refusal and gave
        back an empty set, so a hand-written `gpu-box` beside a typo'd
        `spare` was silently replaced the moment a computer took its name."""
        (store.path.parent / "model_endpoints.yaml").write_text(
            "endpoints:\n  gpu-box:\n    kind: ollama\n"
            "    url: http://10.0.0.5:11434\n"
            "  spare:\n    url: http://10.0.0.8:11434\n",  # missing `kind:`
            encoding="utf-8",
        )
        stored = store.upsert(node(node_id="gpu-box", kind=NodeKind.LLAMACPP,
                                   url="http://10.0.0.9:8081"))
        assert stored.node_id == "gpu-box-2", (
            "the hand-written gpu-box was replaced, not the newcomer renamed"
        )

    def test_an_unquoted_numeric_name_is_refused_by_name(self, store):
        """m4: YAML reads an unquoted `7:` as the integer 7, not the text
        "7". `ModelEndpointRegistry.names()` -- FROZEN, in `src/kernel/` --
        then calls `sorted()` on a mapping with both int and str keys and
        raises a bare `TypeError`, not a message naming the file. Caught
        here, before that mapping is ever built."""
        path = store.path.parent / "model_endpoints.yaml"
        path.write_text(
            "endpoints:\n  7:\n    kind: ollama\n    url: http://10.0.0.9:11434\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError) as exc:
            legacy_endpoints(path)
        assert str(path) in str(exc.value)


class TestEndpointResolution:
    def test_defaults_survive_with_no_computers(self, store):
        endpoints = merged_endpoints(store)
        assert "local-ollama" in endpoints
        assert "local-llama" in endpoints

    def test_a_computer_becomes_a_usable_endpoint(self, store):
        store.upsert(node())
        endpoints = merged_endpoints(store)
        assert endpoints["home-pc"] == {"kind": "ollama",
                                        "url": "http://localhost:11434"}

    def test_the_mapping_fits_the_existing_registry(self):
        # The kernel is FROZEN and consumed unchanged: the merged mapping is
        # injected into the registry it already accepts.
        from src.kernel.models import ModelEndpointRegistry

        registry = ModelEndpointRegistry(
            {"home-pc": {"kind": "ollama", "url": "http://h:11434"}}
        )
        assert registry.get("home-pc").url == "http://h:11434"

    def test_a_computer_whose_address_names_a_password_is_left_out(self, store):
        """Final re-review finding 1: the FROZEN kernel copies an
        endpoint's url verbatim into a failed attempt's note, which the
        run ledger keeps. Left out of the mapping entirely, a graph naming
        this computer hits the kernel's own "no model endpoint" refusal --
        which never saw the address -- instead of that leak."""
        store.upsert(node(node_id="tainted",
                          url="http://alice:s3cret@10.0.0.9:11434"))
        endpoints = merged_endpoints(store)
        assert "tainted" not in endpoints

    def test_other_computers_still_resolve_beside_a_tainted_one(self, store):
        store.upsert(node(node_id="tainted",
                          url="http://alice:s3cret@10.0.0.9:11434"))
        store.upsert(node(node_id="clean-box", url="http://10.0.0.1:11434"))
        endpoints = merged_endpoints(store)
        assert "tainted" not in endpoints
        assert endpoints["clean-box"]["url"] == "http://10.0.0.1:11434"


class TestLegacyEndpointsRefuseUserinfo:
    """Final re-review finding 1, for `model_endpoints.yaml`: the same
    plaintext-password leak, through the other file.
    """

    def test_an_entry_naming_a_password_is_refused_without_echoing_it(
        self, store
    ):
        path = store.path.parent / "model_endpoints.yaml"
        path.write_text(
            "endpoints:\n  mine:\n    kind: ollama\n"
            "    url: http://alice:s3cret@10.0.0.9:11434\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError) as exc:
            legacy_endpoints(path)
        message = str(exc.value)
        assert "alice" not in message
        assert "s3cret" not in message
        assert str(path) in message

    def test_the_whole_file_is_left_out_not_just_the_one_entry(self, store):
        """The same rule a malformed `kind:`/`url:` already gets (review
        finding 7): one bad entry voids the file for actual use, so a
        graph naming the *other*, well-formed entry in it also fails
        clean rather than silently resolving half a broken file."""
        path = store.path.parent / "model_endpoints.yaml"
        path.write_text(
            "endpoints:\n"
            "  mine:\n    kind: ollama\n"
            "    url: http://alice:s3cret@10.0.0.9:11434\n"
            "  clean:\n    kind: ollama\n    url: http://10.0.0.1:11434\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError):
            legacy_endpoints(path)


class TestUserinfoInAnyScheme:
    """Review of PR #33: a stored address in a scheme other than http/https
    hid its userinfo from every check, so it resolved and was displayed."""

    def test_a_computer_naming_a_password_in_another_scheme_is_left_out(
        self, store
    ):
        store.upsert(node(node_id="tainted",
                          url="ftp://alice:s3cret@10.0.0.9:11434"))
        assert "tainted" not in merged_endpoints(store)

    def test_an_endpoint_naming_a_password_in_another_scheme_is_refused(
        self, store
    ):
        path = store.path.parent / "model_endpoints.yaml"
        path.write_text(
            "endpoints:\n  mine:\n    kind: ollama\n"
            "    url: ssh://alice:s3cret@10.0.0.9:11434\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError) as exc:
            legacy_endpoints(path)
        assert "s3cret" not in str(exc.value)


class TestANonUtf8EndpointFile:
    """Review of PR #33: `_legacy_names` caught `OSError` and `YAMLError`
    but not `UnicodeDecodeError`, so a non-UTF-8 `model_endpoints.yaml`
    crashed `node add` with a traceback. A file that cannot be read
    reserves no names -- the rule for any unreadable file -- and adding a
    computer still works."""

    def test_it_reserves_no_names_instead_of_crashing(self, store):
        from src.nodes.registry import names_in_use

        path = store.path.parent / "model_endpoints.yaml"
        path.write_bytes(b"endpoints:\n  gpu:\n    kind: ollama\n"
                         b"    url: http://10.0.0.9:11434\n  bad: \"\xff\xfe\"\n")
        assert names_in_use(path) >= set()  # no exception

    def test_a_computer_can_still_be_added(self, store):
        path = store.path.parent / "model_endpoints.yaml"
        path.write_bytes(b"endpoints:\n  bad: \"\xff\xfe\"\n")
        store.upsert(node(node_id="kitchen", url="http://10.0.0.8:11434"))
        assert [n.node_id for n in store.load()[0]] == ["kitchen"]
