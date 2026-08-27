# Packaging guide

Three ways to install this, and what each one is for. The differences are real
and the choice matters, so they are stated rather than left to be discovered.

| Install | For | Gets the pilot examples? | Desktop app? |
|---|---|---|---|
| **Source checkout** (`pip install -e`) | developing, running the tests | yes — they are in the tree | yes, with `[gui]` |
| **Wheel** (`pip install .`) | using the library or CLI from another project | **no** — see below | yes, with `[gui]` |
| **Binary** (PyInstaller) | giving it to someone who does not have Python | **yes**, bundled inside | yes, it *is* the desktop app |

## The binary

One file. Double-clicked it opens the desktop app; given arguments it is the
full CLI. Recipients need nothing installed.

```bash
uv pip install -e '.[build]'
PYTHON=.venv/bin/python ./packaging/build.sh
```

Result: `dist/fukasawa`, about 30 MB on Linux.

### Verified, not deferred

Master handoff §2.3 permits either "verified on a supported target" or an
explicit documented blocker. **It is verified.** On Linux (kernel 5.15, Python
3.12.13, PyInstaller 6.22.2), from an empty directory containing no source:

| Check | Result |
|---|---|
| `fukasawa --help` | works |
| All 9 `workflow` subcommands present | works |
| `validate` the bundled pilot by its documented path | 24 findings, exit 2 |
| `validate brief` the bundled brief example | works |
| Full lifecycle: validate → promote ×2 → assess → build → export | works, brief written |
| `workflow status` after it | 5 of 6 stages present |
| GUI mode under Xvfb | window `Fukasawa AgentFoundry Runtime` 820x640, clean startup, no output |

Windows and macOS are built by CI (`.github/workflows/build.yml`) on their own
runners — PyInstaller does not cross-compile — but have **not** been
hand-verified beyond CI's smoke test. That is the honest state: Linux is
verified by the table above, the other two are built and smoke-tested.

### Bundled examples work from the binary

They did not until phase 9. The spec bundles all 39 files under `examples/`,
PyInstaller unpacks them into `sys._MEIPASS`, and nothing resolved paths against
it — so the binary carried the pilot and every documented command failed with
"No such file".

`src/resources.py` resolves this, with the working directory always winning:

1. the path as given, if it exists — **always**, even when a bundled file has
   the same name, because a file the operator edited is the one they mean;
2. when frozen, the same relative path inside the bundle;
3. otherwise the path as given, so the error names what they typed rather than
   a temporary directory they have never heard of.

An absolute path is never redirected into the bundle.

## The wheel does not ship `examples/`

**This is a decision, not an oversight.** A `pip install .` gives you the code
and none of the pilot, so documented commands like

```bash
fukasawa workflow validate examples/workflows/substack-publication/observed-workflow.yaml
```

will not work from a bare wheel install. Use a checkout or the binary for those.

The reasoning: `examples/` sits at the repository root, outside any package.
Shipping it in a wheel means either restructuring it under `src/` — which
changes every documented path in every document, for the benefit of the one
install mode least likely to want it — or `data-files`, which installs to
`sys.prefix` where nothing can reliably find it again. Neither trade is worth
it. The wheel's audience is a developer integrating the library, and they have
the repository.

`src.resources.bundled_examples()` returns `./examples` when it exists and the
process is not frozen, so a checkout and a binary both answer "where is the
pilot?" correctly and a wheel install answers `None` rather than lying.

## What is in the wheel

Every package under `src/`, discovered rather than listed:

```toml
[tool.setuptools.packages.find]
include = ["src*"]
```

It used to be a hand-written list, and it silently omitted `src.gui.services`
when phase 7 split that module into a package — every wheel built for two weeks
installed a GUI that could not import its own service layer, while the suite
stayed green because tests run from the source tree. `tests/test_packaging.py`
builds a real wheel and reads its manifest, from a clean copy of the tree with
`--no-cache-dir`, because both a cached wheel and a leftover `*.egg-info` will
otherwise make a broken configuration look correct.

## What the spec handles that stock hooks miss

`packaging/fukasawa.spec`:

1. **Tcl/Tk 9** — newer Python builds ship Tcl/Tk 9, whose shared libraries and
   script directories PyInstaller's tkinter hook does not locate. The spec finds
   them under `sys.base_prefix/lib` version-agnostically and bundles them;
   `packaging/rthook_tk.py` points `TCL_LIBRARY`/`TK_LIBRARY` at the bundled
   copies at launch.
2. **customtkinter assets** — collected as data files so the UI themes.
3. **Lazy `src` imports** — the CLI defers most subcommand imports, so
   `collect_submodules("src")` catches what static analysis misses. This is also
   why the phase 7b modules (`dialogs`, `tables`, `step_editor_view`, the
   `services` package) needed no spec change: discovery covers them.
4. **`examples/` as data** — bundled at `examples/`, reachable via
   `src/resources.py`.

`console=False` gives a clean double-click with no stray terminal on Windows. On
Linux, CLI output still reaches the invoking shell; Windows CLI users should
prefer a `pip install`.

## FROZEN paths are enforced in CI

`.github/workflows/frozen-paths.yml` fails a pull request that modifies any path
in directive §3's FROZEN list. The list was prose until phase 9, and prose did
not bind: four files were edited across four merged PRs by a contributor that
did not read it.

The escape hatch is a tracked file, `.github/FROZEN_WAIVER.md`, naming which
files, why, who authorised it, and what was re-verified — so the decision is
reviewable in the diff instead of argued in a comment thread. The job does not
forbid the change; it forbids the change happening quietly.

## A clean checkout, end to end

Master handoff §2.3 asks that a clean checkout can install, test, build and run
from documented commands. It can:

```bash
git clone https://github.com/Flaveon/Fukasawa-AgentFoundry-Runtime.git
cd Fukasawa-AgentFoundry-Runtime
uv venv --python 3.12 .venv
uv pip install -e '.[dev,gui]'

xvfb-run -a .venv/bin/python -m pytest -q      # 694 passed, 1 skipped
.venv/bin/python -m pytest -q                  # 654 passed, 41 skipped

uv pip install -e '.[build]'
PYTHON=.venv/bin/python ./packaging/build.sh   # dist/fukasawa
./dist/fukasawa --help
```

Run the suite **both ways**. The plain invocation silently skips 40 view tests
that only execute under a display, and one of the desktop defects found in
phase 7 only ever appeared under Xvfb.

**A git worktree needs its own venv.** The repository-root one carries an
editable install pointing at the main checkout, so `import src` resolves there
rather than at your worktree and you will test the wrong tree without noticing.
