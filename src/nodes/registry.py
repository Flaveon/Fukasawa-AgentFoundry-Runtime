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
from typing import Callable, Optional

import yaml

from src.kernel.models import DEFAULT_ENDPOINTS
from src.nodes.store import DEFAULT_HOME, NodeStore


def legacy_endpoints(path: Path) -> dict[str, dict]:
    """The endpoints written in ``model_endpoints.yaml``; none when it is absent.

    A file laid out wrongly raises ``ValueError`` naming the file and, where
    there is one, the entry -- rather than an ``AttributeError`` or
    ``KeyError`` from deep inside the kernel's registry. A file that cannot
    be opened or is not YAML raises as reading it does.
    """
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path} should start with `endpoints:`, and it does not.")
    entries = raw.get("endpoints") or {}
    if not isinstance(entries, dict):
        raise ValueError(
            f"{path}: under `endpoints:` each one should be its name followed "
            f"by its details, and they are not written that way."
        )
    for name, spec in entries.items():
        if not (isinstance(spec, dict) and isinstance(spec.get("kind"), str)
                and isinstance(spec.get("url"), str)):
            raise ValueError(
                f"{path}: '{name}' under `endpoints:` needs a `kind:` and a "
                f"`url:` written under it."
            )
    return dict(entries)


def names_in_use(legacy_path: Path) -> set[str]:
    """Names the runtime resolves that are not recorded computers.

    The built-in ones, and those in the endpoint file. A computer is used by
    its id in this same namespace, and a computer's entry wins (design §6),
    so an id taken from one of these would silently send every graph using
    that name to a different machine (review finding 3). ``NodeStore`` gives
    a new computer a suffix instead.

    An endpoint file that cannot be read contributes no names: the runtime
    leaves it out too, so none of them is in use.
    """
    names = set(DEFAULT_ENDPOINTS)
    try:
        names |= set(legacy_endpoints(legacy_path))
    except (OSError, yaml.YAMLError, ValueError):
        pass
    return names


def merged_endpoints(
    store: Optional[NodeStore] = None,
    legacy_path: Optional[Path] = None,
    on_unreadable: Optional[Callable[[Path, Exception], None]] = None,
) -> dict[str, dict]:
    """Every named endpoint the runtime should know about.

    ``on_unreadable``, when given, is told about each of the two files that
    cannot be used -- ``(path, the error)`` -- and that file is left out, so
    the other still resolves: a graph that uses nothing from a broken file
    still runs. Without it the error is raised, as it always was.
    """
    store = store or NodeStore()
    legacy_path = legacy_path or (DEFAULT_HOME / "model_endpoints.yaml")
    unusable = (OSError, yaml.YAMLError, ValueError)

    endpoints: dict[str, dict] = dict(DEFAULT_ENDPOINTS)

    try:
        endpoints.update(legacy_endpoints(legacy_path))
    except unusable as exc:
        if on_unreadable is None:
            raise
        on_unreadable(legacy_path, exc)

    try:
        nodes, _consent = store.load()
    except unusable as exc:
        if on_unreadable is None:
            raise
        on_unreadable(store.path, exc)
        nodes = []
    for node in nodes:
        endpoints[node.node_id] = {"kind": node.kind.value, "url": node.url}

    return endpoints
