# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Unified entry point for the bundled application.

One executable, two audiences:

* **Double-clicked** (no arguments) it opens the desktop app — the
  non-technical front door.
* **Invoked with arguments** it is the full ``fukasawa`` CLI, so the same
  bundle a colleague double-clicks is also scriptable by a builder.

This module exists so PyInstaller has a single script to analyze. It adds no
behavior of its own beyond the GUI-vs-CLI dispatch.
"""

import sys


def main() -> None:
    """Dispatch to the CLI when given arguments, otherwise launch the GUI."""
    if len(sys.argv) > 1:
        from src.cli import app

        app()
    else:
        from src.gui.app import main as gui_main

        gui_main()


if __name__ == "__main__":
    main()
