# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""The desktop's half of telling Fukasawa what computers it can use.

Tk-free by rule (ADR-007 §1): dataclasses in, dataclasses out, no widget
imports, no printing. The view renders what these return and decides nothing.

Scanning is exposed as a **generator of view-shaped events**, because the
design requires findings to appear one at a time (§3.4). The view runs it on
the phase-7 worker thread and pushes each event onto the queue the tab already
drains — no new threading machinery.

**Both network verbs are injectable.** ``scan()`` forwards ``fetch`` *and*
``post`` to discovery, because probing an Ollama server is mostly POSTs: one
``/api/show`` per model it lists. A service that forwarded only ``fetch``
would leave ``post`` defaulting to the real network, so its own tests would
send live traffic while asserting that none was sent — the exact blind spot
this feature's privacy promise cannot afford.

Every string returned here is read by a person, so design §3.1.1 and §3.1.2
govern them: report a figure with its unit and never characterise anybody's
hardware, and say what happens to the *step* rather than assuming who owns it.

**Nothing here raises for a stored file that cannot be used.** ``nodes.yaml``
is hand-editable by design (``src/schemas/node.py``), so a file that does not
parse is an expected outcome rather than an exotic one. It comes back as a
refusal, on the rule the package already states in ``workflow.py``: a
traceback is not an error message, and this is the only screen from which
somebody could correct the file.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

import yaml

from src.gui.services.workflow import Outcome
from src.nodes.discovery import discover
from src.nodes.store import NodeStore
from src.nodes.summary import (
    human_bytes,
    human_rate,
    human_words,
    source_label,
    summarise,
)
from src.schemas.node import (
    InferenceNode,
    NodeKind,
    Provenance,
    ScanConsent,
    ScanScope,
    slugify,
)

#: Fields a person may edit from the tab. Deliberately short: a measured figure
#: is not on it, because typing over a reading would flip its source to "you
#: told me" — an honest label on an invented number.
EDITABLE = ("label", "url", "kind")

#: The stages on which ``scan()`` stops without a finding. On one of these the
#: message *is* the answer, and the view shows it in place of findings rather
#: than as one more row in the stream.
#:
#: Written down because the obvious test — ``ok=False and finished`` — is
#: wrong, and identifies the opposite of a refusal as one. ``discover`` ends a
#: scan that ran to completion, opened every permitted address and found
#: nothing with exactly that shape ("Didn't find anything answering. You can
#: type it in instead."), which is the most common outcome of a first scan.
#: A view built on the shape cannot tell "we looked and found nothing" from
#: "we did not look", and would put the first in a refusal treatment.
#:
#: ``store`` is on the list although it is not a refusal on doctrine: the file
#: cannot be used, which stops the scan the same way and needs the same
#: treatment. The other three decline before anything is opened.
REFUSAL_STAGES = frozenset({"permission", "not-built", "address", "store"})

#: The answer to a whole-network sweep, which the design names (§3.3) and this
#: phase does not build. Written once so the two callers cannot drift apart.
#:
#: The words matter. The CLI settled the same question at `node scan` and chose
#: to say the part does not exist rather than that anybody is being refused:
#: nothing here is declining a request on doctrine, the sweep simply has not
#: been written. Both sentences after it name a route that does work, because a
#: dead end with no exit is how a person ends up stuck on this screen.
NOT_BUILT = (
    "Looking at every computer on this network is not built yet. "
    "Name one computer's address to look at that one, or type a computer "
    "in by hand."
)


@dataclass
class FieldView:
    """One row of a computer's card."""

    name: str
    label: str
    value: str
    source: str
    editable: bool = False


@dataclass
class NodeRowView:
    """One computer, flattened for display."""

    node_id: str
    label: str
    url: str
    fields: list[FieldView] = field(default_factory=list)


