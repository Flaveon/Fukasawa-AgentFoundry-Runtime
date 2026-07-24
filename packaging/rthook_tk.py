# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""PyInstaller runtime hook: point Tcl/Tk at the bundled script libraries.

Newer Python builds ship Tcl/Tk 9, whose interpreter needs TCL_LIBRARY and
TK_LIBRARY set to the directories holding init.tcl and the Tk scripts. Inside
a frozen app those live under the unpack dir (sys._MEIPASS), so we set the
environment before tkinter initializes. Without this, the bundled GUI aborts
with "Can't find a usable init.tcl".
"""

import os
import sys

_base = getattr(sys, "_MEIPASS", None)
if _base:
    for var, subdir in (("TCL_LIBRARY", "tcl9.0"), ("TK_LIBRARY", "tk9.0")):
        candidate = os.path.join(_base, subdir)
        if os.path.isdir(candidate):
            os.environ[var] = candidate
