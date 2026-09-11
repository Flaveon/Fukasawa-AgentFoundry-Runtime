# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Design §3.1.1 and §3.1.2 as checks, shared by every front end's tests.

One copy, so the CLI and the desktop are held to the same list and not to two
lists that drift. These lived in ``tests/test_node_cli.py`` until the desktop
tests imported them from there, which loaded that test module under a second
name -- and, under a bare ``pytest``, did not import at all. Moved here, as the
phase-10a handoff prescribed, when that turned out to have kept CI red.
"""

import re

#: The words design §3.1.1 forbids, in its own order. Every one of them
#: characterises the reader's hardware instead of reporting a figure, and the
#: whole point of the rule is that whether five words a second is slow depends
#: on work this program knows nothing about.
#:
#: This is the spec's list and nothing else. "weak" used to sit here and does
#: not appear in §3.1.1; a test that invents its own rules stops being
#: evidence about the rules that exist.
JUDGEMENT = [
    "slow", "fast", "good", "poor", "powerful", "limited", "adequate",
    "sufficient", "plenty", "only",
]

#: The phrases design §3.1.2 forbids. Each asserts an ownership nobody
#: established: the person reading may be setting a machine up for somebody
#: else, and this runtime already names a step's performer in its own data.
#: Singular entries catch their plurals as substrings.
OWNERSHIP = [
    "stays with you", "your workflow", "your model", "off your hands",
    "my network",
]

#: Copy the spec writes out and approves, which nonetheless contains a word on
#: the JUDGEMENT list. These are removed from the output before the words are
#: hunted for, and nothing else is.
#:
#: WHY THIS EXISTS, so the next reader does not delete it as clutter: §3.1.1
#: forbids "only" as a verdict about hardware — "8 GB is only..." — and the
#: same goes for "plenty" and "limited". It does not forbid the ordinary
#: adverb of restriction, and the spec's own approved copy uses it, twice, to
#: promise a person that nothing will be examined beyond what they permitted.
#: A plain `word in output` check would fail on the exact sentences the spec
#: endorses, and the two ways out of that — quietly dropping "only" from the
#: list, or quietly rewriting approved copy until the test goes green — both
#: throw away the rule instead of enforcing it.
#:
#: So: allow the endorsed phrase, then match what is left on word boundaries.
#: Boundaries matter on their own. "fastest measured speed" (§3.6) is a
#: comparison between figures, not a verdict on any of them, and \bfast\b
#: leaves it alone while still catching "that will be fast".
ENDORSED = [
    'only checks this computer',   # §3.2, the empty Environment tab
    'i check that one only',       # §3.3, the second rung of the permission
]


def judgements_in(output: str) -> list[str]:
    """Every forbidden verdict in this output, ignoring copy the spec endorses."""
    remaining = output.lower()
    for phrase in ENDORSED:
        remaining = remaining.replace(phrase, " ")
    return [w for w in JUDGEMENT if re.search(rf"\b{w}\b", remaining)]


#: Design §3.1's vocabulary rule: words of the implementation that never
#: appear in a sentence shown to a person.
JARGON = ["endpoint", "provenance", "capability", "capabilities", "vram"]


def jargon_in(output: str) -> list[str]:
    """Implementation words used as prose (§3.1), with their typed exceptions.

    Two words are allowed only as something a person types: ``node`` as the
    command noun in ``fukasawa node …``, and ``scope`` as the ``--scope``
    flag. Anywhere else they are the implementation showing through. Every
    other word on ``JARGON`` is simply absent.
    """
    lowered = output.lower()
    found = [w for w in JARGON if re.search(rf"\b{w}\b", lowered)]
    if re.search(r"(?<!fukasawa )\bnode\b", lowered):
        found.append("node")
    if re.search(r"(?<!--)\bscope\b", lowered):
        found.append("scope")
    return found


def ownership_in(output: str) -> list[str]:
    """Every phrase in this output that claims someone owns something."""
    lowered = output.lower()
    return [p for p in OWNERSHIP if p in lowered]
