# Task 7 Report: GUI service layer for node management

## Scope completed

All of it, test-first, with every test watched fail before it passed.

1. Wrote `tests/test_gui_nodes.py`; confirmed it failed with
   `ImportError: cannot import name 'nodes' from 'src.gui.services'`.
2. Wrote `src/gui/services/nodes.py` from the plan's text, amended by the
   brief's three corrections plus two judgement calls recorded below.
3. Added the re-exports and `__all__` entries to `src/gui/services/__init__.py`.
4. Ran the targeted tests, then fourteen mutation checks, then the full suite.

## Files created / modified

- Created: `src/gui/services/nodes.py`
- Created: `tests/test_gui_nodes.py`
- Modified: `src/gui/services/__init__.py` (eleven re-exports, eleven `__all__`
  entries, one docstring bullet)
- Nothing else. FROZEN check:
  `git status --short | grep -E "kernel/|security/|schemas/graph|schemas/bundle|generator\.py|state_machine|runtime/bundle"`
  → `no frozen path touched`.

## The three corrections in the brief

**Correction 1 — `post` is forwarded.** `scan()` takes `fetch=None` *and*
`post=None` and forwards whichever were given. Two things guard it:

- `test_the_scan_forwards_the_poster_it_was_given` asserts a POST to
  `/api/show` landed in the recorder. Deleting the forwarding line turns it red.
- An autouse `no_sockets` fixture replaces `urllib.request.urlopen` with
  something that raises `AssertionError`. This is the part that matters:
  `probe_ollama` catches `OSError` at every stage, so a real connection that
  is refused is indistinguishable from a stand-in declining to answer. An
  `AssertionError` is not an `OSError` and is not swallowed. The fixture is
  deliberately *not* patched at `src.nodes.backends.http_post_json`, because
  patching there would also hide a service that forgot to forward — the defect
  the test exists to catch.

Deleting the `post` forwarding turns **seven** tests red, six of them through
the socket guard. The file runs in 0.49s; nothing in it opens a socket.

**Correction 2 — `LOCAL_NETWORK` is refused legibly.** `scan()` yields
`ScanEventView(stage="not-built", ok=False, finished=True)` before
`candidate_addresses` can raise `ConsentRefused`. Mutation-checked: with the
guard removed the test fails on the raised `ConsentRefused`, which is the crash
on a button press this prevents. The stage is `"not-built"` rather than
`"permission"` so Task 8's tab can tell "you granted nothing" apart from "this
part is unwritten" without parsing prose — the same distinction the CLI drew
with exit 1 versus exit 3.

**Correction 3 — the Tk-free test reads through the module.**
`pathlib.Path(service.__file__)`, not a cwd-relative literal. Checked by
inserting `import tkinter` into the service and watching it go red.

## Decisions I made that the brief did not specify

Two additions, both flagged here rather than buried, both one function and one
test wide so they are cheap to reverse.

**1. `save_consent` refuses `LOCAL_NETWORK` too.** The brief covers `scan()`.
I extended the same refusal to the consent write, for the CLI's stated reason
(`src/cli.py`, the `LOCAL_NETWORK` branch of `node scan`): a permission nothing
can act on gets read back by every later scan and refused again, so the screen
says the reach was granted while nothing acts on it. Design §3.7 asks the two
front ends to match, and this is the one place they could have diverged
silently.

Counter-argument, so the reviewer has it: someone might want to record the
grant now against the sweep being built later, and the GUI's cost of a bad
consent is lower than the CLI's because §3.3 says the permission is changeable
from the same screen. I judged consistency with the CLI to be worth more.
Reverse by deleting the two-line guard in `save_consent` and the
`test_a_permission_nothing_can_act_on_is_not_written_down` test.

**2. `scan()` refuses `NAMED_HOST` with an empty address.** Without it,
`_normalise("")` produces `http://`, and the scan reaches for
`http://:11434` — an address that is nothing, failing in a way that reads to a
person as "the scan didn't work". The CLI has this guard already. Not a privacy
leak, just a defect; small enough that writing a comment about it instead of
fixing it seemed worse.

