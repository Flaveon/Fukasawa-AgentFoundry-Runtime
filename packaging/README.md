# Packaging — building the distributable executable

This produces a single self-contained executable of the Fukasawa
AgentFoundry Runtime. Double-clicked, it opens the desktop app; given
arguments, it is the full `fukasawa` CLI. Recipients need nothing installed
— no Python, no dependencies.

## Build

```bash
python -m pip install -e '.[build]'
./packaging/build.sh
# or pin an interpreter:
PYTHON=.venv/bin/python ./packaging/build.sh
```

The result is `dist/fukasawa` (≈30 MB on Linux). Verify it:

```bash
./dist/fukasawa validate brief examples/q2c-production-handoff.yaml   # CLI mode
./dist/fukasawa                                                        # GUI mode
```

**The example paths above work from anywhere**, including a directory with no
source: `examples/` is bundled into the executable and `src/resources.py`
resolves it, with your working directory always winning. That was not true
before phase 9 — all 39 files were inside the binary and none were reachable.

`docs/packaging-guide.md` records the full Linux verification and the
differences between a checkout, a wheel and this binary.

## One binary, two modes

`src/app_entry.py` dispatches: no arguments launches the GUI (the
double-click experience), any arguments run the CLI. So the same file a
non-technical colleague opens is also scriptable by a builder.

## Cross-platform

**PyInstaller builds for the OS it runs on** — it does not cross-compile.
To ship all three platforms, run `packaging/build.sh` (or the equivalent
`pyinstaller packaging/fukasawa.spec`) on each:

| Target | Build on | Produces |
|---|---|---|
| Linux | Linux | `dist/fukasawa` (ELF) |
| Windows | Windows | `dist\fukasawa.exe` |
| macOS | macOS | `dist/fukasawa` (+ optional `.app`) |

The spec is portable; the platform-specific pieces (Tcl/Tk libraries, the
harmless `user32`/`libobjc.dylib` ctypes probes) are handled automatically.
CI matrix builds across the three OSes are the usual way to produce all
artifacts from one commit.

## Notes on the spec

`packaging/fukasawa.spec` handles three things the stock hooks miss:

1. **Tcl/Tk 9** — newer Python builds ship Tcl/Tk 9, whose shared libs and
   script directories PyInstaller's tkinter hook does not yet locate. The
   spec discovers them from `sys.base_prefix/lib` (version-agnostic) and
   bundles them; `rthook_tk.py` points `TCL_LIBRARY`/`TK_LIBRARY` at the
   bundled copies at launch.
2. **customtkinter assets** — collected as data files so the UI themes.
3. **Lazy `src` imports** — the CLI defers most subcommand imports, so
   `collect_submodules('src')` ensures none are dropped.

`console=False` gives the clean double-click experience (no stray terminal
on Windows). On Linux, CLI output still reaches the invoking shell; Windows
CLI users should prefer `pip install` of the package.