@dataclass
class NodeListResult(Outcome):
    """Every computer, plus the panel that says what follows."""

    rows: list[NodeRowView] = field(default_factory=list)
    summary_rows: list[tuple[str, str]] = field(default_factory=list)
    consequence: str = ""


@dataclass
class ScanEventView:
    """One discovery event, ready to render.

    ``node_id`` says which computer this row is about, and is empty on the
    rows that are about no computer in particular — an attempt, or the closing
    line. §3.4 has the desktop filling a card row by row, and a scan that
    finds two computers yields one interleaved stream, so without this the
    only key is the order rows arrived in. Order is not a key: a stage that
    fails costs one row rather than the whole scan, so the number of rows per
    computer is not fixed.

    It is the id ``discover`` derived from the address, which is what groups
    the rows of one scan. It is not promised to be the id the computer ends
    up stored under: ``NodeStore.upsert`` keeps the id an already-recorded
    address is filed under, and gives a newcomer whose id is taken a numeric
    suffix. Read the stored id back from ``list_nodes`` once the scan closes.
    """

    stage: str
    message: str
    ok: bool = True
    finished: bool = False
    done: int = 0
    total: int = 0
    node_id: str = ""


#: What every entry point puts in ``Outcome.summary`` when the stored file
#: cannot be used. One string, so the view can treat the case uniformly and
#: the six call sites cannot drift into six different words for it.
UNUSABLE_FILE = "Cannot use what is stored"

#: What both write paths say when a name or an address is blank. Shared,
#: because `add_node` refused these from the start while `update_field` wrote
#: them, and clearing a text entry on the §3.5 card is the likelier of the two
#: routes to it.
NEEDS_BOTH = "A computer needs a name and an address."


def _store(store: Optional[NodeStore]) -> NodeStore:
    """Use the store given, else the configured one."""
    return store or NodeStore()


def _unusable(path: Path, exc: Exception) -> str:
    """Say what is wrong with the stored file, and name a way out of it.

    Three failures are expected here and are told apart, because they call for
    different repairs: the file could not be opened at all, it is not YAML, or
    it parses but is not a computer. ``NodeStore.load`` already phrases the
    third one and names the path, so it is passed through as written.
    """
    if isinstance(exc, yaml.YAMLError):
        detail = f"{path} is not valid YAML: {exc}"
    elif isinstance(exc, OSError):
        detail = f"{path} could not be opened: {exc}"
    else:
        detail = str(exc)
    return (
        f"{detail}\n"
        "Correct that file, or move it aside and record the computers again."
    )


def _row(node: InferenceNode) -> NodeRowView:
    """Flatten one computer into display rows with plain-language sources."""
    return NodeRowView(
        node_id=node.node_id,
        label=node.label,
        url=node.url,
        fields=[
            FieldView("label", "Call it", node.label,
                      source_label(node.source_of("label")), editable=True),
            FieldView("url", "Address", node.url,
                      source_label(node.source_of("url")), editable=True),
            FieldView("models", "Models it can run", str(len(node.models)),
                      source_label(node.source_of("models"))),
            FieldView("context", "Longest input",
                      human_words(node.max_context_length),
                      source_label(node.source_of("models"))),
            FieldView("speed", "Speed", human_rate(node.host.tokens_per_second),
                      source_label(node.source_of("host.tokens_per_second"))),
            FieldView("gpu", "Graphics card", human_bytes(node.host.vram_bytes),
                      source_label(node.source_of("host.vram_bytes"))),
        ],
    )


def list_nodes(store: Optional[NodeStore] = None) -> NodeListResult:
    """Every computer, and what follows from having them.

    Refuses exactly once: when the stored file cannot be read. Nothing else
    here is a failure — no computers recorded is an ordinary answer, and the
    panel says what still runs without one.
    """
    target = _store(store)
    try:
        nodes, _consent = target.load()
    except (OSError, yaml.YAMLError, ValueError) as exc:
        return NodeListResult(
            ok=False, summary=UNUSABLE_FILE, refusal=_unusable(target.path, exc)
        )
    summary = summarise(nodes)
    return NodeListResult(
        ok=True,
        summary=f"{len(nodes)} computer(s) recorded." if nodes else "None recorded yet.",
        rows=[_row(n) for n in nodes],
        summary_rows=[(r.label, r.value) for r in summary.rows],
        consequence=summary.consequence,
    )


