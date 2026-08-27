# Task 7 Fix Report: closing the review findings

Written as a separate file rather than a section appended to
`task-7-report.md`, so the implementer's own account of what was built stays
readable on its own and this reads as what it is: a round that changed that
work without rewriting it.

Range: `b8541f7..4999df2`, ten commits, no `Co-Authored-By` trailer on any of
them.

## Test counts

| | passed | skipped | time |
|---|---|---|---|
| before (`b8541f7`) | 861 | 41 | 54.29s |
| after (`4999df2`) | 907 | 41 | 53.56s |

`tests/test_gui_nodes.py` went 33 → 77 (one of the 33 was deleted, see M3, so
45 were added). `tests/test_node_cli.py` went 49 → 53. No new skips, no
regressions, no test disabled or loosened.

## Files touched

Exactly the five the round allowed. `git diff --stat b8541f7..HEAD`:

```
 src/cli.py                   |  23 ++-
 src/gui/services/__init__.py |   6 +
 src/gui/services/nodes.py    | 247 +++++++++++++++++++++++++---
 tests/test_gui_nodes.py      | 369 ++++++++++++++++++++++++++++++++++++++++--
 tests/test_node_cli.py       |  34 ++++
```

No FROZEN path. `src/cli.py` was touched only for I3's guard, as scoped.

## Finding by finding

### C1 (Critical) — CLOSED — `6b4dbf0`

All six entry points now catch `(OSError, yaml.YAMLError, ValueError)` and
return a refusal naming the file and a route out of it. `_unusable()` tells
the three cases apart — unopenable, not YAML, off-contract — because they
call for different repairs; `NodeStore.load` already phrases the third and
names the path, so that one is passed through as written.

`list_nodes`' docstring no longer claims "Never refuses". It now says it
refuses exactly once, when the file cannot be read.

Red watched first: 18 new tests, all failing by raising — `yaml.parser.
ParserError`, `ValueError` from `store.py:55`, and `IsADirectoryError` — one
of each confirmed in the traceback rather than assumed. Then two
representative guards mutated to `except (KeyError,)` and watched go red
(6 failures each), anchors asserted unique and read back, file restored by
checksum.

`scan()`'s store failure yields `stage="store"`, `ok=False`, `finished=True`.

### I2 (Important) — CLOSED — `3f17c76`

`REFUSAL_STAGES` added beside `EDITABLE` and exported. Pinned by a test
asserting discovery's `done` is **not** on it, in the not-found variant
specifically (`ok=False`, `finished=True`, message "Didn't find anything
answering…") and in the found variant, plus tests that each stop before
looking **is** on it. Mutating the constant to include `"done"` fails two
tests.

**Judgement call — the list has four members, not the three named.** I
verified the stage strings against what `scan()` actually emits, as asked,
and after C1 it emits a fourth: `"store"`. It is not a refusal on doctrine,
but it stops the scan the same way and needs the same treatment — a view
that rendered it as one more finding row would bury the only message telling
somebody their file is broken. Reasoning is written at the constant. Reverse
by deleting one string and one test if the operator wants the name to mean
refusals strictly; `"store"` would then need a second constant, or Task 8
would need to special-case it.

### I1 (Important) — CLOSED — `ba5e21e`

New test runs a recorder that answers nothing — the only stream where all
three fields vary — and asserts the shape of the whole sequence:
`[e.finished …] == [False, False, True]`, `[e.ok …] == [True, True, False]`,
and all three messages verbatim.

Mutation-checked, four for four, each anchor asserted unique and read back,
each restore verified by checksum:

| mutation | result |
|---|---|
| `message=event.message,` → `message=NOT_BUILT,` | RED (2 failed) |
| `ok=event.ok,` → `ok=True,` | RED (2 failed) |
| `finished=event.finished,` → `finished=True,` | RED (1 failed) |
| `stage=event.stage,` → `stage="done",` | RED (2 failed) |

`stage` was a fourth unpinned passthrough that the finding did not name; it
is pinned now by the M2 replacement.

### Seam fix (`ScanEventView.node_id`) — CLOSED — `311457b`

`node_id: str = ""`, populated from `event.node.node_id`. Test asserts the
six describing stages carry it, the `trying` and `done` rows do not, and all
six name the same computer. Mutating the assignment to `""` goes red.

Documented, because it is a real limit: this is the id **discovery derived**,
which is what groups the rows of one scan. It is not promised to be the id
the computer ends up stored under — `upsert` keeps the id an already-recorded
address is filed under, and suffixes a newcomer whose id is taken. Task 8
should read the stored id back from `list_nodes` once the scan closes.

### I3 (Important) — CLOSED — `07d6b42`

`node_consent` gets the same guard, per the operator's ruling. Reasoning is
commented at the call site pointing at the `node scan` branch's argument.
Exit 1, matching that site and its stated reason: nothing is refused on
doctrine, the sweep has not been written; `src/cli.py:35` documents 3 for the
former.

Red watched first: exit 0 with "Changed to: Every computer on this network"
and the permission written to file. Two tests — one for the exit code, the
answer, and the permission on file being untouched; one for the answer naming
two permissions that do work. `node consent --set local-network` was also
added to the copy-rules parametrize list.

Mutation: the guard's condition → `if False:` goes red. **Note the anchor
trap fired here as designed** — see "Traps" below.

### I4 (Important) — CLOSED — `c0182cd`

Blank check reused from `add_node` via a shared `NEEDS_BOTH` constant, so
the two write paths cannot drift. URL clash rejected when a *different*
`node_id` already holds it; re-typing the same address onto the same computer
still works, and there is a test saying so.

Red watched first: 4 blank cases + 1 clash case, all returning
`ok=True, "Saved."`. Both guards mutated to no-ops and watched go red.

### I5 (Important) — PARTLY CLOSED — `8b0e537` (service only)

`add_node` reads before writing and refuses with "Already recorded at that
address as 'Home PC'. Edit that computer to change what it is called."

**Measured behaviour differs slightly from the finding, and is worse than
described.** With the seeded node's provenance (no `DECLARED` on `label` or
`kind`), the old code did not merely discard the typed values — it applied
them to the existing row. Adding "Kitchen Box"/`llamacpp` at Home PC's
address returned `ok=True, "Added Kitchen Box."` and left the store holding
`("home-pc", "Kitchen Box", llamacpp)`: no computer created, the count
unmoved, and somebody else's row silently renamed and re-typed. The reviewer's
"corrected kind discarded" is what happens when the existing row's label *is*
`DECLARED`; both are wrong and both are now refused.

