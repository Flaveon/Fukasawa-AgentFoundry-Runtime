# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Where what a person told us is kept, and how it reaches the runtime."""

import pytest
import yaml

from src.nodes.registry import merged_endpoints
from src.nodes.store import NodeStore
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

    def test_forget_removes_one(self, store):
        store.upsert(node())
        assert store.forget("home-pc") is True
        assert store.load()[0] == []

    def test_forgetting_an_unknown_id_reports_it(self, store):
        assert store.forget("nope") is False


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
