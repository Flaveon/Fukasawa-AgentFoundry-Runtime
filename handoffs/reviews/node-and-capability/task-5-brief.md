### Task 5: Storage and endpoint resolution

**Files:**
- Create: `src/nodes/store.py`, `src/nodes/registry.py`
- Test: `tests/test_node_store.py`

**Interfaces:**
- Consumes: Tasks 1 and 4.
- Produces: `NodeStore(path)` with `.load() -> tuple[list[InferenceNode], ScanConsent]`, `.save(nodes, consent) -> None`, `.upsert(node) -> InferenceNode`, `.forget(node_id) -> bool`, `.default_path() -> Path`; and `merged_endpoints(store) -> dict[str, dict]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_node_store.py
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

    def test_forget_removes_one(self, store):
        store.upsert(node())
        assert store.forget("home-pc") is True
        assert store.load()[0] == []

    def test_forgetting_an_unknown_id_reports_it(self, store):
        assert store.forget("nope") is False


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
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `.venv/bin/python -m pytest tests/test_node_store.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.nodes.store'`

- [ ] **Step 3: Write the implementation**

```python
# src/nodes/store.py
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
        replaced. Two computers may never share a URL.
        """
        nodes, consent = self.load()
        for index, existing in enumerate(nodes):
            if existing.url != node.url:
                continue
            # Everything a person typed wins over anything just detected. Only
            # top-level fields are editable (see EDITABLE in the GUI service),
            # so a dotted key cannot be DECLARED and none is looked for.
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
                setattr(merged, key, getattr(existing, key))
            nodes[index] = merged
            self.save(nodes, consent)
            return merged

        nodes.append(node)
        self.save(nodes, consent)
        return node

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
```

```python
# src/nodes/registry.py
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
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `.venv/bin/python -m pytest tests/test_node_store.py -q`
Expected: PASS, 14 tests.

- [ ] **Step 5: Confirm no FROZEN file was touched**

```bash
git status --short | grep -E "kernel/|security/|schemas/graph|schemas/bundle|generator\.py|state_machine|runtime/bundle" || echo "no frozen path touched"
```
Expected: `no frozen path touched`

- [ ] **Step 6: Commit**

```bash
git add src/nodes/store.py src/nodes/registry.py tests/test_node_store.py
git commit -m "feat: store computers locally, and resolve them as endpoints"
```

---

