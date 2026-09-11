# Task 8 brief — the Environment tab

Written 2026-09-11, **after checking the plan's Task 8 section
(`docs/superpowers/plans/2026-08-23-node-and-capability.md`, lines 2709–3006)
against the source on `main` at `ef86721`.** The plan predates Tasks 5–7's fix
rounds and all of M8/I5/M5. It is used here for its file layout and its
threading pattern only; everything below overrides it.

## What the plan's text gets wrong, found before writing any code

| # | Plan says | Why that is wrong now | Instead |
|---|---|---|---|
| 1 | `run_scan` returns `list(services.scan(...))`, rendered at the end | §3.4: findings appear one at a time, never as a block | the worker puts **each event** on the queue as it arrives |
| 2 | `on_look` hardcodes `THIS_MACHINE` and calls `save_consent` first | §3.3 is a four-rung choice shown before any socket; Task 7's I6 made `scan()` record the permission it acts under | a permission pane with all four rungs, wired straight to `scan()` |
| 3 | `on_add` prints a `fukasawa node add` command | §3.8 (M8) specifies fields, a save, and a separate "May I contact it?" defaulting to no | a typed-in pane following §3.8 exactly |
| 4 | the view imports `ScanScope` from `src.schemas.node` | breaks the import law (ADR-007 §2) the plan itself cites — `TestImportLaw` fails | the rungs, with their §3.3 words, come from the service layer (`SCAN_CHOICES`) |
| 5 | `test_the_tab_never_judges…` calls `services.list_nodes()` with no store | reads the tester's real `~/.fukasawa/nodes.yaml` | every view test injects a store in `tmp_path` |
| 6 | the tab test has its own word list | the handoff moved the one list to `tests/copy_rules.py` | use `judgements_in` / `ownership_in` |
| 7 | nothing about concurrent writes | `src/gui/services/nodes.py` docstring: **the tab must not offer editing while a scan runs** | every write handler refuses while busy; buttons disabled |
| 8 | nothing about a silent check | M5 option C: a checked, silent computer must not keep reading "not checked yet" | `check_node` stamps it (`NodeStore.mark_silent`), CLI uses the same |
| 9 | the tab may read the store while being built | two test modules build `FukasawaApp`; `DEFAULT_HOME` is fixed at import | build reads nothing; the app calls `refresh()` when the tab is opened |

## Scope

**Files:** `src/gui/environment_views.py` (new), `src/gui/app.py`,
`src/gui/services/nodes.py`, `src/gui/services/__init__.py`,
`src/nodes/store.py` (`mark_silent`), `src/nodes/summary.py` (shared §3.8
copy), `src/cli.py` (use the shared copy and `mark_silent`), tests in
`tests/test_gui_workflow.py` (view, shared window), `tests/test_gui_nodes.py`
(service), `tests/test_node_store.py`, `tests/test_node_cli.py` (parity).

**No FROZEN path.** No new dependency. No network in any test.

## The tab

Four regions, one shown at a time, like the Workflow tab's pane stack:

- **home** — the §3.2 empty state when nothing is recorded; otherwise a
  §3.5 card per computer (fields with plain-language sources, a status line
  — *not checked yet* / *answering when last checked* / *not answering when
  last checked*, and **Change something**, **Check again**, **Forget**), the
  §3.6 panel, and **Look for more** / **Add one by hand**. A log above the
  cards fills one line per finding during a look.
- **permission** — §3.3, four rungs in its words, *Just this computer*
  preselected, an address box for the second rung, *You can change this
  later.*, **Cancel** / **Look**. *Don't look at anything* goes to typed-in
  and contacts nothing. The other three go to `scan()`, which answers the
  not-built and no-address cases itself.
- **typed-in** — §3.8: opening copy branched on whether anything is recorded,
  name / address / which program, **Save**; then *Saved … at …*, *Nothing has
  contacted it…*, and **Not now** / **Check it**.

## Service additions

- `SCAN_CHOICES` — the four rungs as `(scope, title, detail)` in §3.3 order.
- `add_node` normalises the address with `address_for` **before** the clash
  check, and returns `AddResult` carrying the stored `node_id` and `url`.
- `NodeRowView.status` — the three states above, from `reachable` and
  `last_probed_at`.
- `check_node(node_id, …)` — a one-computer look at a recorded address; if
  nothing answered there, the record is stamped silent **before** the closing
  event is yielded, keeping `scan()`'s promise that a finished look has
  already recorded what it learned.

## Tests must name what they would catch

The handoff's rule: five of six defects in this phase hid in what a fixture
avoided. So, specifically:

- **Streaming** is proved with a fetcher that **blocks** after the first
  event: the first line must be on screen while the scan is still running. A
  fake that returns instantly cannot tell streaming from batching.
- **No editing during a scan** is proved at the same blocked moment, by
  calling the write handlers and checking the file did not change.
- **The silent stamp** needs a check that finds nothing *at that address* —
  and a separate one that finds the computer, so the stamp is shown not to
  fire on success.
- Every guard is broken on purpose and confirmed red; anchors asserted unique.
