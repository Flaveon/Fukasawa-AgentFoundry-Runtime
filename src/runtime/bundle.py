# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Signed export/import of whole workflows — the Phase 5 sharing format.

A bundle is a single ``.fkz`` file (an ordinary ZIP archive) that carries a
workflow brief, its graph(s), the generated agent packages, and the eval
cases, plus a ``manifest.json`` pinning every file by SHA-256 and a
``manifest.sig`` detached Ed25519 signature over that manifest.

The safety model is the one already load-bearing for graph execution
(security/trust.py, kernel.UntrustedGraphError): the runtime *enforces* the
signature, and a human decides whose signatures to honor. On import a bundle
is refused — before a single file touches disk — unless

* its manifest is signed by a key the operator trusts, and
* every file's bytes still hash to what the signed manifest recorded.

Export is the mirror discipline: an agent package is only bundled if it still
passes its own Foundry validation, and every graph and eval must name the same
workflow as the brief. A bundle that would not survive import is not written.

The archive layout is deterministic::

    manifest.json          the signed inventory (BundleManifest)
    manifest.sig           base64 detached signature over the manifest
    brief/<file>.yaml
    graphs/<file>.yaml
    packages/<agent>/...
    evals/<file>.yaml
"""

import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

import yaml

from src.foundry.validator import validate_package
from src.schemas.bundle import BundleEntry, BundleManifest, BundleRole
from src.schemas.eval_case import EvalCase
from src.schemas.graph import GraphSpec
from src.schemas.workflow_brief import WorkflowBrief
from src.security.signing import content_hash, public_key_id
from src.security.trust import TrustStore

#: File extension for a bundle. A plain ZIP under a workflow-specific suffix.
BUNDLE_SUFFIX = ".fkz"

#: Reserved archive names — the manifest and its detached signature.
MANIFEST_NAME = "manifest.json"
SIGNATURE_NAME = "manifest.sig"

_RESERVED_NAMES = {MANIFEST_NAME, SIGNATURE_NAME}


class BundleError(Exception):
    """Raised when a bundle cannot be built or is structurally invalid."""


class UntrustedBundleError(BundleError):
    """Raised when a bundle is unsigned, or signed by a key the operator does not trust."""


class BundleTamperError(BundleError):
    """Raised when a file's bytes no longer match the hash the signed manifest recorded."""


# --------------------------------------------------------------------- helpers


def _safe_archive_path(path: str) -> str:
    """Reject archive paths that could escape the destination on extraction.

    Absolute paths, drive-relative paths, and any component of ``..`` are the
    classic zip-slip vectors. A bundle is untrusted input until proven signed,
    so this guard runs on every entry before anything is written.
    """
    normalized = path.replace("\\", "/")
    if normalized.startswith("/") or ":" in normalized.split("/")[0]:
        raise BundleTamperError(f"unsafe absolute path in bundle: {path!r}")
    if any(part == ".." for part in normalized.split("/")):
        raise BundleTamperError(f"path traversal in bundle: {path!r}")
    return normalized


def _load_yaml(path: Path):
    """Read and parse a YAML/JSON file, raising BundleError on failure."""
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise BundleError(f"cannot read {path}: {exc}") from exc


@dataclass
class _StagedFile:
    """A file collected for export: its archive path, role, and raw bytes."""

    archive_path: str
    role: BundleRole
    data: bytes


@dataclass
class BundleImportResult:
    """The outcome of importing a bundle: what was verified and unpacked."""

    manifest: BundleManifest
    dest: Path
    signer_key_id: str
    signer_trusted: bool
    extracted: list[Path] = field(default_factory=list)


@dataclass
class BundleInspection:
    """A read-only verification of a bundle, without extracting it."""

    manifest: BundleManifest
    signer_key_id: str
    signer_trusted: bool
    hashes_ok: bool


# ---------------------------------------------------------------------- export


def _stage_brief(brief_path: Path) -> tuple[WorkflowBrief, _StagedFile]:
    """Validate a brief and stage it under brief/ in the archive."""
    brief = WorkflowBrief.model_validate(_load_yaml(brief_path))
    data = brief_path.read_bytes()
    return brief, _StagedFile(f"brief/{brief_path.name}", BundleRole.BRIEF, data)


def _stage_graph(graph_path: Path, brief: WorkflowBrief) -> _StagedFile:
    """Validate a graph, enforce it names the bundle's workflow, and stage it."""
    graph = GraphSpec.model_validate(_load_yaml(graph_path))
    if graph.workflow != brief.id:
        raise BundleError(
            f"graph '{graph.graph_id}' orchestrates '{graph.workflow}', not the "
            f"bundle's workflow '{brief.id}'. A bundle carries one coherent "
            f"workflow — export the matching graph, or the right brief."
        )
    return _StagedFile(f"graphs/{graph_path.name}", BundleRole.GRAPH, graph_path.read_bytes())


