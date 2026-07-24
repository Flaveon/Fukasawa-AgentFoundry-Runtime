# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Bundle schemas — the contract for sharing a whole workflow, safely.

A bundle packages everything one operator needs to receive a workflow from
another: the workflow brief, the graph(s) that orchestrate it, the generated
agent packages, and the eval cases that hold the agents to account. It is the
Phase 5 "export/import format" — the workflow-level counterpart to the app's
own signed release.

Two schemas, one job each:

* ``BundleEntry`` records one file inside the archive with its SHA-256, so a
  recipient can prove nothing was swapped or edited after signing.

* ``BundleManifest`` is the signed heart of a bundle: it lists every entry,
  names the signer, and carries the metadata that makes the archive
  self-describing. The detached signature is computed over this manifest, so
  signing the manifest transitively vouches for every file it hashes.

The trust model is the same one that gates graph execution (security/trust.py):
the runtime enforces the signature; a human decides whose signatures to honor.
A bundle from an untrusted signer, or one whose files no longer match their
recorded hashes, is refused on import — never silently unpacked.
"""

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class BundleRole(str, Enum):
    """What part a file plays inside a bundle.

    The role tells the importer where a file belongs when it is unpacked and
    lets ``fukasawa bundle inspect`` summarize a bundle without extracting it.
    """

    BRIEF = "brief"
    GRAPH = "graph"
    PACKAGE = "package"
    EVAL = "eval"


class BundleEntry(BaseModel):
    """One file inside a bundle, pinned by content hash."""

    path: str = Field(
        description=(
            "Archive-relative path of the file (POSIX separators, never "
            "absolute and never containing '..'). This is where the file "
            "lives inside the archive and, mirrored, where it is written on "
            "import."
        )
    )
    role: BundleRole = Field(
        description="Which part of the workflow this file is: brief, graph, package, or eval."
    )
    sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description="SHA-256 hex digest of the file's exact bytes. The tamper check.",
    )


class BundleManifest(BaseModel):
    """The signed inventory of a bundle — what it contains and who vouches for it.

    The bundle's detached signature is computed over this manifest's canonical
    JSON. Because every content file's hash lives here, one signature over the
    manifest authenticates the entire archive: change any file and its hash no
    longer matches; change the manifest and the signature no longer verifies.
    """

    format_version: str = Field(
        default="1",
        description="Bundle format version, so future importers can stay backward-compatible.",
    )
    bundle_id: str = Field(
        pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$",
        description="Unique slug identifying this bundle.",
    )
    workflow_id: str = Field(
        description="Id of the WorkflowBrief this bundle is built around. All graphs and evals must agree.",
    )
    description: str = Field(
        default="",
        description="Plain-language summary of what this workflow does, for the receiving operator.",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the bundle was exported (UTC).",
    )
    signer_key_id: str = Field(
        description="Short fingerprint of the signing key, for display and trust decisions.",
    )
    signer_public_pem: str = Field(
        description=(
            "The signer's public key, carried so a recipient can see who signed "
            "and, if they choose, add it to their trust store. Trust never comes "
            "from the bundle itself — only from a human putting this key in the "
            "store."
        ),
    )
    entries: list[BundleEntry] = Field(
        min_length=1,
        description="Every content file in the bundle, each pinned by its SHA-256.",
    )

    def entries_by_role(self, role: BundleRole) -> list[BundleEntry]:
        """Return every entry that plays the given role, in manifest order."""
        return [e for e in self.entries if e.role is role]
