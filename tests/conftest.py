# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Session-wide test environment.

**Colour is off, and the width fixed, for every test.** The CLI's console is
built when `src.cli` is imported, and Rich picks its colour system then. With it set, the
console wraps text in escape codes and every assertion on plain words fails —
65 of them did — though nothing about the program is wrong. The assertions say
what the operator reads; colour is presentation. So the switch is turned off
here, before any test module imports the CLI, rather than loosening what the
tests expect.

Rich has a family of these switches, not one: ``TTY_COMPATIBLE`` and
``TTY_INTERACTIVE`` force the same escape codes, so they go too. And a narrow
``COLUMNS`` wraps an asserted phrase across two lines (``COLUMNS=30`` failed
15 tests), so the width is pinned at 80 -- Rich's own default, and what CI
sees -- so no expectation moves. A test that wants another width still sets
its own through ``CliRunner(env=...)``, which overrides this.

This file runs before the test modules are collected, which is why it works:
moving the line into a fixture would be too late for the module-level console.
"""

import os

for name in ("FORCE_COLOR", "TTY_COMPATIBLE", "TTY_INTERACTIVE"):
    os.environ.pop(name, None)
os.environ["COLUMNS"] = "80"
os.environ.pop("LINES", None)
