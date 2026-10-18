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

import re
import unicodedata
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

    "The rest" is a path, a query, a fragment, or any mix of the three. The
    authority -- userinfo and host[:port] -- ends where that starts: the
    first ``/``, ``?`` or ``#``, whichever comes first. That boundary is
    found *first*, over the whole post-scheme string, before anything looks
    for an ``@``: userinfo is only ever found *inside* the authority, and
    looking for it over the whole string instead read one out of a path or
    a query that merely happened to contain ``@`` (``http://box/p@x``,
    ``http://box?a=@b``), splitting a real path character off as if it
    were a user name and sending the look that resulted to port 80 -- the
    exact failure finding this boundary first exists to prevent, just one
    character later. A ``#`` with no ``/`` or ``?`` anywhere
    (``http://box#frag``) was missed the same way before it was added here.

    Written by hand rather than with ``urllib.parse``: this module is one of
    the two the whole-network-access guard (``tests/test_hardening.py``)
    allows to import anything under ``urllib`` at all, and a parsing-only
    submodule is not the exception that rule exists to catch.
    """
    scheme, _, after_scheme = base.partition("://")
    end = len(after_scheme)
    for mark in ("/", "?", "#"):
        found = after_scheme.find(mark)
        if found != -1:
            end = min(end, found)
    authority, rest = after_scheme[:end], after_scheme[end:]
    # `rpartition` finds the *last* "@" within the authority alone, so a
    # user name may itself contain one; this is used only to keep an
    # already-stored, pre-policy record readable (`address_for` is still
    # called on every record for comparison) -- `address_problem` refuses
    # any *new* address naming userinfo before it ever reaches here.
    userinfo, sep, netloc = authority.rpartition("@")
    prefix = f"{userinfo}{sep}"  # "" when there was no "@"
    return scheme, prefix, netloc, rest


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


#: Shown wherever a freshly typed address names a user name or password.
#: Never built from the typed value -- the whole point is that the secret
#: must not be echoed back in a message that might be displayed or logged
#: (orchestrator policy, re-review finding 1). ``urllib`` does not even
#: turn "user:pw@host" into Basic auth -- no ``Authorization`` header is
#: ever sent -- so keeping it bought no function and cost a plaintext
#: secret written to ``nodes.yaml``, printed by every listing, and copied
#: into a failed run's ledger note.
USERINFO_REFUSED = (
    "Leave the user name and password out of the address -- it cannot "
    "contain \"@\". Fukasawa cannot send them, and they would be saved in "
    "plain text."
)

#: Shown for an address this program cannot use at all -- not a userinfo
#: refusal, but a port that is not a number, more than one of them, or
#: brackets with something after them it does not recognise. Garbage in
#: is refused rather than guessed at and silently sent somewhere wrong.
MALFORMED_ADDRESS = "That address is not one this program can use. Check it and try again."


#: A URL scheme as RFC 3986 spells one: a letter, then letters, digits,
#: ``+``, ``-`` or ``.``, then a colon.
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*:")

#: The only schemes this program can reach a computer with.
_USABLE_SCHEMES = ("http", "https")


def _folded(text: str) -> str:
    """The text as urllib would read its characters: NFKC-normalised, so a
    fullwidth or small ``＠`` is an ``@``."""
    return unicodedata.normalize("NFKC", text)


def has_userinfo(host: str) -> bool:
    """Whether this address names a user name and/or a password.

    Checked on a freshly typed address before it is saved (``address_problem``
    calls this), and on an address already stored, to refuse *using* a
    record an older build or a hand edit left with one (``NodeStore.load``
    still reads such a record; nothing here stops that). It never raises.
    """
    # Any "@" at all, path and query included. Four review rounds found
    # four different ways a parser of "where the authority ends" could be
    # led to miss one -- a scheme it did not know, text before "://", a
    # later "://", a backslash -- and each fix opened the next. A base
    # address for a computer never needs an "@", so none is accepted and no
    # parse is needed: refusing an odd address costs a retype, missing one
    # leaks a password. Linear in the length of the text.
    return "@" in _folded(host)


def redact_userinfo(url: str) -> str:
    """Hide a user name and password a *stored* address holds, for display.

    Never raises and returns ``url`` unchanged when there is nothing to
    hide. Used wherever a record's address reaches a screen or a log --
    ``node list``, ``node show``, ``model list``, a card, a notice -- so an
    old record naming one is still visible enough to find and fix, without
    the secret itself ever being shown again.
    """
    if not has_userinfo(url):
        return url
    text = _folded(url)
    # Keep only what follows the last "@" -- the host, as a person would
    # recognise it -- and the scheme if one comes before every "@". Nothing
    # between them is shown, wherever a secret might have been put.
    scheme_end = text.find("://")
    is_scheme = -1 < scheme_end < text.find("@") and bool(
        _SCHEME.fullmatch(text[:scheme_end + 1])
    )
    lead = text[:scheme_end + 3] if is_scheme else ""
    return f"{lead}…@{text.rpartition('@')[2]}"

#: Matches userinfo wherever it appears in free text, not only in an
#: address this module already knows is one -- a stored file's own
#: content, or a third-party library's exception message (PyYAML,
#: pydantic), can quote a secret back inside a sentence that is otherwise
#: about something else entirely (final re-review finding 1's residual
#: leak: ``node list`` on a *malformed* file echoed the bad entry's raw
#: value, which could still be a tainted url). The scheme is optional --
#: a YAML parser's own context snippet can truncate it -- and the
#: character classes exclude quotes so a value already inside `'...'` or
#: `"..."` is still found starting just after the quote.
_USERINFO_IN_TEXT = re.compile(r"(?:\w+://)?[^\s/@'\"]+(?::[^\s/@'\"]*)?@")


def scrub_userinfo(text: str) -> str:
    """Replace every ``[scheme://]user[:pw]@`` this text contains with
    ``…@``.

    Unlike ``has_userinfo``/``redact_userinfo``, this does not parse one
    known address -- it sweeps arbitrary text (an error message built from
    a stored file's own content, or a library's exception text) for
    anything shaped like userinfo, because by the time such a message is
    being shown, there is no single field left to read it from. Applied to
    every user-facing message built from file content or a third-party
    exception (``unusable_message``, the endpoint-file warning, and
    anywhere a pydantic or YAML error string reaches a screen).
    """
    return _USERINFO_IN_TEXT.sub("…@", text)


def address_problem(host: str) -> Optional[str]:
    """Why a freshly typed address should be refused, or ``None`` when it
    is fine to use.

    Checked at the point a person is about to save or reach for an address
    -- before it is normalised into a port-bearing one, let alone written
    down -- never on one already stored: a record a hand edit or an older
    build left malformed must still load however it was written
    (``NodeStore.load``); only a *new* one is held to this.

    Two refusals, named separately because they call for different
    corrections: userinfo (``USERINFO_REFUSED`` -- any ``@`` at all, see
    ``has_userinfo``), and a handful of shapes that are not a usable
    address at all -- a scheme other than http or https (``ftp://``,
    ``file://``), a leading ``//``, a scheme with one slash, a non-numeric
    port, more than
    one of them, or something after a bracketed host's ``]`` that is not
    ``:<port>``. The "more than one colon" check is skipped when the host
    has no ``.`` in it: a bare IPv6 host (``::1``) is also full of colons
    with no brackets, and ``address_for`` already brackets that case
    rather than refuses it -- a dotted host with more than one colon
    (``10.0.0.9:11434:1``) is not that, so it is still caught.
    """
    if has_userinfo(host):
        return USERINFO_REFUSED
    typed = host.strip()
    if "://" in typed and typed.partition("://")[0].lower() not in _USABLE_SCHEMES:
        return MALFORMED_ADDRESS
    found = _SCHEME.match(typed)
    if typed.startswith("/") or (
        found and typed[found.end():].startswith("/")
        and not typed[found.end():].startswith("//")
    ):
        return MALFORMED_ADDRESS
    base = _normalise(host)
    _scheme, _prefix, netloc, _rest = _split_authority(base)
    if netloc.startswith("["):
        close = netloc.find("]")
        if close == -1:
            return MALFORMED_ADDRESS
        after = netloc[close + 1:]
        if after and not (after.startswith(":") and after[1:].isdigit()):
            return MALFORMED_ADDRESS
        return None
    if "." in netloc and netloc.count(":") > 1:
        return MALFORMED_ADDRESS
    if ":" in netloc and not netloc.endswith(":"):
        port = netloc.rsplit(":", 1)[1]
        if not port.isdigit():
            return MALFORMED_ADDRESS
    return None


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