def save_consent(
    scope: ScanScope, actor: str, store: Optional[NodeStore] = None
) -> Outcome:
    """Record how far a scan may reach.

    A whole-network reach is answered rather than written down. The CLI made
    the same call: a permission no scan can act on is read back by every later
    scan and refused again, so the screen would say the reach was granted
    while nothing ever acts on it.
    """
    if scope is ScanScope.LOCAL_NETWORK:
        return Outcome(ok=False, summary="Not built yet", refusal=NOT_BUILT)
    target = _store(store)
    try:
        target.set_consent(ScanConsent.granted(scope, actor))
    except (OSError, yaml.YAMLError, ValueError) as exc:
        return Outcome(ok=False, summary=UNUSABLE_FILE,
                       refusal=_unusable(target.path, exc))
    return Outcome(ok=True, summary="Saved.")


def scan(
    scope: ScanScope,
    host: str = "",
    store: Optional[NodeStore] = None,
    fetch=None,
    post=None,
) -> Iterator[ScanEventView]:
    """Look for computers, yielding each finding, and save what is found.

    ``fetch`` and ``post`` stand in for the two network verbs. Both are
    forwarded when given, so a caller — a test, or a future dry run — can see
    every address either verb reaches. Omitting one silently restores the real
    network for that verb, which is why they travel together.
    """
    target = _store(store)
    if scope is ScanScope.NONE:
        yield ScanEventView(
            stage="permission",
            message="Not looking — nothing was permitted.",
            ok=False,
            finished=True,
        )
        return

    if scope is ScanScope.LOCAL_NETWORK:
        # `candidate_addresses` raises ConsentRefused here, which reaching a
        # view means a crash on a button press. Answer in words instead, and
        # keep the stage distinct from `permission` above: nobody is being
        # refused a reach they were entitled to, the sweep is unwritten.
        yield ScanEventView(
            stage="not-built", message=NOT_BUILT, ok=False, finished=True
        )
        return

    if scope is ScanScope.NAMED_HOST and not host.strip():
        # Without this the candidate list is built from an empty host and the
        # scan reaches for `http://:11434`, which addresses nothing and reads
        # to a person as the scan simply failing.
        yield ScanEventView(
            stage="address",
            message="No address was given. Type the address of the computer "
                    "to look at.",
            ok=False,
            finished=True,
        )
        return

    kwargs = {}
    if fetch is not None:
        kwargs["fetch"] = fetch
    if post is not None:
        kwargs["post"] = post

    found: list[InferenceNode] = []
    for event in discover(scope, host, **kwargs):
        if event.node is not None and event.node not in found:
            found.append(event.node)
        if event.finished and found:
            # Written once per computer, not once per event. `discover`
            # attaches the same node to six events (reachable, then five
            # describing lines) and each `upsert` rewrites the whole file, so
            # the old shape did six full load-and-dump cycles per computer.
            # This is the shape `node scan` already uses in src/cli.py.
            #
            # Done BEFORE the closing event is yielded, so a scan that says it
            # has finished has already recorded what it found.
            try:
                for node in found:
                    target.upsert(node)
            except (OSError, yaml.YAMLError, ValueError) as exc:
                yield ScanEventView(
                    stage="store",
                    message=_unusable(target.path, exc),
                    ok=False,
                    finished=True,
                )
                return
        yield ScanEventView(
            stage=event.stage,
            message=event.message,
            ok=event.ok,
            finished=event.finished,
            done=event.progress[0],
            total=event.progress[1],
            node_id=event.node.node_id if event.node is not None else "",
        )