**NOT closed in `src/cli.py`.** `node_add` shares the behaviour. I did not fix
it, and this is a deliberate stop rather than an oversight: the round scopes
`src/cli.py` to I3 only and `tests/test_node_cli.py` to I3's test only, so a
change there could not be covered by a test. Shipping an untested behaviour
change to a second front end to close a finding about a front end lying to
people is the wrong trade. **The exact change for the next round**, at
`src/cli.py` `node_add`, before `_node_store().upsert(node)`:

```python
store = _node_store()
clash = next((n for n in store.load()[0] if n.url == url), None)
if clash is not None:
    console.print(
        f"Already recorded at that address as [bold]{escape(clash.label)}[/bold]."
    )
    raise typer.Exit(1)
```

Exit 1 for the same reason the neighbouring sites give. Until then the two
front ends disagree on `add`, which is the §3.7 divergence I3 was about, one
verb over.

### I6 (Important) — CLOSED — `c771e9c` — **option (a)**

**Chosen: `scan()` records the consent it acts under.** Rejected: documenting
the required call order and pinning it with a test.

Why. A documented call order is a rule the view can break silently, and the
only thing that would notice is a person reading the docstring. The whole
pitch of this feature is that nothing is examined beyond what was permitted,
and the permission record is the only artifact that can ever be shown as
evidence of that. If Task 8 wires the §3.3 radio straight to `scan()` — which
the review says it will — then under option (b) the tab scans and the record
says nothing was ever granted. Option (a) makes that impossible instead of
forbidden. It also makes the two front ends identical: `node scan` writes
`set_consent` immediately before its discovery loop, and this is the same
write at the same point.

`scan()` gained `actor: str = "operator"`, matching what the CLI writes.
Placed after `store` in the signature; every existing caller passes `store`,
`fetch` and `post` by keyword, so nothing shifted.

`scan()` **does not consult** stored consent, and that is deliberate: the
scope argument is the request, exactly as `--scope` is for the CLI. Gating
the request on the record as well would mean a first-ever scan could never
happen. Recording it is what makes the record true.

Ordering is pinned three ways, all watched red: the write mutated to `pass`
(3 failures); the write inserted **above** the guards (8 failures, which is
the test that a refused reach is never written down); and three parametrized
cases asserting a stop leaves the record alone.

### I7 (Minor priority, write-down) — CLOSED as asked — `c56b9fb`

Constraint written into `nodes.py`'s module docstring, in the terms Task 8
needs: **the tab must not offer editing while a scan is running** — disable
the card's fields, or hold the edit until the closing event. Names both
mechanisms (no lock, no mtime check, plain `write_text` so a crash truncates)
and says explicitly that fixing it is a change to the store, which this phase
does not own. Store untouched, as instructed.

### M1 — CLOSED — `6b4dbf0`

`scan()` collects into `found` and upserts once per computer after the loop,
the CLI's shape. Written **before** the closing event is yielded, so a scan
that says it has finished has already recorded what it found.

Pinned by counting `NodeStore.save` calls: `[0, 1]` — the permission write
with nothing on file, then the one computer. Mutating `if event.finished and
found:` to `if found:` goes red. Was six writes per computer found.

