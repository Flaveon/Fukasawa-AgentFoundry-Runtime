# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Trust and integrity tests — the three commit-review findings, closed.

* Command injection / arbitrary file access from a *shared* graph is
  neutralized by refusing to run graphs not signed by a trusted key.
* Path traversal is additionally jailed by the filesystem workspace root.
* Graph swap on resume is caught by the pinned graph hash.
"""

from pathlib import Path

import pytest

from src.kernel.adapters import AdapterRegistry, FilesystemAdapter
from src.kernel.kernel import (
    GraphRunner,
    GraphSpecError,
    UntrustedGraphError,
    graph_fingerprint,
    load_graph,
)
from src.runtime.ledger import RunLedger
from src.schemas.graph import GraphSpec
from src.security.signing import (
    generate_keypair,
    content_hash,
    public_key_id,
    sign,
    verify,
)
from src.security.trust import TrustStore

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_BRIEF = ROOT / "examples" / "q2c-production-handoff.yaml"
PILOT_GRAPH = ROOT / "examples" / "q2c-pipeline-graph.yaml"


class TestSigning:
    def test_sign_and_verify_roundtrip(self):
        kp = generate_keypair()
        payload = {"graph": "x", "nodes": [1, 2, 3]}
        sig = sign(payload, kp.private_pem)
        assert verify(payload, sig, kp.public_pem)

    def test_tampered_payload_fails_verification(self):
        kp = generate_keypair()
        sig = sign({"v": 1}, kp.private_pem)
        assert not verify({"v": 2}, sig, kp.public_pem)

    def test_wrong_key_fails_verification(self):
        a, b = generate_keypair(), generate_keypair()
        sig = sign({"v": 1}, a.private_pem)
        assert not verify({"v": 1}, sig, b.public_pem)

    def test_content_hash_is_order_independent(self):
        assert content_hash({"a": 1, "b": 2}) == content_hash({"b": 2, "a": 1})

    def test_bad_signature_never_raises(self):
        kp = generate_keypair()
        assert verify({"v": 1}, "not-base64-!!", kp.public_pem) is False


class TestTrustStore:
    def test_identity_is_created_and_auto_trusted(self, tmp_path):
        store = TrustStore(tmp_path / "store")
        kp = store.ensure_identity(name="alice")
        # The private key is not world-readable.
        mode = (store.identity_dir / "private.pem").stat().st_mode & 0o077
        assert mode == 0
        # You trust yourself.
        sig = sign({"v": 1}, kp.private_pem)
        assert store.is_trusted_signature({"v": 1}, sig)

    def test_untrusted_key_is_not_honored(self, tmp_path):
        store = TrustStore(tmp_path / "store")
        store.ensure_identity()
        stranger = generate_keypair()
        sig = sign({"v": 1}, stranger.private_pem)
        assert not store.is_trusted_signature({"v": 1}, sig)
        # After explicitly trusting the stranger, it is honored.
        store.trust(stranger.public_pem, name="stranger")
        assert store.is_trusted_signature({"v": 1}, sig)

    def test_revoke_removes_trust(self, tmp_path):
        store = TrustStore(tmp_path / "store")
        stranger = generate_keypair()
        key = store.trust(stranger.public_pem)
        assert store.revoke(key.key_id)
        sig = sign({"v": 1}, stranger.private_pem)
        assert not store.is_trusted_signature({"v": 1}, sig)


@pytest.fixture()
def brief():
    return GraphRunner(RunLedger(":memory:")).runtime.load_brief(EXAMPLE_BRIEF)


class TestTrustEnforcement:
    """Finding #1/#2: shared graphs run only when trusted-signed."""

    def test_unsigned_graph_refused_when_enforcing(self, tmp_path, brief):
        store = TrustStore(tmp_path / "store")
        store.ensure_identity()
        runner = GraphRunner(
            RunLedger(tmp_path / "t.db"), handoff_dir=tmp_path / "h", trust_store=store
        )
        graph = load_graph(PILOT_GRAPH)
        with pytest.raises(UntrustedGraphError, match="unsigned"):
            runner.start(graph, brief)

    def test_untrusted_signer_refused(self, tmp_path, brief):
        store = TrustStore(tmp_path / "store")
        store.ensure_identity()
        stranger = generate_keypair()
        graph = load_graph(PILOT_GRAPH)
        sig = sign(graph.model_dump(mode="json"), stranger.private_pem)
        runner = GraphRunner(
            RunLedger(tmp_path / "t.db"), handoff_dir=tmp_path / "h", trust_store=store
        )
        with pytest.raises(UntrustedGraphError, match="not signed by any trusted key"):
            runner.start(graph, brief, signature=sig)

    def test_trusted_signature_runs(self, tmp_path, brief):
        store = TrustStore(tmp_path / "store")
        graph = load_graph(PILOT_GRAPH)
        sig, _ = store.sign_with_identity(graph.model_dump(mode="json"))
        runner = GraphRunner(
            RunLedger(tmp_path / "t.db"), handoff_dir=tmp_path / "h", trust_store=store
        )
        state = runner.start(graph, brief, signature=sig)
        assert state.graph_hash == graph_fingerprint(graph)

    def test_no_enforcement_without_trust_store(self, tmp_path, brief):
        # Backward-compatible: no trust store means local, unenforced.
        runner = GraphRunner(RunLedger(tmp_path / "t.db"), handoff_dir=tmp_path / "h")
        state = runner.start(load_graph(PILOT_GRAPH), brief)
        assert state.graph_hash  # still pinned