def _stage_eval(eval_path: Path, brief: WorkflowBrief) -> _StagedFile:
    """Validate an eval case, enforce workflow agreement, and stage it."""
    case = EvalCase.model_validate(_load_yaml(eval_path))
    if case.workflow != brief.id:
        raise BundleError(
            f"eval case '{case.case_id}' targets workflow '{case.workflow}', not "
            f"the bundle's '{brief.id}'."
        )
    return _StagedFile(f"evals/{eval_path.name}", BundleRole.EVAL, eval_path.read_bytes())


def _stage_package(package_dir: Path) -> list[_StagedFile]:
    """Validate an agent package and stage its whole directory tree.

    A package that fails Foundry validation is never bundled: shipping a
    package that would not pass its own gate is exactly the non-conformance
    the export step exists to prevent.
    """
    findings = validate_package(package_dir)
    if findings:
        raise BundleError(
            f"agent package '{package_dir.name}' fails validation and will not "
            f"be bundled:\n  - " + "\n  - ".join(findings)
        )
    staged: list[_StagedFile] = []
    for file in sorted(p for p in package_dir.rglob("*") if p.is_file()):
        rel = file.relative_to(package_dir.parent).as_posix()
        staged.append(_StagedFile(f"packages/{rel}", BundleRole.PACKAGE, file.read_bytes()))
    return staged


def export_bundle(
    *,
    brief_path: str | Path,
    out_path: str | Path,
    graph_paths: Sequence[str | Path] = (),
    package_dirs: Sequence[str | Path] = (),
    eval_paths: Sequence[str | Path] = (),
    trust_store: Optional[TrustStore] = None,
    description: str = "",
    bundle_id: Optional[str] = None,
) -> BundleManifest:
    """Collect, hash, and sign a workflow into a portable ``.fkz`` bundle.

    Every artifact is validated first — the brief and graphs parse, each graph
    and eval names the same workflow as the brief, and each agent package
    passes Foundry validation — so a written bundle is always one that will
    survive import. The manifest is then signed with the local identity, which
    is what makes the bundle safe for someone else to trust.

    Returns the BundleManifest that was written into the archive.
    """
    brief_path = Path(brief_path)
    out_path = Path(out_path)
    store = trust_store or TrustStore()

    brief, brief_file = _stage_brief(brief_path)
    staged: list[_StagedFile] = [brief_file]
    for gp in graph_paths:
        staged.append(_stage_graph(Path(gp), brief))
    for ep in eval_paths:
        staged.append(_stage_eval(Path(ep), brief))
    for pd in package_dirs:
        staged.extend(_stage_package(Path(pd)))

    # Guard against two staged files claiming the same archive path — a silent
    # overwrite would drop content the manifest still promises.
    seen: set[str] = set()
    for sf in staged:
        if sf.archive_path in _RESERVED_NAMES:
            raise BundleError(f"'{sf.archive_path}' is a reserved bundle name")
        if sf.archive_path in seen:
            raise BundleError(
                f"two files map to the same bundle path '{sf.archive_path}' — "
                f"rename one before bundling"
            )
        seen.add(sf.archive_path)

    entries = [
        BundleEntry(path=sf.archive_path, role=sf.role, sha256=content_hash(sf.data))
        for sf in staged
    ]
    keypair = store.ensure_identity()
    manifest = BundleManifest(
        bundle_id=bundle_id or f"bundle-{uuid.uuid4().hex[:8]}",
        workflow_id=brief.id,
        description=description or brief.title,
        signer_key_id=public_key_id(keypair.public_pem),
        signer_public_pem=keypair.public_pem,
        entries=entries,
    )
    signature, _ = store.sign_with_identity(manifest.model_dump(mode="json"))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, manifest.model_dump_json(indent=2))
        zf.writestr(SIGNATURE_NAME, signature)
        for sf in staged:
            zf.writestr(sf.archive_path, sf.data)
    return manifest


# --------------------------------------------------------------- read / verify


def _read_manifest_and_signature(zf: zipfile.ZipFile) -> tuple[BundleManifest, str]:
    """Parse and validate a bundle's manifest and detached signature."""
    names = set(zf.namelist())
    if MANIFEST_NAME not in names or SIGNATURE_NAME not in names:
        raise BundleError(
            "not a valid bundle: missing manifest.json or manifest.sig"
        )
    try:
        manifest = BundleManifest.model_validate_json(
            zf.read(MANIFEST_NAME).decode("utf-8")
        )
    except ValueError as exc:
        raise BundleError(f"bundle manifest is malformed: {exc}") from exc
    signature = zf.read(SIGNATURE_NAME).decode("utf-8").strip()
    return manifest, signature