### M2 — CLOSED — `ba5e21e`

`assert all(hasattr(e, "message") …)` replaced with the full stage sequence
for a scan that finds something. The old assertion was true by construction
for any `ScanEventView`; the new one caught the `stage` passthrough mutation.

### M3 — CLOSED by deletion — `4999df2`

Deleted, with a comment left in its place saying where the check lives.
Confirmed first that `test_gui_workflow.py::TestImportLaw::
test_services_never_import_widgets` is parametrised over a glob and collects
`services/nodes.py` as a case. It walks the AST, so it catches `from tkinter
import Tk`, which the substring check read past. Keeping both meant the
weaker one was the one a reader of this file would find and trust.

### M4 — CLOSED — `3f17c76`

`NOT_BUILT`, `REFUSAL_STAGES` and `UNUSABLE_FILE` re-exported from
`src/gui/services/__init__.py` and added to `__all__`, with a test asserting
the package attribute *is* the module's object.

### M5 — NOT FIXED, out of scope, confirmed — no commit

Verified rather than taken on trust. `src/nodes/summary.py:113` is
`usable = [n for n in nodes if n.reachable]`, and a hand-added
`InferenceNode` has `reachable` defaulting to False. So the route both
refusals recommend — "type a computer in by hand" — lands on a panel reading
"Agent steps can run on: nothing yet" and "No step can be assigned to an
agent." Both refusals are therefore currently signposting a dead end. This is
Task 3's contract and needs a decision, not a patch here.

### M6 — CLOSED — `c771e9c`

`scan()`'s docstring says it is a generator and that nothing happens — no
refusal, no permission written, no address opened — until the first `next()`.

### M7 — no action, as directed.

## Traps this round, and what happened

**Anchor uniqueness fired twice, both caught by the guard rather than by a
misleading red.** Every mutation went through a helper that asserts the
anchor appears exactly once, applies it, reads the file back to confirm the
mutation landed, and restores from a pristine copy verified by checksum.

1. `target.set_consent(ScanConsent.granted(scope, actor))` appears **twice**
   after this round — in `save_consent` and in `scan`. The helper refused the
   mutation. Re-run with the `try`/`except`/first-body-line triple as the
   anchor, which is unique. This is the identical failure the implementer
   self-reported, at the identical line, arriving a third time.
2. `if chosen is ScanScope.LOCAL_NETWORK:` is **not** unique in `src/cli.py` —
   `node_scan` has it too. Anchored on the condition plus its following
   comment line.

**"What does the fixture make impossible."** The I1 test was written by asking
what a recorder that *answers* makes impossible: it makes `ok=False` on a
non-terminal event impossible and makes `finished` vary only at the end,
which is precisely why the old assertions could not fail. The recorder that
answers nothing is the fixture where all three vary. Every new assertion in
this round was mutation-checked against the line it claims to catch, except
where the test was watched fail before the fix existed — 18 for C1, 7 for I2,
5 for I4, 1 for I5, 2 for I3, 2 for I6.

## Judgement calls, all reversible

1. **`REFUSAL_STAGES` has four members, not three.** `"store"` added. See I2.
2. **I6 option (a) over option (b).** See I6.
3. **`scan(actor="operator")` default**, matching what the CLI hardcodes.
   Task 8 should pass the real operator rather than rely on the default.
4. **I5 not fixed in `src/cli.py`**, on the file-scope constraint. Exact
   patch written above. This is the one finding I am reporting as only
   partly closed.
5. **`add_node` at a known address now refuses (`ok=False`) rather than
   succeeding quietly.** It could have returned `ok=True` with an honest
   summary. Refusing is right because nothing the person asked for happened;
   the view can then show it where a person will read it.
6. **Copy for every new string** checked against §3.1.1/§3.1.2 using the
   existing `judgements_in` / `ownership_in` helpers — no second word list —
   including a test over the unusable-file refusal and the two new
   `update_field` refusals. The new CLI answer is in the `node` copy-rules
   parametrize list.

## Still open after this round

- **I5 in `src/cli.py`'s `node_add`** — patch above, needs a test-file
  allowance.
- **M5** — the hand-add route lands on a "nothing can run" panel. Task 3's
  `reachable` gate. Needs a decision.
- The known-accepted items from the 2026-08-26 03:29 ledger block are
  untouched: the copy-rule helpers still live in `tests/test_node_cli.py` and
  `tests/test_gui_nodes.py` still imports them (Task 8 would be the third
  importer — the move to `tests/copy_rules.py` is still the right fix and is
  still outside this round's files); `list_nodes` still says "{n}
  computer(s) recorded."; `update_field` still accepts `kind` with no §3.5
  row for it; `add_node` still leans on `_with_unique_id` for two hand-added
  computers with the same *name* at *different* addresses, silently.
- **M8 from Task 6**, still needing the operator.
