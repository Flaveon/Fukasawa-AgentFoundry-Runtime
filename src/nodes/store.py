# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Where what a person told us about their computers is kept.

One file, ``$FUKASAWA_HOME/nodes.yaml``, holding both the computers and the
standing permission — a permission with no computers beside it is a thing
people lose track of.

**This file describes somebody's house.** It is per-operator, never committed,
never bundled into a distribution, and never written into an exported brief. A
shared workflow references a computer by name; the address stays here.

The upsert rule is what makes "Check again" safe to press: rediscovering an
address already stored refreshes the values that were *detected* and preserves
every value a person *typed*.
"""

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import ValidationError

from src.schemas.node import InferenceNode, Provenance, ScanConsent

#: Matches the trust store's location, so everything local lives together.
DEFAULT_HOME = Path(os.environ.get("FUKASAWA_HOME", "~/.fukasawa")).expanduser()


class NodeStore:
    """Read and write the computers a person has told us about."""

    def __init__(self, path: Optional[Path] = None) -> None:
        """Bind to a file. Defaults to `$FUKASAWA_HOME/nodes.yaml`."""
        self.path = Path(path) if path else self.default_path()

    @staticmethod
    def default_path() -> Path:
        """Where this file lives when nobody says otherwise."""
        return DEFAULT_HOME / "nodes.yaml"

    def load(self) -> tuple[list[InferenceNode], ScanConsent]:
        """Everything stored. A missing file is no computers and no permission."""
        if not self.path.exists():
            return [], ScanConsent()
        raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        try:
            nodes = [
                InferenceNode.model_validate({**spec, "node_id": node_id})
                for node_id, spec in (raw.get("nodes") or {}).items()
            ]
            consent = ScanConsent.model_validate(raw.get("consent") or {})
        except ValidationError as exc:
            raise ValueError(f"{self.path} does not match the contract — {exc}") from exc
        return nodes, consent

    def save(self, nodes: list[InferenceNode], consent: ScanConsent) -> None:
        """Write every computer and the standing permission."""
        payload = {
            "schema_version": "1",
            "consent": consent.model_dump(mode="json", exclude={"schema_version"}),
            "nodes": {
                node.node_id: node.model_dump(
                    mode="json", exclude={"node_id", "schema_version"}
                )
                for node in nodes
            },
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            yaml.safe_dump(payload, sort_keys=False, width=100, allow_unicode=True),
            encoding="utf-8",
        )

    def upsert(self, node: InferenceNode) -> InferenceNode:
        """Add a computer, or refresh one already stored at the same address.

        Values a person typed are preserved; values that were detected are
        replaced. Two computers may never share a URL, and never silently
        share an id either -- a newly discovered id already in use by a
        different computer gets a numeric suffix (see ``_with_unique_id``).
        """
        nodes, consent = self.load()
        for index, existing in enumerate(nodes):
            if existing.url != node.url:
                continue
            # Everything a person typed wins over anything just detected.
            # Only a top-level field can be copied across by name below --
            # a dotted key (e.g. "host.vram_bytes") records provenance for
            # a nested value, and nothing in the current UI produces one, so
            # it is carried through in the provenance map but skipped in the
            # copy loop rather than looked up as an attribute.
            typed = {
                key: source
                for key, source in existing.provenance.items()
                if source is Provenance.DECLARED
            }
            merged = node.model_copy(update={
                "node_id": existing.node_id,
                "provenance": {**node.provenance, **typed},
            })
            for key in typed:
                if "." in key:
                    continue
                setattr(merged, key, getattr(existing, key))
            nodes[index] = merged
            self.save(nodes, consent)
            return merged

        node = self._with_unique_id(node, nodes)
        nodes.append(node)
        self.save(nodes, consent)
        return node

    @staticmethod
    def _with_unique_id(node: InferenceNode, nodes: list[InferenceNode]) -> InferenceNode:
        """Give ``node`` an id nobody in ``nodes`` already holds.

        Discovery derives an id from host:port (see ``src/nodes/discovery.py``),
        so two different computers can independently produce the same one
        before either is stored. A collision reaching here is never the same
        computer -- ``upsert`` already matched on URL above and found none --
        so the newcomer gets a numeric suffix (``-2``, ``-3``, ...) rather
        than silently displacing whoever already holds the id when ``save()``
        writes ``nodes`` as a dict keyed by id.
        """
        taken = {existing.node_id for existing in nodes}
        if node.node_id not in taken:
            return node
        suffix = 2
        while f"{node.node_id}-{suffix}" in taken:
            suffix += 1
        return node.model_copy(update={"node_id": f"{node.node_id}-{suffix}"})

    def forget(self, node_id: str) -> bool:
        """Remove one computer. False when there was nothing by that name."""
        nodes, consent = self.load()
        remaining = [n for n in nodes if n.node_id != node_id]
        if len(remaining) == len(nodes):
            return False
        self.save(remaining, consent)
        return True

    def set_consent(self, consent: ScanConsent) -> None:
        """Record a new standing permission, leaving the computers alone."""
        nodes, _ = self.load()
        self.save(nodes, consent)
