# Task 7 brief: GUI service layer

**Source:** `docs/superpowers/plans/2026-08-23-node-and-capability.md`, lines 2307–2707.

**Read the corrections below before you read the plan.** The plan was written
on 2026-08-23. Five tasks have landed since, and Task 6's brief was stale in
two places — one caught, one not, and the one not caught became a defect that
reached review. This brief has been checked against the current source. Two
things in the plan's Task 7 text are wrong, and one of them would reproduce a
defect the review loop already caught once.

---

## CORRECTION 1 (critical): `scan()` must forward `post`, not only `fetch`

The plan's service signature is:

```python
def scan(scope, host="", store=None, fetch=None) -> Iterator[ScanEventView]:
    ...
    kwargs = {"fetch": fetch} if fetch is not None else {}
    for event in discover(scope, host, **kwargs):
```

`discover` in the current source takes **both**, keyword-only
(`src/nodes/discovery.py:114-121`):

```python
def discover(scope, host="", *, fetch=http_get_json, post=http_post_json,
             connect_timeout=2.0) -> Iterator[DiscoveryEvent]:
```

And `probe_ollama` falls back to the real network when `post` is absent —
`src/nodes/backends.py:99` is `post = post or http_post_json`, and line 131
POSTs to `/api/show` for **every model** the server lists:

```python
# A POST with the name in the body — Ollama's /api/show is not a GET.
shown = post(f"{base_url}/api/show", {"name": model.name}, 10.0)
```

So the plan's own test — which returns a model named `"m"` from `/api/tags`
and injects only `fetch` — would send **real outbound POSTs to
`http://127.0.0.1:11434/api/show`**. A GUI service whose scan cannot be faked
for POST traffic is untestable for the exact traffic the privacy rules police.

This is not hypothetical. It is the Task 4 defect verbatim: *"the fake could
not see POST traffic, so the privacy assertions had a blind spot over exactly
the traffic they policed."* It cost a review round then. Do not re-create it.

**Do this instead:** `scan()` takes `fetch=None` **and** `post=None` and
forwards whichever were given. The test injects **both**, and asserts on the
recorded calls that no address outside the granted scope was touched — by
either verb. Look at how `tests/test_node_discovery.py` does it; there is a
`Recorder` there that records GET and POST into one asserted list. Reuse that
approach rather than inventing a second one.

**Prove it, do not assume it.** Before you finish, confirm the whole file is
hermetic: no test may open a socket. A runtime in the tens of seconds is the
tell — Task 4's suite went 20.09s → 0.08s when this was fixed.

## CORRECTION 2 (important): the service must refuse LOCAL_NETWORK legibly

The plan's `scan()` guards only `ScanScope.NONE`. But `candidate_addresses`
raises `ConsentRefused` for `LOCAL_NETWORK` (`src/nodes/discovery.py:83`) —
the /24 sweep is **not built in this phase**, by design.

Task 6 hit this at the CLI and it was a review Critical: the command crashed
with an uncaught traceback *and* had already persisted an unusable consent, so
every later scan crashed the same way. The fix is at `src/cli.py:1480-1498` —
refuse before the consent write, in plain words, naming what does work.

The GUI service has the same hole and Task 8 is about to build a tab on top of
it. Yield a refusal `ScanEventView` (`ok=False, finished=True`) for
`LOCAL_NETWORK`, the way `NONE` is handled, rather than letting
`ConsentRefused` escape into the view. Do **not** implement the /24 sweep —
out of scope for this plan.

Note the CLI chose **exit 1** for this, on the reasoning that exit 3 means
"refused as a matter of doctrine" and nothing here is refusing anyone: the
feature does not exist yet. The service has no exit codes, but keep the same
distinction in the wording.

## CORRECTION 3 (minor): the Tk-free test's path is cwd-dependent

`TestServicesStayTkFree` does `pathlib.Path("src/gui/services/nodes.py")`,
which only resolves when cwd is the repo root. It works under pytest, whose
rootdir is the repo root. Prefer deriving the path from the imported module
(`pathlib.Path(service.__file__)`) so it cannot silently pass by reading
nothing, or silently fail from another directory.

---

## Verified as still correct

Checked against the current source — the plan is right about these, do not
"fix" them:

- `Outcome` (`src/gui/services/workflow.py:90`) has exactly `ok: bool`,
  `summary: str`, `refusal: str = ""`. The `NodeListResult(Outcome)` subclass
  with defaulted fields is a valid dataclass — parent's only non-defaulted
  fields come first.
- `DiscoveryEvent.progress` exists, `tuple[int, int] = (0, 0)`
  (`src/nodes/discovery.py:54`), so `event.progress[0]` / `[1]` are fine.
- `source_of(field_path)` is a plain dict lookup
  (`src/schemas/node.py:184`), so the dotted keys
  `"host.tokens_per_second"` and `"host.vram_bytes"` work.
- `max_context_length` is a property returning `int`, `0` when unestablished
  (`src/schemas/node.py:189`).
