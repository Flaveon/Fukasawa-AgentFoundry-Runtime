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
