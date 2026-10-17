# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Session-wide test environment.

**Colour is off for every test.** The CLI's console is built when `src.cli` is
imported, and Rich reads ``FORCE_COLOR`` at that moment. With it set, the
console wraps text in escape codes and every assertion on plain words fails —
65 of them did — though nothing about the program is wrong. The assertions say
what the operator reads; colour is presentation. So the switch is turned off
here, before any test module imports the CLI, rather than loosening what the
tests expect.

This file runs before the test modules are collected, which is why it works:
moving the line into a fixture would be too late for the module-level console.
"""

import os

os.environ.pop("FORCE_COLOR", None)