def add_node(
    label: str, kind: str, url: str, store: Optional[NodeStore] = None
) -> Outcome:
    """Add a computer by hand. Every field is marked as typed."""
    if not label.strip() or not url.strip():
        return Outcome(ok=False, summary="Missing details", refusal=NEEDS_BOTH)
    if kind not in {k.value for k in NodeKind}:
        return Outcome(
            ok=False,
            summary="Unknown kind",
            refusal=f"'{kind}' is not one of: {', '.join(k.value for k in NodeKind)}",
        )
    target = _store(store)
    try:
        target.upsert(InferenceNode(
            node_id=slugify(label), label=label, kind=NodeKind(kind), url=url,
            provenance={
                "label": Provenance.DECLARED,
                "url": Provenance.DECLARED,
                "kind": Provenance.DECLARED,
            },
        ))
    except (OSError, yaml.YAMLError, ValueError) as exc:
        return Outcome(ok=False, summary=UNUSABLE_FILE,
                       refusal=_unusable(target.path, exc))
    return Outcome(ok=True, summary=f"Added {label}.")


def forget_node(node_id: str, store: Optional[NodeStore] = None) -> Outcome:
    """Remove a computer."""
    target = _store(store)
    try:
        removed = target.forget(node_id)
    except (OSError, yaml.YAMLError, ValueError) as exc:
        return Outcome(ok=False, summary=UNUSABLE_FILE,
                       refusal=_unusable(target.path, exc))
    if not removed:
        return Outcome(
            ok=False, summary="Not found",
            refusal=f"Nothing stored called '{node_id}'.",
        )
    return Outcome(ok=True, summary=f"Removed {node_id}.")


def update_field(
    node_id: str, field_name: str, value: str, store: Optional[NodeStore] = None
) -> Outcome:
    """Change one field, marking it as typed by a person."""
    if field_name not in EDITABLE:
        return Outcome(
            ok=False, summary="Not editable",
            refusal=f"'{field_name}' cannot be edited here.",
        )
    target = _store(store)
    try:
        nodes, consent = target.load()
    except (OSError, yaml.YAMLError, ValueError) as exc:
        return Outcome(ok=False, summary=UNUSABLE_FILE,
                       refusal=_unusable(target.path, exc))
    match = next((n for n in nodes if n.node_id == node_id), None)
    if match is None:
        return Outcome(
            ok=False, summary="Not found",
            refusal=f"Nothing stored called '{node_id}'.",
        )
    if field_name == "kind" and value not in {k.value for k in NodeKind}:
        return Outcome(
            ok=False, summary="Unknown kind",
            refusal=f"'{value}' is not one of: {', '.join(k.value for k in NodeKind)}",
        )
    # `InferenceNode.model_config` forbids extra fields but does not validate
    # on assignment, so the `setattr` below runs no check and `save` writes
    # whatever lands. These two guards are that check.
    if field_name in ("label", "url") and not value.strip():
        return Outcome(ok=False, summary="Missing details", refusal=NEEDS_BOTH)
    if field_name == "url":
        # `store.py` states the invariant -- two computers may never share a
        # URL -- but enforces it inside `upsert`, which this path does not go
        # through. Two rows at one address survive until the next scan, which
        # merges into whichever it matches first and leaves the other a stale
        # duplicate nothing will ever refresh.
        clash = next(
            (n for n in nodes if n.url == value and n.node_id != node_id), None
        )
        if clash is not None:
            return Outcome(
                ok=False, summary="Address already recorded",
                refusal=f"'{clash.label}' is already recorded at that address.",
            )
    setattr(match, field_name, NodeKind(value) if field_name == "kind" else value)
    match.provenance[field_name] = Provenance.DECLARED
    try:
        target.save(nodes, consent)
    except OSError as exc:
        return Outcome(ok=False, summary=UNUSABLE_FILE,
                       refusal=_unusable(target.path, exc))
    return Outcome(ok=True, summary="Saved.")