class TestGraphPinning:
    """Finding #3: a resume cannot swap in a different graph."""

    def test_resume_with_different_graph_is_refused(self, tmp_path, brief):
        runner = GraphRunner(RunLedger(tmp_path / "t.db"), handoff_dir=tmp_path / "h")
        graph = load_graph(PILOT_GRAPH)
        state = runner.start(graph, brief, variables={"workdir": "x", "destdir": "y"})
        # Build a *different* graph with the same id.
        data = graph.model_dump(mode="json")
        data["description"] = "tampered"
        swapped = GraphSpec.model_validate(data)
        with pytest.raises(GraphSpecError, match="hash mismatch"):
            runner.resume(swapped, state.graph_run_id)

    def test_resume_with_same_graph_passes_pin(self, tmp_path, brief):
        runner = GraphRunner(RunLedger(tmp_path / "t.db"), handoff_dir=tmp_path / "h")
        graph = load_graph(PILOT_GRAPH)
        state = runner.start(graph, brief, variables={"workdir": "x", "destdir": "y"})
        # Resuming a non-blocked/paused run is a no-op, but the pin check runs
        # first and must not raise for the identical graph.
        same = load_graph(PILOT_GRAPH)
        result = runner.resume(same, state.graph_run_id)
        assert result.graph_run_id == state.graph_run_id


class TestFilesystemJail:
    """Finding #2: path traversal blocked by the workspace jail."""

    def test_jailed_adapter_refuses_escape(self, tmp_path):
        jail = tmp_path / "work"
        jail.mkdir()
        adapter = FilesystemAdapter(workspace_root=jail)
        secret = tmp_path / "secret.txt"
        secret.write_text("password")
        result = adapter.execute({"op": "read", "path": str(secret)})
        assert not result.ok
        assert "outside the workspace jail" in result.note

    def test_jailed_adapter_allows_inside(self, tmp_path):
        jail = tmp_path / "work"
        jail.mkdir()
        (jail / "ok.txt").write_text("fine")
        adapter = FilesystemAdapter(workspace_root=jail)
        result = adapter.execute({"op": "read", "path": str(jail / "ok.txt")})
        assert result.ok

    def test_traversal_string_cannot_escape(self, tmp_path):
        jail = tmp_path / "work"
        jail.mkdir()
        adapter = FilesystemAdapter(workspace_root=jail)
        result = adapter.execute(
            {"op": "read", "path": str(jail / ".." / "escape.txt")}
        )
        assert not result.ok

    def test_registry_passes_jail_through(self, tmp_path):
        jail = tmp_path / "work"
        jail.mkdir()
        registry = AdapterRegistry(workspace_root=jail)
        fs = registry.get("filesystem")
        result = fs.execute({"op": "write", "path": str(tmp_path / "out.txt"), "content": "x"})
        assert not result.ok  # tmp_path is above the jail
