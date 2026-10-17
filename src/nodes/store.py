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


def _what(value) -> str:
    """Name what was found where something else belonged, for a person."""
    if value is None:
        return "nothing"
    if isinstance(value, list):
        return "a list"
    return f"the single value {value!r}"


def unusable_message(path: Path, exc: Exception) -> str:
    """Say what is wrong with a stored file, and name a way out of it.

    Shared by the terminal and the desktop, so the two say the same words
    (§3.7). Three failures are told apart, because they call for different
    repairs: the file could not be opened at all, it is not YAML, or it
    parses but is not laid out as this file is. ``NodeStore.load`` already
    phrases the third and names the path, so it is passed through as
    written.
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


def recorded_at(
    nodes: list[InferenceNode], url: str, kind
) -> Optional[InferenceNode]:
    """The computer in ``nodes`` at this address, however either was written.

    Addresses are compared as ``address_for`` reads them, not character for
    character. A record saved by an older build, by hand, or before ``node
    add`` read addresses can hold ``10.0.0.9:11434`` or ``http://10.0.0.9``
    where a look produces ``http://10.0.0.9:11434``; compared as strings, a
    look at it filed the finding as a second computer and the first went on
    reading "not answering". ``kind`` is needed because an address with no
    port means that program's usual one. None when nothing is there.
    """
    matches = _matching_address(nodes, url, kind)
    return matches[0] if matches else None


def _matching_address(
    nodes: list[InferenceNode], url: str, kind
) -> list[InferenceNode]:
    """Every computer in ``nodes`` at this address. Ordinarily at most one.

    ``recorded_at`` is built on this and only ever wants the first; ``upsert``
    needs to know whether there was more than one, which is the store already
    holding the pair ``upsert`` exists to prevent -- see I2.
    """
    # Late, because discovery sits above this module (it imports the network
    # layer) and nothing here should depend on it at import time.
    from src.nodes.discovery import address_for

    wanted = address_for(url, kind)
    return [n for n in nodes if address_for(n.url, n.kind) == wanted]


def duplicate_node_groups(nodes: list[InferenceNode]) -> list[list[InferenceNode]]:
    """Groups of two or more computers that read to the same address.

    Ordinarily empty -- ``upsert`` refuses to create one. A store saved
    before that rule held, or edited by hand, can still carry one in, and a
    person deserves to know before a look at either one tells them the hard
    way (review finding I2). The computers themselves, not just their ids,
    because naming one means something different to each front end -- the
    terminal says the id, the desktop says the label and address, as each
    already does on screen (re-review nit). Each inner list is sorted by id
    so a message built from it reads the same from one run to the next.
    """
    from src.nodes.discovery import address_for

    by_address: dict[str, list[InferenceNode]] = {}
    for n in nodes:
        by_address.setdefault(address_for(n.url, n.kind), []).append(n)
    return [
        sorted(group, key=lambda n: n.node_id)
        for group in by_address.values() if len(group) > 1
    ]


def duplicate_groups(nodes: list[InferenceNode]) -> list[list[str]]:
    """Groups of two or more ids that read to the same address.

    The terminal's view of ``duplicate_node_groups``: just the ids, which is
    what ``fukasawa node forget <id>`` takes.
    """
    return [[n.node_id for n in group] for group in duplicate_node_groups(nodes)]


class AmbiguousAddressError(ValueError):
    """``upsert`` cannot tell which stored computer a write belongs to.

    Raised when more than one already reads to the address being written --
    the pair ``upsert`` exists to prevent, but a store saved before that
    rule held, or edited by hand, can still carry one in (review finding
    I2). Carries the computers themselves, not just a finished sentence, so
    each front end can name them the way it already names a computer on
    screen -- the terminal by id, the desktop by label and address -- rather
    than one message written for only one of them (re-review nit).
    """

    def __init__(self, path: Path, nodes: list[InferenceNode]) -> None:
        self.path = path
        self.nodes = nodes
        ids = ", ".join(sorted(n.node_id for n in nodes))
        super().__init__(
            f"{path}: {ids} are recorded at the same address. A look "
            f"cannot tell which one it means. Remove one with "
            f"`fukasawa node forget <id>`, then try again."
        )


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
        """Everything stored. A missing file is no computers and no permission.

        A file that cannot be used raises ``ValueError`` naming it, whatever
        is wrong with it -- or ``OSError`` / ``yaml.YAMLError`` when it cannot
        be opened or is not YAML. That is the set every caller catches. YAML
        of the wrong shape (a list, a bare word, a computer with nothing
        under it) used to escape as ``AttributeError`` or ``TypeError``
        straight past all of them, through the desktop and every graph run
        (review finding 2); it is checked here, before anything is read out
        of it.
        """
        if not self.path.exists():
            return [], ScanConsent()
        try:
            text = self.path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            # Caught here, before `yaml.safe_load` sees it, so the file is
            # named: left to propagate as-is, `str(exc)` reads "'utf-8' codec
            # can't decode byte 0xff..." with no path in it at all, and
            # `unusable_message`'s fallback branch passes that straight
            # through (m5).
            raise ValueError(f"{self.path} is not UTF-8 text: {exc}") from exc
        raw = yaml.safe_load(text) or {}
        self._check_shape(raw)
        try:
            nodes = [
                InferenceNode.model_validate({**spec, "node_id": node_id})
                for node_id, spec in (raw.get("nodes") or {}).items()
            ]
            consent = ScanConsent.model_validate(raw.get("consent") or {})
        except ValidationError as exc:
            raise ValueError(f"{self.path} does not match the contract — {exc}") from exc
        return nodes, consent

    def _check_shape(self, raw) -> None:
        """Refuse, by name, YAML that is not laid out the way this file is.

        Written for the person who will open the file to fix it: it says
        where the problem is and what belongs there.
        """
        if not isinstance(raw, dict):
            raise ValueError(
                f"{self.path} should start with `consent:` and `nodes:`, and "
                f"it holds {_what(raw)} instead."
            )
        # A misspelled top-level key (`node:` for `nodes:`) is not one of the
        # wrong shapes above -- `raw.get("nodes")` just reads as absent, which
        # loads as "no computers" rather than a refusal, and the next write
        # (through `save()`, which only ever writes what `load()` handed
        # back) erases the ones a person wrote by hand (review finding I3).
        allowed = {"schema_version", "consent", "nodes"}
        # `key=str`: a key that is not even text (an int or `null` key, which
        # YAML allows) must not crash this check by landing next to a string
        # in a plain `sorted()`.
        unknown = sorted((set(raw) - allowed), key=str)
        if unknown:
            # Every key named is backticked, including the allowed ones: a
            # bare "nodes" here is the implementation showing through a
            # sentence a person reads (§3.1), not a key they typed.
            names = ", ".join(f"`{key}`" for key in sorted(allowed))
            raise ValueError(
                f"{self.path}: `{unknown[0]}:` is not one of this file's "
                f"top-level keys ({names}). Check the spelling."
            )
        computers = raw.get("nodes") or {}
        if not isinstance(computers, dict):
            raise ValueError(
                f"{self.path}: under `nodes:` each computer should be its "
                f"name followed by its details, and they are written as "
                f"{_what(computers)}."
            )
        for name, details in computers.items():
            if not isinstance(details, dict):
                raise ValueError(
                    f"{self.path}: '{name}' under `nodes:` should have its "
                    f"details written under it, and it has {_what(details)}."
                )
        consent = raw.get("consent") or {}
        if not isinstance(consent, dict):
            raise ValueError(
                f"{self.path}: `consent:` should have the permission's details "
                f"written under it, and it has {_what(consent)}."
            )

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

        Values a person typed are preserved, and so is the name; values that
        were detected are replaced. Two computers may never share an address
        -- compared as ``address_for`` reads it, not as a string, see
        ``recorded_at`` -- and never silently share an id either: a new id
        already in use gets a numeric suffix (see ``_with_unique_id``).

        Raises ``AmbiguousAddressError`` (a ``ValueError``), carrying the
        computers involved, when *more* than one stored computer already
        reads to this address. That pair should never exist -- this method
        is what stops one forming -- but a store written before this rule
        held, or edited by hand, can still carry it in. With only one
        candidate to refresh, picking it by address was safe; with two, it
        is a guess, and the one review finding I2 reproduces: a look that
        reached the second record updated the first instead and then read
        the second, which had just answered, as silent. Refusing the write
        is the one response here that cannot misattribute anything --
        ``load()``, ``forget()`` and ``node list`` are unaffected, so the
        person can still see both and remove one. A caller processing
        several findings in one pass (``node scan``'s loop, on either front
        end) should catch this per finding and keep going -- one ambiguous
        address must not cost an unrelated one in the same scan.
        """
        nodes, consent = self.load()
        matches = _matching_address(nodes, node.url, node.kind)
        if len(matches) > 1:
            raise AmbiguousAddressError(self.path, matches)
        same = matches[0] if matches else None
        for index, existing in enumerate(nodes):
            if existing is not same:
                continue
            # Everything a person typed wins over anything just detected.
            # Only a top-level field can be copied across by name below --
            # a dotted key (e.g. "host.vram_bytes") records provenance for
            # a nested value, and nothing in the current UI produces one, so
            # it is carried through in the provenance map but skipped in the
            # copy loop rather than looked up as an attribute.
            typed = {
                key: source
                for key, source in existing.provenance.items()
                if source is Provenance.DECLARED
            }
            # The name is kept whatever its source, as design §6.0 says a
            # rescan does: a name saved without one -- as `node scan --label`
            # saved it until review finding 4 -- was renamed back to
            # "Ollama on this computer" by the next look.
            merged = node.model_copy(update={
                "node_id": existing.node_id,
                "label": existing.label,
                "provenance": {**node.provenance, **typed},
            })
            for key in typed:
                # The address is the one exception. The two already name the
                # same place (`recorded_at`), so what the person typed is
                # kept; only its spelling becomes the one the look reached,
                # which is the one the runtime can use. Restored as written,
                # a record left as `http://10.0.0.9` read "answering" while
                # sending every graph to port 80.
                if "." in key or key == "url":
                    continue
                setattr(merged, key, getattr(existing, key))
            # The label's own provenance is not a top-level typed field by
            # name -- it is the one key `_run_scan`'s `--label` sets on
            # `node` itself, not on `existing` -- so the loop above never
            # touches it. Left to the merge above, the incoming DECLARED
            # would win even though the *text* just above is always
            # `existing.label`: a rescan's `--label` over a machine-made
            # name kept the old text and still marked it "you told me"
            # (review finding I1). The label's source follows the label's
            # text, whatever that source is -- including "nobody said".
            merged.provenance.pop("label", None)
            if "label" in existing.provenance:
                merged.provenance["label"] = existing.provenance["label"]
            nodes[index] = merged
            self.save(nodes, consent)
            return merged

        node = self._with_unique_id(node, nodes)
        nodes.append(node)
        self.save(nodes, consent)
        return node

    def _with_unique_id(self, node: InferenceNode, nodes: list[InferenceNode]) -> InferenceNode:
        """Give ``node`` an id nobody in ``nodes`` already holds.

        Discovery derives an id from host:port (see ``src/nodes/discovery.py``),
        so two different computers can independently produce the same one
        before either is stored. A collision reaching here is never the same
        computer -- ``upsert`` already matched on URL above and found none --
        so the newcomer gets a numeric suffix (``-2``, ``-3``, ...) rather
        than silently displacing whoever already holds the id when ``save()``
        writes ``nodes`` as a dict keyed by id.

        The names the runtime already resolves are taken too: the built-in
        endpoints and those in ``model_endpoints.yaml`` beside this file. A
        computer's entry wins over them (design §6), so without this,
        calling a computer "GPU box" replaced a hand-written ``gpu-box`` and
        sent every graph using it to another machine (review finding 3).
        Only a newcomer is renamed -- an id already stored is already in
        somebody's graphs.
        """
        from src.nodes.registry import names_in_use

        taken = {existing.node_id for existing in nodes}
        taken |= names_in_use(self.path.parent / "model_endpoints.yaml")
        if node.node_id not in taken:
            return node
        suffix = 2
        while f"{node.node_id}-{suffix}" in taken:
            suffix += 1
        return node.model_copy(update={"node_id": f"{node.node_id}-{suffix}"})

    def forget(self, node_id: str) -> bool:
        """Remove one computer. False when there was nothing by that name."""
        nodes, consent = self.load()
        remaining = [n for n in nodes if n.node_id != node_id]
        if len(remaining) == len(nodes):
            return False
        self.save(remaining, consent)
        return True

    def mark_silent(self, node_id: str) -> bool:
        """Record that this computer was looked at and did not answer.

        Discovery saves only what answers, so a look that found nothing
        changes no record. That was harmless until the summary panel began
        counting computers nobody has looked at (design §3.6, M5 option C):
        without this, a computer checked and found silent would go on reading
        "not checked yet", and be counted, after it was checked.

        Two facts change: it is not answering, and when that was learned.
        Everything else -- what the person typed, and the last models and
        figures a look did find -- is left as it was. False when nothing is
        stored under that id.

        Named by id rather than by address: the address is exactly what may
        be spelled one way in the record and another in the look, and the
        caller always knows which record it looked at.
        """
        from datetime import datetime, timezone

        nodes, consent = self.load()
        for node in nodes:
            if node.node_id == node_id:
                node.reachable = False
                node.last_probed_at = datetime.now(timezone.utc)
                self.save(nodes, consent)
                return True
        return False

    def set_consent(self, consent: ScanConsent) -> None:
        """Record a new standing permission, leaving the computers alone."""
        nodes, _ = self.load()
        self.save(nodes, consent)
