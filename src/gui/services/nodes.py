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
"""

from dataclasses import dataclass, field
from typing import Iterator, Optional

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
    """One discovery event, ready to render."""

    stage: str
    message: str
    ok: bool = True
    finished: bool = False
    done: int = 0
    total: int = 0


def _store(store: Optional[NodeStore]) -> NodeStore:
    """Use the store given, else the configured one."""
    return store or NodeStore()


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
    """Every computer, and what follows from having them. Never refuses."""
    nodes, _consent = _store(store).load()
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
    _store(store).set_consent(ScanConsent.granted(scope, actor))
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

    for event in discover(scope, host, **kwargs):
        if event.node is not None:
            target.upsert(event.node)
        yield ScanEventView(
            stage=event.stage,
            message=event.message,
            ok=event.ok,
            finished=event.finished,
            done=event.progress[0],
            total=event.progress[1],
        )


def add_node(
    label: str, kind: str, url: str, store: Optional[NodeStore] = None
) -> Outcome:
    """Add a computer by hand. Every field is marked as typed."""
    if not label.strip() or not url.strip():
        return Outcome(
            ok=False,
            summary="Missing details",
            refusal="A computer needs a name and an address.",
        )
    if kind not in {k.value for k in NodeKind}:
        return Outcome(
            ok=False,
            summary="Unknown kind",
            refusal=f"'{kind}' is not one of: {', '.join(k.value for k in NodeKind)}",
        )
    _store(store).upsert(InferenceNode(
        node_id=slugify(label), label=label, kind=NodeKind(kind), url=url,
        provenance={
            "label": Provenance.DECLARED,
            "url": Provenance.DECLARED,
            "kind": Provenance.DECLARED,
        },
    ))
    return Outcome(ok=True, summary=f"Added {label}.")


def forget_node(node_id: str, store: Optional[NodeStore] = None) -> Outcome:
    """Remove a computer."""
    if not _store(store).forget(node_id):
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
    nodes, consent = target.load()
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
    setattr(match, field_name, NodeKind(value) if field_name == "kind" else value)
    match.provenance[field_name] = Provenance.DECLARED
    target.save(nodes, consent)
    return Outcome(ok=True, summary="Saved.")
