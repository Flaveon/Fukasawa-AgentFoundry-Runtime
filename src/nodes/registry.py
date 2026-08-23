# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Making stored computers usable by the runtime that already exists.

`src/kernel/models.py` is FROZEN, and it does not need changing:
``ModelEndpointRegistry`` already accepts an explicit mapping. So the merge
happens here and the result is injected — the kernel is consumed unchanged,
exactly as the rest of this release consumes it.

Resolution order, later winning:

    built-in defaults  ->  model_endpoints.yaml  ->  nodes.yaml

An existing endpoint file keeps working untouched, and a computer becomes a
usable endpoint under its own id, so a graph says ``endpoint: home-pc`` and
never carries an address.
"""

from pathlib import Path
from typing import Optional

import yaml

from src.kernel.models import DEFAULT_ENDPOINTS
from src.nodes.store import DEFAULT_HOME, NodeStore


def merged_endpoints(
    store: Optional[NodeStore] = None,
    legacy_path: Optional[Path] = None,
) -> dict[str, dict]:
    """Every named endpoint the runtime should know about."""
    store = store or NodeStore()
    legacy_path = legacy_path or (DEFAULT_HOME / "model_endpoints.yaml")

    endpoints: dict[str, dict] = dict(DEFAULT_ENDPOINTS)

    if legacy_path.exists():
        raw = yaml.safe_load(legacy_path.read_text(encoding="utf-8")) or {}
        endpoints.update(raw.get("endpoints") or {})

    nodes, _consent = store.load()
    for node in nodes:
        endpoints[node.node_id] = {"kind": node.kind.value, "url": node.url}

    return endpoints
