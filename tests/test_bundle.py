# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Bundle export/import tests — the Phase 5C sharing format, held to its contract.

The four behaviors the format exists to guarantee:

* a trusted roundtrip export -> import reproduces every file,
* tampering with any file after signing is caught on import,
* a bundle from an untrusted signer is refused before anything is unpacked,
* a bundle from a trusted signer is accepted.

Plus the export-side discipline (workflow coherence, package validation) and
the zip-slip / smuggled-file guards on the import side.
"""

import zipfile
from pathlib import Path

import pytest

from src.runtime.bundle import (
    BUNDLE_SUFFIX,
    MANIFEST_NAME,
    BundleError,
    BundleTamperError,
    UntrustedBundleError,
    export_bundle,
    import_bundle,
    inspect_bundle,
)
from src.schemas.bundle import BundleManifest
from src.security.trust import TrustStore

ROOT = Path(__file__).resolve().parent.parent
BRIEF = ROOT / "examples" / "q2c-production-handoff.yaml"
GRAPH = ROOT / "examples" / "q2c-pipeline-graph.yaml"
PACKAGE = ROOT / "examples" / "packages" / "writer-agent"
EVAL = ROOT / "examples" / "evals" / "q2c-writer-handoff.yaml"


def _export(out: Path, store: TrustStore, **kw) -> BundleManifest:
    """Export the example workflow, defaulting to the full artifact set."""
    return export_bundle(
        brief_path=BRIEF,
        out_path=out,
        graph_paths=kw.pop("graph_paths", [GRAPH]),
        package_dirs=kw.pop("package_dirs", [PACKAGE]),
        eval_paths=kw.pop("eval_paths", [EVAL]),
        trust_store=store,
        **kw,
    )


class TestRoundtrip:
    def test_export_writes_a_signed_bundle(self, tmp_path):
        store = TrustStore(tmp_path / "store")
        out = tmp_path / f"wf{BUNDLE_SUFFIX}"
        manifest = _export(out, store)
        assert out.exists()
        with zipfile.ZipFile(out) as zf:
            names = set(zf.namelist())
        assert MANIFEST_NAME in names and "manifest.sig" in names
        assert "brief/q2c-production-handoff.yaml" in names
        assert any(n.startswith("packages/writer-agent/") for n in names)
        assert manifest.workflow_id == "q2c-production-handoff"

    def test_trusted_roundtrip_reproduces_every_file(self, tmp_path):
        store = TrustStore(tmp_path / "store")
        out = tmp_path / f"wf{BUNDLE_SUFFIX}"
        manifest = _export(out, store)
        result = import_bundle(out, tmp_path / "dest", trust_store=store)
        assert result.signer_trusted
        # Every promised file landed, byte-identical.
        for entry in manifest.entries:
            landed = (tmp_path / "dest" / entry.path)
            assert landed.exists(), entry.path
        assert (tmp_path / "dest" / "brief" / "q2c-production-handoff.yaml").read_bytes() \
            == BRIEF.read_bytes()

    def test_inspect_reports_intact_and_trusted(self, tmp_path):
        store = TrustStore(tmp_path / "store")
        out = tmp_path / f"wf{BUNDLE_SUFFIX}"
        _export(out, store)
        inspection = inspect_bundle(out, trust_store=store)
        assert inspection.hashes_ok
        assert inspection.signer_trusted


class TestTamper:
    def _rewrite(self, src: Path, dst: Path, edits: dict[str, bytes]) -> None:
        """Copy a zip, replacing/adding the named members with new bytes."""
        with zipfile.ZipFile(src) as zin:
            items = [(i, zin.read(i.filename)) for i in zin.infolist()]
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
            for info, data in items:
                zout.writestr(info.filename, edits.get(info.filename, data))
            for name, data in edits.items():
                if name not in {i.filename for i, _ in items}:
                    zout.writestr(name, data)

    def test_edited_file_is_refused(self, tmp_path):
        store = TrustStore(tmp_path / "store")
        good = tmp_path / f"good{BUNDLE_SUFFIX}"
        _export(good, store)
        bad = tmp_path / f"bad{BUNDLE_SUFFIX}"
        self._rewrite(good, bad, {"brief/q2c-production-handoff.yaml": b"tampered"})
        with pytest.raises(BundleTamperError, match="does not match its signed hash"):
            import_bundle(bad, tmp_path / "dest", trust_store=store)
        assert not (tmp_path / "dest").exists()  # nothing written on refusal

    def test_smuggled_file_is_refused(self, tmp_path):
        store = TrustStore(tmp_path / "store")
        good = tmp_path / f"good{BUNDLE_SUFFIX}"
        _export(good, store)
        bad = tmp_path / f"bad{BUNDLE_SUFFIX}"
        self._rewrite(good, bad, {"packages/writer-agent/EXTRA.md": b"not signed"})
        with pytest.raises(BundleTamperError, match="never listed"):
            import_bundle(bad, tmp_path / "dest", trust_store=store)

    def test_manifest_edit_breaks_signature(self, tmp_path):
        store = TrustStore(tmp_path / "store")
        good = tmp_path / f"good{BUNDLE_SUFFIX}"
        m = _export(good, store)
        # Re-serialize the manifest with a changed description: the signature no
        # longer verifies, so the (now effectively unsigned) bundle is untrusted.
        forged = m.model_copy(update={"description": "forged"})
        bad = tmp_path / f"bad{BUNDLE_SUFFIX}"
        self._rewrite(good, bad, {MANIFEST_NAME: forged.model_dump_json(indent=2).encode()})
        with pytest.raises(UntrustedBundleError):
            import_bundle(bad, tmp_path / "dest", trust_store=store)


class TestTrustGate:
    def test_untrusted_signer_is_refused(self, tmp_path):
        author = TrustStore(tmp_path / "author")   # signs the bundle
        recipient = TrustStore(tmp_path / "recip")  # does not know the author
        recipient.ensure_identity()
        out = tmp_path / f"wf{BUNDLE_SUFFIX}"
        _export(out, author)
        with pytest.raises(UntrustedBundleError, match="not in your trust store"):
            import_bundle(out, tmp_path / "dest", trust_store=recipient)
        assert not (tmp_path / "dest").exists()

    def test_trusting_the_author_lets_the_bundle_in(self, tmp_path):
        author = TrustStore(tmp_path / "author")
        recipient = TrustStore(tmp_path / "recip")
        author_key = author.ensure_identity()
        out = tmp_path / f"wf{BUNDLE_SUFFIX}"
        _export(out, author)
        # The human vouches for the author's key; now the bundle is honored.
        recipient.trust(author_key.public_pem, name="author")
        result = import_bundle(out, tmp_path / "dest", trust_store=recipient)
        assert result.signer_trusted
        assert (tmp_path / "dest" / "brief" / "q2c-production-handoff.yaml").exists()

    def test_allow_untrusted_bypasses_the_gate(self, tmp_path):
        author = TrustStore(tmp_path / "author")
        recipient = TrustStore(tmp_path / "recip")
        recipient.ensure_identity()
        out = tmp_path / f"wf{BUNDLE_SUFFIX}"
        _export(out, author)
        result = import_bundle(
            out, tmp_path / "dest", trust_store=recipient, require_trusted=False
        )
        assert not result.signer_trusted
        assert result.extracted  # but the (intact) files were unpacked

    def test_inspect_of_untrusted_bundle_does_not_raise(self, tmp_path):
        author = TrustStore(tmp_path / "author")
        recipient = TrustStore(tmp_path / "recip")
        recipient.ensure_identity()
        out = tmp_path / f"wf{BUNDLE_SUFFIX}"
        _export(out, author)
        inspection = inspect_bundle(out, trust_store=recipient)
        assert inspection.hashes_ok
        assert not inspection.signer_trusted


class TestExportDiscipline:
    def test_graph_for_other_workflow_is_refused(self, tmp_path):
        store = TrustStore(tmp_path / "store")
        other = tmp_path / "other-graph.yaml"
        # A structurally valid graph that names a different workflow.
        other.write_text(
            "graph_id: other-graph\n"
            "workflow: some-other-workflow\n"
            "nodes:\n"
            "  - node_id: n1\n"
            "    kind: deterministic\n"
            "    adapter: noop\n",
            encoding="utf-8",
        )
        with pytest.raises(BundleError, match="not the bundle's workflow"):
            _export(tmp_path / f"wf{BUNDLE_SUFFIX}", store, graph_paths=[other])

    def test_invalid_package_is_not_bundled(self, tmp_path):
        store = TrustStore(tmp_path / "store")
        empty_pkg = tmp_path / "broken-agent"
        empty_pkg.mkdir()  # missing every required file
        with pytest.raises(BundleError, match="fails validation"):
            _export(tmp_path / f"wf{BUNDLE_SUFFIX}", store, package_dirs=[empty_pkg])

    def test_brief_only_bundle_is_valid(self, tmp_path):
        store = TrustStore(tmp_path / "store")
        out = tmp_path / f"wf{BUNDLE_SUFFIX}"
        manifest = _export(out, store, graph_paths=[], package_dirs=[], eval_paths=[])
        assert len(manifest.entries) == 1
        result = import_bundle(out, tmp_path / "dest", trust_store=store)
        assert result.signer_trusted


class TestMalformedBundle:
    def test_non_bundle_zip_is_rejected(self, tmp_path):
        store = TrustStore(tmp_path / "store")
        junk = tmp_path / f"junk{BUNDLE_SUFFIX}"
        with zipfile.ZipFile(junk, "w") as zf:
            zf.writestr("hello.txt", "not a bundle")
        with pytest.raises(BundleError, match="missing manifest"):
            inspect_bundle(junk, trust_store=store)