- `summary_rows=[(r.label, r.value) for r in summary.rows]` does **not** touch
  `SummaryRow.source`. That attribute was deleted by Task 2's review and its
  presence is what made Task 6's brief stale. This line is clean — leave it.

---

## The plan text

Follow `docs/superpowers/plans/2026-08-23-node-and-capability.md` lines
2307–2707 for the files, the interfaces, the dataclasses, the
`src/gui/services/__init__.py` re-exports and `__all__` additions, and the
commit step — **as amended by the three corrections above.**

Files:
- Create: `src/gui/services/nodes.py`
- Modify: `src/gui/services/__init__.py`
- Test: `tests/test_gui_nodes.py`

---

## Method

Test-driven. Write the failing test, **run it and watch it fail for the right
reason**, then implement, then watch it pass. A test you never saw fail is not
evidence.

**When you write a fixture, ask what it makes impossible.** Three defects in
this task have now hidden in what a fixture *avoided* rather than in what an
assertion said:

- Task 4: a fake blind to POST, guarding traffic that was mostly POST.
- Task 6 C1: `CliRunner`'s 80-column default and a short label, testing a
  bug about wrapping at narrow widths.
- Task 6 C1's own fix: a discovery stand-in yielding events with **no node
  attached**, so the code path under test never ran at all.

Every one of those tests passed honestly and proved nothing. Before you call a
test done, state to yourself which line of implementation it would catch if
that line were deleted — and where you can, delete the line and check.

## Copy rules apply here too

This is a service layer that returns strings a person will read — `summary`
and `refusal` on every `Outcome`, and `message` on every `ScanEventView`. Read
**§3.1.1 and §3.1.2** of
`docs/superpowers/specs/2026-08-23-node-and-capability-design.md` and obey
them:

- No text may characterise anyone's hardware. Not *slow*, *fast*, *good*,
  *poor*, *powerful*, *limited*, *adequate*, *sufficient*, *plenty*, *only*.
  Report the figure with its unit and stop.
- No text may assume who owns the work, hardware, or network. Not *stays with
  you*, *off your hands*, *your workflows*, *your models*, *my network*. Say
  what happens to the **step**.

`tests/test_node_cli.py` has a `TestCopyRules` class with the spec's word
lists and a word-boundary matcher that handles the *only* ambiguity (§3.2's
approved copy legitimately contains "only checks this computer"). **Reuse that
mechanism — import it or lift it into a shared helper — rather than writing a
second copy that can drift.** Two divergent lists is a defect waiting to
happen; Task 8 will need the same one.

## Environment

Work in the worktree
`/home/flaveon/agentic-workspace/OpenAI_GPT_Builds/Fukasawa-AgentFoundry-Runtime/.claude/worktrees/handoff-master-verification-37e5d2`,
branch `claude/handoff-master-verification-37e5d2`, HEAD `e5b86f5`.

Use `.venv/bin/python`. **The worktree has its own venv and `src` still
resolves to the MAIN CHECKOUT for any plain `python script.py`** — the
editable install points there. `python -c` masks it (cwd joins `sys.path`) and
pytest masks it (rootdir insertion). For any script not run under pytest, use
`PYTHONPATH=$PWD .venv/bin/python script.py`.

Baseline you must not regress: **827 passed, 41 skipped** (~53s). About 40
display-gated tests skip in a plain run; that is expected. Run the full suite
before committing — `src/gui/services/__init__.py` is shared, and the GUI
import-law tests discover service files by glob, so they must accept the new
one.

Do not touch any FROZEN path. Your files are the three named above.

## Constraints

- SPDX header on every new file: `# SPDX-License-Identifier: AGPL-3.0-or-later`
  then `# Copyright (C) 2026 ConcordiaPax LLC`.
- Every function has a docstring; non-developers read this code.
- No network calls at runtime or in tests.
- No hardcoded agent or model names.
- Tk-free by rule (ADR-007 §1): no widget imports, no printing, dataclasses in
  and out.
- If you are unsure whether something belongs in the schema or the runtime, it
  goes in the schema.
- **When in doubt, stop and write a comment explaining what the next step
  requires rather than guessing. Guessing creates non-conformance.**

## Commits

Match the branch's style: a specific subject line, then a body explaining
*why*, in sentences. See `git log e5b86f5 -6`. **No `Co-Authored-By` trailer**
— this branch has zero and the operator's conventions forbid them.

Commit only the three files named above.

## Write a report

Write `.superpowers/sdd/2026-08-23-node-and-capability/task-7-report.md`,
matching `task-5-report.md`'s format. Task 6 had no report and the reviewer
could not tell deliberate decisions from oversights — it cost a round. Say
what you changed, what you decided and **why**, what you deliberately did not
do, and every open question you are handing back.

Do not report anything as done unless you watched a test fail and then pass
for it. An honest "not done, here is the blocker" is worth more than a green
claim someone has to re-verify.
