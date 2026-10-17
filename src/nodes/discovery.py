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

from dataclasses import dataclass
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
    """Turn what a person typed into a base URL, without inventing a port.

    Reading an address twice must give the same answer as reading it once.
    The store matches records by address, and an address is read when it is
    saved and again when a look is aimed at it; a trailing slash that was
    kept on the first reading and dropped on the second once filed a
    finding under a second record, and left the first reading "not
    answering". So the scheme is recognised whatever its capitals, and a
    trailing slash is dropped whether or not a scheme was typed.
    """
    host = host.strip()
    scheme, sep, rest = host.partition("://")
    if sep and scheme.lower() in ("http", "https"):
        return f"{scheme.lower()}://{rest}".rstrip("/")
    return f"http://{host}".rstrip("/")


def _kind_words(kind: NodeKind) -> str:
    """What a program is called on screen. Imported late, as `human_words` is."""
    from src.nodes.summary import KIND_WORDS

    return KIND_WORDS[kind]


def _split_authority(base: str) -> tuple[str, str, str, str]:
    """Split a ``_normalise``d URL into ``(scheme, "user:pw@" or "", host[:port], the rest)``.

    "The rest" is a path, a query, a fragment, or any mix of the three,
    taken whole -- nothing here needs to look inside it, only to know where
    the host part ends. That end is the first ``/``, ``?`` or ``#``,
    whichever comes first; a ``#`` used to be missed, so a fragment with no
    ``/`` or ``?`` (``http://box#frag``) read as part of the host.

    Userinfo (``user:pw@host``) is split off *before* that: its own colon is
    not a port, and reading it as one sent a look at ``http://user:pw@box``
    to port 80 while naming no port at all. Splitting it off here --
    `rpartition` finds the *last* ``@``, so userinfo may itself contain one
    -- rather than refusing it keeps whatever a person typed working end to
    end; nothing downstream needs to inspect it, only put it back.

    Written by hand rather than with ``urllib.parse``: this module is one of
    the two the whole-network-access guard (``tests/test_hardening.py``)
    allows to import anything under ``urllib`` at all, and a parsing-only
    submodule is not the exception that rule exists to catch.
    """
    scheme, _, after_scheme = base.partition("://")
    userinfo, sep, host_and_rest = after_scheme.rpartition("@")
    prefix = f"{userinfo}{sep}"  # "" when there was no "@"
    end = len(host_and_rest)
    for mark in ("/", "?", "#"):
        found = host_and_rest.find(mark)
        if found != -1:
            end = min(end, found)
    return scheme, prefix, host_and_rest[:end], host_and_rest[end:]


def _names_a_port(base: str) -> bool:
    """Whether a base URL from ``_normalise`` already says which port to use.

    Only the host part is read, never userinfo, a path, a query or a
    fragment. A bracketed IPv6 address is full of colons and names a port
    only after its closing bracket; an *unbracketed* one (a bare ``::1``) is
    full of colons with no brackets at all, which is not "host:port" either
    -- it names no port, the same as a plain host, and needs bracketing
    before a port can be appended (``address_for``). Either form naming an
    *empty* port (``box:``, ``[::1]:``) is read the same as naming none:
    reading one back a second time must not keep a colon with nothing after
    it, the same invariant ``_normalise`` states for a trailing slash.
    """
    _scheme, _prefix, netloc, _rest = _split_authority(base)
    if netloc.startswith("["):
        return "]:" in netloc and not netloc.endswith("]:")
    if netloc.count(":") > 1:
        return False
    return ":" in netloc and not netloc.endswith(":")


def address_for(host: str, kind: NodeKind) -> str:
    """The address a typed-in computer is recorded at, without contacting it.

    What a person typed is read the same way a named-computer scan reads it: a
    full URL, or a host that already names a port, is kept exactly as given. A
    bare host gets the port that kind of program listens on by default, since
    nothing has been asked which port it actually uses.

    Reading an address twice must give what reading it once gave (the same
    invariant ``_normalise`` states). The port used to be appended to the
    *whole string*, which is right only when there is nothing after the host:
    ``http://box/v1`` became ``http://box/v1:11434`` -- a port on
    the path, not the host, so the look it produced still went to port 80 --
    and reading that result again appended a second port the same way (m2).
    The port is placed into the host part ``_split_authority`` finds instead.
    """
    base = _normalise(host)
    if _names_a_port(base):
        return base
    port = next(p for p, k in PORTS if k is kind)
    scheme, prefix, netloc, rest = _split_authority(base)
    if netloc.endswith(":"):
        # An empty port names none; drop it rather than keep ":port" twice.
        netloc = netloc[:-1]
    if not netloc.startswith("[") and netloc.count(":") >= 1:
        # A bare (unbracketed) IPv6 host: bracket it so the port being
        # appended is not read as one more field of the address itself.
        netloc = f"[{netloc}]"
    return f"{scheme}://{prefix}{netloc}:{port}{rest}"


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
        if _names_a_port(base):
            return [(base, kind) for _port, kind in PORTS]
        return [(f"{base}:{port}", kind) for port, kind in PORTS]
    raise ConsentRefused(f"{scope.value} is not scannable by this function")


def _describe(node: InferenceNode) -> list[tuple[str, str]]:
    """The human lines for what one probe established, in the order learned."""
    lines = [("backend", f"It's {_kind_words(node.kind)} {node.backend_version}".rstrip())]
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

    This early return and ``candidate_addresses()``'s own ``NONE`` guard are
    deliberate defence in depth: either one alone stops every socket from
    opening. ``test_none_yields_a_permission_stage_event`` pins this guard's
    specific behaviour (a ``permission``-stage event), since a test that only
    checks "nothing was fetched" cannot tell the two guards apart.
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
        # The id is derived from host:port, not port alone -- two machines
        # both running the default port (e.g. two Ollama boxes on :11434)
        # must not collide by construction. See NodeStore.upsert for the
        # second half of collision handling: an id already taken by a
        # *different* URL gets a numeric suffix rather than overwriting.
        netloc = base_url.split("//", 1)[1]
        node = InferenceNode(
            node_id=slugify(f"{result.kind.value}-{netloc}"),
            # The program's own name ("Ollama", not "ollama"): this label is
            # the heading of a card a person reads (§3.5), not an identifier.
            label=f"{_kind_words(result.kind)} on {'this computer' if '127.0.0.1' in base_url else host}".strip(),
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
