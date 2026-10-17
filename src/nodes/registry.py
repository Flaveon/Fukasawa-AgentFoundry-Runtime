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
        if not isinstance(name, str):
            # `sorted()` over a mapping that mixes an int key with the string
            # ones already here is where this surfaced: `model list` crashed
            # with a bare `TypeError`, not a message naming the file (m4).
            # Caught by name before `spec` is even looked at.
            raise ValueError(
                f"{path}: an endpoint's name under `endpoints:` should be "
                f"text, and {name!r} is not. Quote it, e.g. \"{name}\"."
            )
        if not (isinstance(spec, dict) and isinstance(spec.get("kind"), str)
                and isinstance(spec.get("url"), str)):
            raise ValueError(
                f"{path}: '{name}' under `endpoints:` needs a `kind:` and a "
                f"`url:` written under it."
            )
    return dict(entries)


def _legacy_names(path: Path) -> set[str]:
    """Every name written under ``endpoints:``, regardless of whether its
    own details are well-formed.

    ``names_in_use`` only has to know which ids are already spoken for -- not
    whether each entry resolves to a usable endpoint, which is
    ``legacy_endpoints``'s job and stays strict for the callers that read an
    entry's contents (``model list``, a graph run). Reusing that strict
    reading here meant one malformed entry reserved *no* names from the
    file, so a hand-written ``gpu-box`` was silently replaced by a computer
    once another, unrelated entry in the same file had a typo (review
    finding 3's class, reopened -- m1). A file that cannot be opened or is
    not YAML still contributes nothing, matching ``names_in_use``'s existing
    rule for that case.
    """
    if not path.exists():
        return set()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return set()
    if not isinstance(raw, dict):
        return set()
    entries = raw.get("endpoints")
    if not isinstance(entries, dict):
        return set()
    return {name for name in entries if isinstance(name, str)}


def names_in_use(legacy_path: Path) -> set[str]:
    """Names the runtime resolves that are not recorded computers.

    The built-in ones, and those in the endpoint file. A computer is used by
    its id in this same namespace, and a computer's entry wins (design §6),
    so an id taken from one of these would silently send every graph using
    that name to a different machine (review finding 3). ``NodeStore`` gives
    a new computer a suffix instead.

    An endpoint file that cannot be opened or is not YAML contributes no
    names: the runtime leaves it out too, so none of them is in use. One
    that parses but holds a malformed entry still reserves its *other*,
    well-formed names (``_legacy_names``, m1) -- only the entries actually
    used to resolve a graph need to be strict about shape.
    """
    return set(DEFAULT_ENDPOINTS) | _legacy_names(legacy_path)


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
