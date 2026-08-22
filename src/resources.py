# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Finding the files that ship with the application.

The problem this solves is small and entirely a packaging one. Every document
in this repository tells an operator to run something like:

    fukasawa workflow validate examples/workflows/substack-publication/observed-workflow.yaml

That works from a source checkout, because `examples/` is right there. From the
PyInstaller binary it did not, even though `packaging/fukasawa.spec` bundles all
39 example files: PyInstaller unpacks its data into a temporary directory named
by ``sys._MEIPASS``, and nothing resolved paths against it. The binary carried
the pilot and no one could open it.

Two ways to be wrong here, and this module avoids both:

* **Silently preferring the bundled copy.** If the operator has their own
  `examples/observed-workflow.yaml` in the working directory, that is the file
  they mean. The working directory always wins.
* **Reaching into the bundle for paths that are not ours.** Only a relative
  path that does not exist locally is looked up, and only against the bundle
  root. An absolute path is returned untouched.

When not frozen this is a no-op — `bundle_root()` returns None and `resolve()`
hands back exactly what it was given, so a source checkout behaves as it always
has and no test needs a frozen interpreter to be meaningful.
"""

import sys
from pathlib import Path
from typing import Optional


def bundle_root() -> Optional[Path]:
    """Where PyInstaller unpacked our data files, or None when not frozen.

    ``sys.frozen`` and ``sys._MEIPASS`` are both set by the PyInstaller
    bootloader. Both are checked because ``_MEIPASS`` is the one that actually
    matters and ``frozen`` is the documented signal; a build that set only one
    of them is a build we should not guess about.
    """
    if not getattr(sys, "frozen", False):
        return None
    meipass = getattr(sys, "_MEIPASS", None)
    return Path(meipass) if meipass else None


def resolve(path: str | Path) -> Path:
    """The file the operator meant, preferring their working directory.

    Order:

    1. The path as given. If it exists, that is the answer — always, including
       when a bundled file of the same name exists.
    2. When frozen, the same *relative* path inside the bundle.
    3. Otherwise the path as given, unchanged, so the caller reports "no such
       file" naming what the operator actually typed rather than a temporary
       directory they have never heard of.
    """
    candidate = Path(path)
    if candidate.exists():
        return candidate
    if candidate.is_absolute():
        return candidate
    root = bundle_root()
    if root is not None:
        bundled = root / candidate
        if bundled.exists():
            return bundled
    return candidate


def bundled_examples() -> Optional[Path]:
    """The bundled `examples/` directory, or None if unavailable.

    Used by the CLI to tell a binary user where the pilot actually is, since
    the answer differs between a checkout and a binary and guessing wrong
    wastes their time.
    """
    root = bundle_root()
    if root is None:
        local = Path("examples")
        return local if local.is_dir() else None
    bundled = root / "examples"
    return bundled if bundled.is_dir() else None
