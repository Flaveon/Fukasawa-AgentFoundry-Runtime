# Phase 10a — the independent review, and its fixes

**Reviewed 2026-09-12, fixed 2026-09-12/13, by `claude-opus-5`, at the
operator's request.** Reviewed closely: `3d81d36..main` (`e16b6e4`) —
everything after Task 5, none of it independently reviewed before: Tasks 6–7
and their fix rounds, M8/I5/M5, Task 8, Task 9, and `1fa5a5e`. Context only:
the whole phase, `ae6b775..main`. Tasks 1–5 were not re-reviewed.

**The phase base is `ae6b775`,** the commit before the design spec. Earlier
documents called `3d81d36` the base; that is the end of Task 5, the boundary
between the reviewed and unreviewed halves. Corrected in the completion note,
the handoff and the Task 9 brief.

Not re-reported: the completion note's *Known limitations* and *New risks or
defects*, including the open operator questions.

## Findings, and what was done

Ten findings: four Important, six Minor. The operator asked for all ten fixed,
with a numeric suffix (not a warning) for #3. Each was reproduced against the
real code before fixing, each fix was written test-first and the test watched
fail, and each guard was then broken on purpose and confirmed red (below).

| # | Severity | Finding | Fix |
|---|---|---|---|
| 1 | Important | A check that **found** the computer said "Nothing answered", stamped the record silent, and filed the findings as a second computer — whenever the stored address was not spelled as a look produces it (CLI `node add` stored addresses as typed; `10.0.0.9:11434/` on the desktop; hand edits). | Addresses compared as `address_for` reads them (`recorded_at`, `src/nodes/store.py`) in `upsert` and every clash check; `node add` reads the address like the desktop; `mark_silent` takes an id; `check_node` and the CLI's typed-in check find the record again by id, and say "Nothing answered" only when nothing did. A matched record takes the spelling the look reached. |
| 2 | Important | YAML of the wrong shape in `nodes.yaml` (a list, a bare word, computers as a list, a computer with nothing under it) crashed the tab, `model list`, every graph run, and every `node` command. | `NodeStore.load` checks the shape and raises the `ValueError` every caller catches; the `node` commands answer an unusable file in the desktop's words (`unusable_message`, shared), exit 1. |
| 3 | Important | A computer's id could take a name the runtime already resolves (`local-ollama`, or one in `model_endpoints.yaml`), silently sending every graph using that name to a different machine. | A new computer gets a numeric suffix instead (`names_in_use`, `src/nodes/registry.py`), and both front ends say which name a graph uses when it differs from the label's (`graph_name`). |
| 4 | Important | A name given with `node scan --label` was saved with no source, and the next scan or the desktop's Check again renamed it. It was also given to every computer a look found. | `--label` is marked *you told me*; `upsert` leaves the name alone whatever its source, as design §6.0 already said; one name is not given to several computers, and a computer already named keeps its name — both said on screen. |
| 5 | Minor | `address_for` stored `10.0.0.9/` as `http://10.0.0.9/:11434` (a look then went to port 80), read `HTTP://` as a host, and took `[::1]` as naming a port. | `_normalise` reads the scheme whatever its case, drops a trailing slash either way, and reads the same the second time; `_names_a_port` reads only the host part and understands brackets. |
| 6 | Minor | `node show` printed "Answering no" for a computer nobody had contacted. | It prints the desktop card's three states (`status_of`). |
| 7 | Minor | The test for a broken `model_endpoints.yaml` could not fail: it passed while `model list` crashed with a parser traceback and printed nothing. Every graph run crashed the same way. | That file is now named in a warning and left out, like `nodes.yaml` (`merged_endpoints(on_unreadable=...)`, `legacy_endpoints`); the test asserts the exit code, the warning, and that recorded computers still resolve. |
| 8 | Minor | `jargon_in` let plurals through ("endpoints", "nodes", "scopes"). | Plurals caught; file names and backticked keys a person types are exempt, as commands are. |
| 9 | Minor | The tab's copy-rule test did not check its look had finished before reading the screen. | Asserted. |
| 10 | Minor | The findings stream said "It's ollama 0.5.4" where §3.4 says "Ollama". | The program's name, as the card heading already used. |

Fixture blind spots behind 1 and 2, in the phase's own terms: every
`check_node` test saved its computer through `add_node`, and the CLI's
stand-in discovery echoed the host string back as the finding's address, so
a record spelled differently from a finding could not arise; the unusable-file
fixtures were broken YAML and a bad field value, never YAML of the wrong
shape. The CLI stand-in now returns the address real discovery produces and
stamps `last_probed_at` as discovery does; the file fixtures include the five
wrong shapes.

## Verification

- `GITHUB_ACTIONS=true xvfb-run -a .venv/bin/pytest -q`: **1221 passed,
  2 skipped** (1045 passed before the fixes). `.venv/bin/python -m pytest -q`
  without a display: 1159 passed, 64 skipped.
- **24 guards broken on purpose, all red**, each anchor asserted unique, each
  mutation read back, each revert verified by checksum: two to four per
  Important finding, one or more per Minor.
- No FROZEN path touched across `ae6b775..HEAD`.

## What held

- **Consent.** Every route that contacts a computer records a permission
  first; the typed-in check defaults to no; Check again invents no question.
  No second permission exists.
- **Threading.** Every write handler on the tab refuses while a look runs,
  `refresh()` does nothing mid-look, and the worker's "done" is queued only
  after its last write. No race between the tab and the store beyond the
  known no-lock limitation.
- Task 8's streaming and busy tests, and Task 9's doctrine tests, each fail
  when what they guard is removed.

## Left as it is, deliberately

- **#3, the other order.** A name added to `model_endpoints.yaml` *after* a
  computer took it still resolves to the computer — design §6's order, later
  winning. And a computer already stored under such a name (recorded before
  this fix) keeps its id, because graphs may already use it.
- **#4 under `--json`.** A label that was not applied is reported as one more
  line, `{"stage": "label", "ok": false, "finished": false}`, after the
  closing event.
- **Deferred minors from the ledger.** Task 5's "upsert compares URLs as exact
  strings" is fixed by #1. Task 1's (two helpers without a direct test) is
  covered downstream. Task 3's two (a probe's note overwritten by the last
  failure; the 12-model cap untested) are still open.
