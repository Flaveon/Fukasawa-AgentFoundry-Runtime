### Task 4: Consent-gated streaming discovery

**Files:**
- Create: `src/nodes/discovery.py`
- Test: `tests/test_node_discovery.py`

**Interfaces:**
- Consumes: Tasks 1 and 3.
- Produces: `DiscoveryEvent(stage, message, ok, node, progress, finished)`, `discover(scope, host="", *, consent=None, fetch=..., connect_timeout=2.0) -> Iterator[DiscoveryEvent]`, `candidate_addresses(scope, host) -> list[tuple[str, NodeKind]]`, `ConsentRefused`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_node_discovery.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Scanning: what it may touch, and how it reports what it finds.

Permission is this feature's privacy promise, so it is tested rather than
trusted. Every test records which addresses were attempted and asserts the
exact set.
"""

import pytest

from src.nodes.discovery import DiscoveryEvent, candidate_addresses, discover
from src.schemas.node import NodeKind, ScanScope


class Recorder:
    """A fetcher that records every URL asked for and answers as Ollama."""

    def __init__(self, answering: set[str] | None = None):
        self.asked: list[str] = []
        self.answering = answering if answering is not None else {"127.0.0.1:11434"}

    def __call__(self, url: str, timeout: float = 0.0) -> dict:
        self.asked.append(url)
        if not any(host in url for host in self.answering):
            raise OSError("connection refused")
        if url.endswith("/api/version"):
            return {"version": "0.5.4"}
        if url.endswith("/api/tags"):
            return {"models": [{"name": "llama3.1:8b", "size": 1,
                                "details": {"family": "llama"}}]}
        if url.endswith("/api/ps"):
            return {"models": []}
        return {"model_info": {"llama.context_length": 8192}, "capabilities": []}

    def hosts(self) -> set[str]:
        """Every distinct host:port attempted."""
        return {u.split("//", 1)[1].split("/", 1)[0] for u in self.asked}


class TestPermissionIsHonoured:
    def test_none_opens_nothing_at_all(self):
        fetch = Recorder()
        events = list(discover(ScanScope.NONE, fetch=fetch))
        assert fetch.asked == [], "NONE must not open a single connection"
        assert events[-1].finished

    def test_this_machine_touches_only_loopback(self):
        fetch = Recorder()
        list(discover(ScanScope.THIS_MACHINE, fetch=fetch))
        for host in fetch.hosts():
            assert host.startswith("127.0.0.1"), f"left the machine: {host}"

    def test_this_machine_tries_both_known_ports(self):
        fetch = Recorder()
        list(discover(ScanScope.THIS_MACHINE, fetch=fetch))
        assert fetch.hosts() == {"127.0.0.1:11434", "127.0.0.1:8081"}

    def test_named_host_touches_only_that_host(self):
        fetch = Recorder(answering={"10.0.0.9:11434"})
        list(discover(ScanScope.NAMED_HOST, "10.0.0.9", fetch=fetch))
        for host in fetch.hosts():
            assert host.startswith("10.0.0.9"), f"touched something else: {host}"

    def test_a_named_host_with_a_port_is_honoured_exactly(self):
        fetch = Recorder(answering={"10.0.0.9:9999"})
        list(discover(ScanScope.NAMED_HOST, "10.0.0.9:9999", fetch=fetch))
        assert fetch.hosts() == {"10.0.0.9:9999"}


class TestCandidates:
    def test_none_has_no_candidates(self):
        assert candidate_addresses(ScanScope.NONE, "") == []

    def test_this_machine_is_loopback_on_both_ports(self):
        assert candidate_addresses(ScanScope.THIS_MACHINE, "") == [
            ("http://127.0.0.1:11434", NodeKind.OLLAMA),
            ("http://127.0.0.1:8081", NodeKind.LLAMACPP),
        ]

    def test_a_bare_named_host_tries_both_ports(self):
        assert candidate_addresses(ScanScope.NAMED_HOST, "box") == [
            ("http://box:11434", NodeKind.OLLAMA),
            ("http://box:8081", NodeKind.LLAMACPP),
        ]

    def test_a_full_url_is_taken_as_given(self):
        assert candidate_addresses(ScanScope.NAMED_HOST, "http://box:1234") == [
            ("http://box:1234", NodeKind.OLLAMA),
            ("http://box:1234", NodeKind.LLAMACPP),
        ]


class TestTheStream:
    def test_events_arrive_before_the_scan_finishes(self):
        fetch = Recorder()
        stream = discover(ScanScope.THIS_MACHINE, fetch=fetch)
        first = next(stream)
        assert isinstance(first, DiscoveryEvent)
        assert not first.finished, "the first event must not be the last"

    def test_each_event_carries_a_human_message(self):
        fetch = Recorder()
        for event in discover(ScanScope.THIS_MACHINE, fetch=fetch):
            assert event.message, f"stage {event.stage} produced no message"
            assert "provenance" not in event.message.lower()
            assert "endpoint" not in event.message.lower()

    def test_a_found_computer_is_carried_on_the_event(self):
        fetch = Recorder()
        events = list(discover(ScanScope.THIS_MACHINE, fetch=fetch))
        found = [e for e in events if e.node is not None]
        assert found, "nothing was reported despite a server answering"
        assert found[-1].node.reachable
        assert found[-1].node.models

    def test_the_last_event_is_marked_finished(self):
        fetch = Recorder()
        events = list(discover(ScanScope.THIS_MACHINE, fetch=fetch))
        assert events[-1].finished
        assert sum(1 for e in events if e.finished) == 1

    def test_a_stage_failure_keeps_what_was_already_found(self):
        class HalfBroken(Recorder):
            def __call__(self, url, timeout=0.0):
                if url.endswith("/api/tags"):
                    self.asked.append(url)
                    raise OSError("boom")
                return super().__call__(url, timeout)

        fetch = HalfBroken()
        events = list(discover(ScanScope.THIS_MACHINE, fetch=fetch))
        nodes = [e.node for e in events if e.node is not None]
        assert nodes, "a listing failure discarded the whole scan"
        assert nodes[-1].reachable, "the server answered and must still be recorded"

    def test_nothing_found_still_finishes_cleanly(self):
        fetch = Recorder(answering=set())
        events = list(discover(ScanScope.THIS_MACHINE, fetch=fetch))
        assert events[-1].finished
        assert all(e.node is None for e in events)
        assert "didn't find" in events[-1].message.lower()
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `.venv/bin/python -m pytest tests/test_node_discovery.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.nodes.discovery'`

- [ ] **Step 3: Write the implementation**

```python
# src/nodes/discovery.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Finding inference computers, with permission, one finding at a time.

**Discovery is a stream, not a return value.** ``discover()`` yields an event
each time it learns something, so a person watches it happen instead of
staring at a frozen window. The command line renders each event as a line; the
desktop fills a card row by row. Same service, two renderers.

It also means a stage that fails costs one row rather than the whole scan: a
server that answers but cannot list its models is still worth recording, and
the event carrying it says so plainly.

**Permission is checked before anything opens.** ``ScanScope.NONE`` opens no
connection at all, and each rung reaches exactly as far as it was granted.
That is the privacy promise this feature makes, and it is enforced here rather
than in the interface, so no caller can skip it.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterator, Optional

from src.nodes.backends import (
    PORTS,
    Fetcher,
    Poster,
    http_get_json,
    http_post_json,
    probe_llamacpp,
    probe_ollama,
)
from src.schemas.node import (
    InferenceNode,
    NodeKind,
    Provenance,
    ScanScope,
    slugify,
)


class ConsentRefused(Exception):
    """Raised when a scan is attempted beyond what was permitted."""


@dataclass
class DiscoveryEvent:
    """One thing learned, as it is learned."""

    stage: str
    message: str
    ok: bool = True
    node: Optional[InferenceNode] = None
    progress: tuple[int, int] = (0, 0)
    finished: bool = False


def _normalise(host: str) -> str:
    """Turn what a person typed into a base URL, without inventing a port."""
    host = host.strip()
    if host.startswith("http://") or host.startswith("https://"):
        return host.rstrip("/")
    return f"http://{host}"


def candidate_addresses(scope: ScanScope, host: str) -> list[tuple[str, NodeKind]]:
    """Every address this permission allows, and which backend to try there.

    A bare host is tried on both known ports. A host that already names a port,
    or a full URL, is taken exactly as given and tried as both backends — the
    one that answers wins.
    """
    if scope is ScanScope.NONE:
        return []
    if scope is ScanScope.THIS_MACHINE:
        return [(f"http://127.0.0.1:{port}", kind) for port, kind in PORTS]
    if scope is ScanScope.NAMED_HOST:
        base = _normalise(host)
        tail = base.split("//", 1)[1]
        if ":" in tail:
            return [(base, kind) for _port, kind in PORTS]
        return [(f"{base}:{port}", kind) for port, kind in PORTS]
    raise ConsentRefused(f"{scope.value} is not scannable by this function")


def _describe(node: InferenceNode) -> list[tuple[str, str]]:
    """The human lines for what one probe established, in the order learned."""
    lines = [("backend", f"It's {node.kind.value} {node.backend_version}".rstrip())]
    if node.models:
        biggest = max(node.models, key=lambda m: m.size_bytes)
        lines.append(("models", f"{len(node.models)} models available"))
        lines.append(("biggest", f"Biggest is {biggest.name}"))
        if node.max_context_length:
            from src.nodes.summary import human_words

            lines.append(
                ("context", f"Longest input — {human_words(node.max_context_length)}")
            )
    else:
        lines.append(("models", "Couldn't list the models"))
    if node.host.gpu_present is True:
        from src.nodes.summary import human_bytes

        lines.append(
            ("hardware", f"Graphics card in use — {human_bytes(node.host.vram_bytes)}")
        )
    elif node.host.gpu_present is False:
        lines.append(("hardware", "No graphics card doing the work"))
    else:
        lines.append(("hardware", "Couldn't tell whether there's a graphics card"))
    return lines


def discover(
    scope: ScanScope,
    host: str = "",
    *,
    fetch: Fetcher = http_get_json,
    post: Poster = http_post_json,
    connect_timeout: float = 2.0,
) -> Iterator[DiscoveryEvent]:
    """Look for inference computers, yielding each finding as it is made.

    Opens nothing when the permission is ``NONE``. Every other rung reaches
    exactly as far as it was granted and no further.
    """
    if scope is ScanScope.NONE:
        yield DiscoveryEvent(
            stage="permission",
            message="Not looking — nothing was permitted.",
            finished=True,
        )
        return

    candidates = candidate_addresses(scope, host)
    total = len(candidates)
    found = 0
    seen_urls: set[str] = set()

    for index, (base_url, kind) in enumerate(candidates, start=1):
        if base_url in seen_urls:
            continue
        port = base_url.rsplit(":", 1)[-1]
        yield DiscoveryEvent(
            stage="trying",
            message=f"Looking on port {port}...",
            progress=(index, total),
        )

        result = (
            probe_ollama(base_url, fetch, post)
            if kind is NodeKind.OLLAMA
            else probe_llamacpp(base_url, fetch)
        )
        if not result.ok:
            continue

        seen_urls.add(base_url)
        found += 1
        node = InferenceNode(
            node_id=slugify(f"{result.kind.value}-{port}"),
            label=f"{result.kind.value} on {'this computer' if '127.0.0.1' in base_url else host}".strip(),
            kind=result.kind,
            url=base_url,
            is_local="127.0.0.1" in base_url,
            reachable=True,
            backend_version=result.backend_version,
            models=result.models,
            host=result.host,
            last_probed_at=datetime.now(timezone.utc),
            provenance={
                "backend_version": Provenance.DETECTED,
                "models": Provenance.DETECTED,
                "host.gpu_present": Provenance.DETECTED,
                "host.vram_bytes": Provenance.DETECTED,
                "url": Provenance.DETECTED,
            },
        )

        yield DiscoveryEvent(
            stage="reachable",
            message=f"Something's listening on port {port}",
            node=node,
            progress=(index, total),
        )
        for stage, message in _describe(node):
            yield DiscoveryEvent(
                stage=stage, message=message, node=node, progress=(index, total)
            )

    if found:
        noun = "computer" if found == 1 else "computers"
        yield DiscoveryEvent(
            stage="done", message=f"Found {found} {noun}.", finished=True
        )
    else:
        yield DiscoveryEvent(
            stage="done",
            message="Didn't find anything answering. You can type it in instead.",
            ok=False,
            finished=True,
        )
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `.venv/bin/python -m pytest tests/test_node_discovery.py -q`
Expected: PASS, 15 tests.

- [ ] **Step 5: Prove the permission guard actually guards**

A guard nobody has watched fail is not a guard. Temporarily make `discover` ignore its scope:

```bash
# In src/nodes/discovery.py, comment out the `if scope is ScanScope.NONE:` block.
.venv/bin/python -m pytest tests/test_node_discovery.py -q -k none_opens_nothing
# Expected: FAIL — "NONE must not open a single connection"
# Then restore the block and re-run: PASS
```

- [ ] **Step 6: Commit**

```bash
git add src/nodes/discovery.py tests/test_node_discovery.py
git commit -m "feat: consent-gated discovery that streams each finding"
```

---