def _verify_hashes(zf: zipfile.ZipFile, manifest: BundleManifest) -> None:
    """Confirm every manifest entry is present and unmodified, with no extras.

    Three ways a bundle can lie, all caught here: a listed file is missing, a
    listed file's bytes changed, or an unlisted file was smuggled in (content
    the signature never covered). Any of them raises BundleTamperError.
    """
    archive_files = {
        n for n in zf.namelist() if n not in _RESERVED_NAMES and not n.endswith("/")
    }
    manifest_paths = set()
    for entry in manifest.entries:
        _safe_archive_path(entry.path)  # raises on unsafe paths
        manifest_paths.add(entry.path)
        if entry.path not in archive_files:
            raise BundleTamperError(
                f"bundle is missing a file the manifest promises: {entry.path!r}"
            )
        actual = content_hash(zf.read(entry.path))
        if actual != entry.sha256:
            raise BundleTamperError(
                f"content of {entry.path!r} does not match its signed hash "
                f"(expected {entry.sha256[:12]}…, got {actual[:12]}…)"
            )
    extra = archive_files - manifest_paths
    if extra:
        raise BundleTamperError(
            "bundle carries files the signed manifest never listed: "
            + ", ".join(sorted(repr(e) for e in extra))
        )


def _check_trusted(
    manifest: BundleManifest, signature: str, store: TrustStore
) -> bool:
    """Return whether the manifest's signature is honored by a trusted key."""
    if not signature:
        return False
    return store.is_trusted_signature(manifest.model_dump(mode="json"), signature)


def inspect_bundle(
    bundle_path: str | Path, trust_store: Optional[TrustStore] = None
) -> BundleInspection:
    """Verify a bundle's signature and file hashes without extracting it.

    A pure read: it answers "is this bundle intact, and do I trust who signed
    it?" so an operator can decide before unpacking. Hash tampering raises;
    an untrusted-but-intact bundle returns with ``signer_trusted=False`` rather
    than raising, because inspecting an untrusted bundle is a legitimate step
    on the way to deciding whether to trust its author.
    """
    store = trust_store or TrustStore()
    with zipfile.ZipFile(Path(bundle_path)) as zf:
        manifest, signature = _read_manifest_and_signature(zf)
        _verify_hashes(zf, manifest)
        trusted = _check_trusted(manifest, signature, store)
    return BundleInspection(
        manifest=manifest,
        signer_key_id=manifest.signer_key_id,
        signer_trusted=trusted,
        hashes_ok=True,
    )


def import_bundle(
    bundle_path: str | Path,
    dest_dir: str | Path,
    *,
    trust_store: Optional[TrustStore] = None,
    require_trusted: bool = True,
) -> BundleImportResult:
    """Verify a bundle and unpack it — refusing untrusted or tampered archives.

    The order is the whole point: signature and hashes are checked while the
    bundle is still only bytes in memory, and nothing is written to ``dest_dir``
    until both pass. A bundle from an untrusted signer, or one whose files no
    longer match the signed manifest, is refused before it can leave a single
    file behind.

    ``require_trusted=False`` drops the trust gate (hash verification still
    runs) — for the local roundtrip case and for deliberately importing your
    own export, never as a way to run someone else's unvouched-for workflow.
    """
    store = trust_store or TrustStore()
    dest = Path(dest_dir)
    with zipfile.ZipFile(Path(bundle_path)) as zf:
        manifest, signature = _read_manifest_and_signature(zf)
        trusted = _check_trusted(manifest, signature, store)
        if require_trusted and not trusted:
            raise UntrustedBundleError(
                f"bundle '{manifest.bundle_id}' is signed by key "
                f"'{manifest.signer_key_id}', which is not in your trust store. "
                f"Refusing to import it. Add the author's key with "
                f"'fukasawa trust add' only if you vouch for them."
            )
        # Verify (and path-check) every file before writing anything to disk.
        _verify_hashes(zf, manifest)
        dest.mkdir(parents=True, exist_ok=True)
        extracted: list[Path] = []
        for entry in manifest.entries:
            safe = _safe_archive_path(entry.path)
            target = dest / safe
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(entry.path))
            extracted.append(target)
    return BundleImportResult(
        manifest=manifest,
        dest=dest,
        signer_key_id=manifest.signer_key_id,
        signer_trusted=trusted,
        extracted=extracted,
    )