**3. `EDITABLE` stays `("label", "url", "kind")`, and only `label` and `url`
appear as editable rows on the card.** `kind` is accepted by `update_field`
(the plan's contract) but no card row offers it, because §3.5's card does not
show it. No measured figure is editable: typing over a reading would flip its
source to "you told me", which is an honest label on an invented number.
`test_the_name_and_address_are_editable_and_the_figures_are_not` pins this.

**4. `LOOPBACK` in the test is derived from `src.nodes.backends.PORTS`.** I
first hardcoded `{11434, 8080}` and the scope test failed — llama.cpp is on
8081. A hand-typed constant that is wrong makes the assertion describe a scan
nobody performs, so it now comes from the port table.

**5. The copy-rule helpers are imported, not copied.**
`from tests.test_node_cli import judgements_in, ownership_in`. The brief asked
for one mechanism rather than two; extracting a shared helper module would have
meant a fourth file and an edit to `tests/test_node_cli.py`, both outside the
three files I was given. See the open question below.

## Mutation checks

Fourteen lines deleted or broken one at a time, each restored afterwards, each
run with the mutation asserted to have actually applied to the file first.
All fourteen turned the file red:

| Mutation | Caught by |
|---|---|
| `post` not forwarded | 7 tests, incl. the socket guard |
| `NONE` guard in `scan` deleted | `test_scanning_without_permission_refuses_and_opens_nothing` |
| `LOCAL_NETWORK` guard in `scan` deleted | `test_the_whole_network_sweep_is_refused_rather_than_raised` |
| `LOCAL_NETWORK` guard in `save_consent` deleted | `test_a_permission_nothing_can_act_on_is_not_written_down` |
| `NAMED_HOST` empty-address guard deleted | `test_a_named_host_with_no_address_is_refused` |
| `url` row not editable | `test_the_name_and_address_are_editable_and_the_figures_are_not` |
| edited field not marked `DECLARED` | `test_editing_a_field_marks_it_as_typed` |
| progress not forwarded | `test_progress_reaches_the_view` |
| `host` argument dropped | `test_a_named_host_is_the_only_host_touched` |
| a judgement word enters the copy | both `TestCopyRules` cases |
| a widget import appears | `test_no_widget_import` |
| `consequence` dropped from the listing | `test_empty_store_is_not_a_failure` |
| findings not saved | 3 scanning tests |

**One mutation lied on the first pass and I want it on the record.** My first
attempt at "delete the `LOCAL_NETWORK` guard in `scan`" replaced the first
occurrence of `if scope is ScanScope.LOCAL_NETWORK:` in the file — which is in
`save_consent`, defined above `scan`. It went red, but for the other guard's
test. `scan`'s guard had not been mutated at all. Re-run against a unique
anchor, with the anchor asserted present before the run, and it is genuinely
red on its own test. This is the "verify the mutation applied" trap arriving in
the middle of the exercise designed to avoid it.

## Test commands and output

Before:

```
$ .venv/bin/python -m pytest -q
827 passed, 41 skipped in 55.73s
```

The new file, and the GUI suite that globs service files:

```
$ .venv/bin/python -m pytest tests/test_gui_nodes.py -q
33 passed in 0.49s

$ .venv/bin/python -m pytest tests/test_gui_nodes.py tests/test_gui_workflow.py -q
107 passed, 36 skipped in 13.29s
```

After:

```
$ .venv/bin/python -m pytest -q
861 passed, 41 skipped in 52.27s
```

861 = 827 + 33 new tests + 1: `TestImportLaw::test_services_never_import_widgets`
is parametrised over a glob of `src/gui/services/*.py`, so the new service file
adds a case to it. 41 skips unchanged and pre-existing.

## What I deliberately did not do

- **No /24 network sweep.** Out of scope for this plan; refused in words in two
  places instead.
- **No Environment tab.** That is Task 8. Nothing here imports a widget or
  prints.
- **No local machine facts.** §3.3 says `THIS_MACHINE` covers "this computer's
  own CPU/RAM/OS" as well as loopback ports, and `discover()` does not collect
  them today. That is a gap in Task 4's discovery, not something a service
  layer should paper over by growing its own probe.
- **No change to `src/nodes/`, `src/cli.py`, or `tests/test_node_cli.py`.**
- **`SummaryRow.source` left alone** — the brief says Task 2's review deleted
  it and the `summary_rows` line is clean. Confirmed; untouched.

## Open questions handed back

1. **The copy-rule helpers live in a test file that another test file now
   imports.** `tests/test_gui_nodes.py` does
   `from tests.test_node_cli import judgements_in, ownership_in`. It works
   (pytest is invoked as `python -m pytest`, so the repo root is on
   `sys.path` and `tests` resolves as a namespace package) and it satisfies
   the brief's "one list, not two". But it means `test_node_cli.py` is
   imported twice under two names, and Task 8 will be the third consumer. The
   right home is probably `tests/copy_rules.py` — a fourth file and an edit to
   a fifth, both outside the three files I was given. **Flagging rather than
   doing it.**

2. **`list_nodes` says "0 computer(s) recorded" in plan wording.** I kept the
   plan's `f"{len(nodes)} computer(s) recorded."`. "computer(s)" is not a
   sentence anybody writes, and §3.7 asks for the same register as the desktop.
   It breaks no copy rule, so I left the plan's text rather than inventing my
   own — but if a reviewer wants "1 computer recorded / 3 computers recorded",
   that is a one-line change.

3. **`update_field` accepts `kind` but no card row offers it.** The plan's
   contract includes it; §3.5's card does not show it. Either the card should
   gain a row in Task 8 or `kind` should leave `EDITABLE`. Not my call to make
   from here.

4. **`add_node` derives `node_id` from `slugify(label)` and does not check for
   a collision** — it relies on `NodeStore.upsert`'s `_with_unique_id`, added
   in Task 5's fix round. Two hand-added computers called "Home PC" at
   different addresses therefore become `home-pc` and `home-pc-2`, silently.
   That is the store's documented behaviour and I did not second-guess it, but
   nothing tells the person their second computer got a different name than the
   one they typed. Worth a glance when the tab is built.

5. **`ScanEventView.stage` is now a four-value vocabulary from this service
   (`permission`, `not-built`, `address`) plus everything discovery emits.**
   Nothing enumerates it. Task 8 will want to know which stages mean "stop and
   show a refusal"; today the answer is `ok=False and finished`.
