# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
#
# PyInstaller spec for the Fukasawa AgentFoundry Runtime.
# Build from the repo root:  pyinstaller packaging/fukasawa.spec
#
# Produces a single-file executable that opens the desktop app when
# double-clicked and behaves as the full CLI when given arguments.
#
# Cross-platform note: PyInstaller builds for the OS it runs on. This spec
# is portable — run it on Linux for an ELF binary, on Windows for an .exe,
# on macOS for an app bundle. See packaging/README.md.

import glob
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# SPECPATH is injected by PyInstaller as the directory containing this spec.
ROOT = os.path.dirname(SPECPATH)  # noqa: F821 - SPECPATH is a PyInstaller global

# customtkinter ships themes/assets as data files that must travel with the
# binary, or the UI fails to theme at runtime.
datas = collect_data_files("customtkinter")
# Bundle the example brief/graph and config so a fresh user has something to
# validate and build against immediately.
datas += [
    (os.path.join(ROOT, "examples"), "examples"),
    (os.path.join(ROOT, "config"), "config"),
]

# --- Tcl/Tk 9 bundling -------------------------------------------------------
# Python builds that ship Tcl/Tk 9 keep the shared libs and script dirs next
# to the base interpreter; PyInstaller's stock tkinter hook does not yet find
# them. Discover them from sys.base_prefix (version-agnostic) and bundle both
# the .so files (binaries) and the script directories (datas). rthook_tk.py
# then points TCL_LIBRARY/TK_LIBRARY at the bundled scripts at launch.
_libdir = os.path.join(sys.base_prefix, "lib")
tk_binaries = [
    (p, ".")
    for pattern in ("libtcl9*.so", "libtk9*.so")
    for p in glob.glob(os.path.join(_libdir, pattern))
]
for _scriptdir in ("tcl9.0", "tk9.0", "tcl9"):
    _full = os.path.join(_libdir, _scriptdir)
    if os.path.isdir(_full):
        datas.append((_full, _scriptdir))

# Our own modules are imported lazily in several places (the CLI defers most
# subcommand imports); collect_submodules ensures none are missed. darkdetect
# is customtkinter's runtime dependency for appearance detection.
hiddenimports = (
    collect_submodules("src")
    + collect_submodules("customtkinter")
    + ["darkdetect"]
)

a = Analysis(
    [os.path.join(ROOT, "src", "app_entry.py")],
    pathex=[ROOT],
    binaries=tk_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[os.path.join(ROOT, "packaging", "rthook_tk.py")],
    excludes=["pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)  # noqa: F821 - PYZ is a PyInstaller global

exe = EXE(  # noqa: F821 - EXE is a PyInstaller global
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="fukasawa",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # console=False gives the clean double-click experience (no stray
    # terminal window on Windows). On Linux, CLI output still reaches the
    # invoking shell. Windows CLI users should prefer the pip install.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
)
