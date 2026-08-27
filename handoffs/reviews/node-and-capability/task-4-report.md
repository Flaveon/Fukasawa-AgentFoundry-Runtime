# Task 4 Report: Consent-gated streaming discovery

## Scope completed

All six steps of the brief were executed in order:

1. Wrote the failing test file `tests/test_node_discovery.py` verbatim from the brief.
2. Ran it and confirmed the expected `ModuleNotFoundError: No module named 'src.nodes.discovery'`.
3. Wrote the implementation `src/nodes/discovery.py` verbatim from the brief (`DiscoveryEvent`, `candidate_addresses`, `discover`, `ConsentRefused`).
4. Ran the suite and confirmed all 15 tests pass.
5. Deliberately broke the permission guard, confirmed the specific test failed with the expected message, then restored the guard and confirmed all 15 tests pass again. See "Step 5 details" below — this took two attempts because the shipped code has two independent `NONE` checks.
6. Committed `src/nodes/discovery.py` and `tests/test_node_discovery.py`.

No FROZEN paths (`src/kernel/`, `src/security/`, `src/schemas/graph.py`, `src/schemas/bundle.py`, `src/foundry/generator.py`, `src/runtime/state_machine.py`, `src/runtime/bundle.py`) were touched — verified with `git diff --stat` against those paths (empty) both before and after commit.

## Files created/modified

- Created: `src/nodes/discovery.py`
- Created: `tests/test_node_discovery.py`
- No other files modified.

Both carry the required SPDX header (`# SPDX-License-Identifier: AGPL-3.0-or-later` / `# Copyright (C) 2026 ConcordiaPax LLC`) as the first two lines, and every function has a docstring, matching the brief verbatim.

## Exact test command and output

```
$ .venv/bin/python -m pytest tests/test_node_discovery.py -q
...............                                                          [100%]
15 passed in 20.09s
```

Full-suite regression check (no other module was touched, but ran as a safety net):

```
$ .venv/bin/python -m pytest -q
757 passed, 41 skipped in 67.54s (0:01:07)
```

## Step 5: deliberate break — what the failure looked like

The brief's instruction was: "In `src/nodes/discovery.py`, comment out the `if scope is ScanScope.NONE:` block," expecting the `none_opens_nothing_at_all` test to fail with the assertion message "NONE must not open a single connection."

The shipped implementation (as given in the brief, copied verbatim) actually contains **two** independent `NONE` guards:

- one in `discover()` — the early-return that yields a "permission" event and stops;
- one in `candidate_addresses()` — an independent `if scope is ScanScope.NONE: return []`.

**First attempt** — commented out only the guard inside `discover()`:

```
$ .venv/bin/python -m pytest tests/test_node_discovery.py -q -k none_opens_nothing
.                                                                        [100%]
1 passed, 14 deselected in 0.07s
```

This did **not** reproduce the expected failure. `discover()` fell through to `candidate_addresses(ScanScope.NONE, "")`, whose own independent `NONE` guard still returned `[]`, so no candidates were generated and no socket was opened — the test passed unchanged. This is a discrepancy between the brief's step-5 narrative (which implies a single guard) and the actual shipped code (which has two, redundantly).

**Second attempt** — to actually exercise the failure the brief describes, I also commented out `candidate_addresses()`'s guard and, since `NONE` otherwise falls through to the function's final `raise ConsentRefused(...)` (there is no case in that function that maps `NONE` to real candidates), I temporarily merged `NONE` into the `THIS_MACHINE` branch (`if scope is ScanScope.THIS_MACHINE or scope is ScanScope.NONE:`) so real candidate URLs were generated for `NONE`:

```
$ .venv/bin/python -m pytest tests/test_node_discovery.py -q -k none_opens_nothing
F                                                                        [100%]
AssertionError: NONE must not open a single connection
assert ['http://127....:8081/health'] == []
  Left contains 4 more items, first extra item: 'http://127.0.0.1:11434/api/version'
1 failed, 14 deselected in 0.09s
```

This reproduced the exact expected failure message and showed real fetch calls (`http://127.0.0.1:11434/api/version`, `http://127.0.0.1:8081/health`, etc.) being recorded once the guard was genuinely absent — proving the test does catch a real breach of the permission boundary.

I then restored all three edits (both `NONE` guards and the merged branch condition) to their original state and re-ran the full file: `15 passed in 20.09s`, and diffed the restored file against what I originally wrote in step 3 to confirm no residue (`git status --short` shows only the two new, untracked files; no stray comments left in `discovery.py`).

## Decisions made

- Implemented the brief's step-3 code exactly as given, rather than the "Interfaces" summary line at the top of the brief (which mentions a `consent=None` keyword parameter that does not appear anywhere in the actual step-3 implementation code or in the test file). The two are inconsistent; I treated the literal, complete code block in Step 3 — plus the test file, which never references `consent` — as authoritative, per the task instructions ("It contains the complete test file and the complete implementation. Work through its numbered steps in order.").
- For step 5, since literally following "comment out the `if scope is ScanScope.NONE:` block" (singular) did not reproduce the brief's stated expected failure, I disabled both `NONE` guards and temporarily rerouted `NONE` through the `THIS_MACHINE` candidate path to force a genuine socket attempt, in order to fulfill the stated intent of the step (prove the test catches a real breach) rather than stop at a non-reproducing result. All changes were reverted afterward.

## Anything I am unsure about / flagged concerns

- **Redundant `NONE` enforcement is good defense-in-depth, but it means the brief's own step-5 walkthrough (as literally written) does not reproduce the failure it promises against the shipped code.** This is worth the plan owner's attention if step 5 is meant to be a literal, mechanical recipe elsewhere (e.g. in onboarding docs) — it currently requires touching two guards, not one, to demonstrate the property.
- **The `NAMED_HOST` tests are slow (~10s each) due to real network I/O**, not because of any bug I introduced: `discover()`'s `post` parameter defaults to the real `http_post_json` (only `fetch` is mocked in the tests), and `probe_ollama()` unconditionally calls `post(...)` for each listed model. For the `NAMED_HOST` tests, this means a real POST to `http://10.0.0.9:11434/api/show` (a private/reserved test address) is attempted and times out after ~10s before being caught as `OSError` inside `probe_ollama`. It doesn't fail the test (the exception is swallowed) and it doesn't violate the scope boundary (10.0.0.9 is within the granted host), but it is an unmocked real socket call that the `Recorder` fake does not track or report on — worth knowing if these tests are ever run in a network-restricted CI sandbox, where they would hang until timeout rather than fail fast. This is inherent to the brief's own verbatim code/tests, not something I changed.

## Fix round 1

Coordinator review confirmed the two concerns raised in the original report and asked for three fixes plus one cleanup.

### What changed

**`tests/test_node_discovery.py`:**

- Gave `Recorder` a `post(url, payload, timeout=0.0)` method that appends to the same `asked` list as `__call__` and answers `/api/show`-shaped POSTs the same way the real Ollama backend does (`{"model_info": {"llama.context_length": 8192}, "capabilities": []}`), refusing with `OSError` for any host not in `answering` — identical policy to the GET fake. Because `hosts()` derives from `asked`, it now reflects addresses touched by either verb without further changes.
- Passed `post=fetch.post` into every `discover(...)` call in the file (14 call sites), so no test leaves the real `http_post_json` default active. This is what eliminated the two ~10s `NAMED_HOST` tests — the `/api/show` POST that `probe_ollama` makes for the one listed model now hits the fake instead of timing out against a real, unreachable address.
- Added `test_no_permitted_scope_posts_to_an_unpermitted_host` (in `TestPermissionIsHonoured`): scans `NAMED_HOST` against `10.0.0.9` and asserts every recorded host (GET or POST) starts with `10.0.0.9`, naming the POST path explicitly so the intent survives independent of the other scope tests.
- Added `test_none_yields_a_permission_stage_event` (in `TestPermissionIsHonoured`): asserts `discover(ScanScope.NONE, ...)`'s first event has `stage == "permission"`, pinning the *specific* behaviour of `discover()`'s own `NONE` guard rather than only its side effect (no socket opened), which `candidate_addresses()`'s independent guard would also produce on its own. Docstring explains the two guards are deliberate defence in depth.
- Added `test_local_network_is_refused_legibly` (in `TestCandidates`): asserts `candidate_addresses(ScanScope.LOCAL_NETWORK, "")` raises `ConsentRefused` with a message naming the scope (`match="LOCAL_NETWORK"`), covering the declared-but-not-implemented refusal path. This uses the previously-unused `pytest` import.
- Added `ConsentRefused` to the imports from `src.nodes.discovery`.
- Updated the module docstring to explain why `Recorder` fakes both verbs.

**`src/nodes/discovery.py`:**

- Removed the unused `field` import from `dataclasses` (only `dataclass` is used).
- Extended `discover()`'s docstring to note that its `NONE` early return and `candidate_addresses()`'s independent `NONE` guard are deliberate defence in depth, and that `test_none_yields_a_permission_stage_event` is what pins the outer guard specifically.

No other files were touched. No FROZEN paths were touched (verified with `git diff --stat` against the frozen list both before and after committing — empty in both cases).

### Test count

18 tests now (was 15): the original 15, plus `test_no_permitted_scope_posts_to_an_unpermitted_host`, `test_none_yields_a_permission_stage_event`, and `test_local_network_is_refused_legibly`.

### Exact command and output

```
$ .venv/bin/python -m pytest tests/test_node_discovery.py -v --durations=5
============================= test session starts ==============================
platform linux -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0
collected 18 items

tests/test_node_discovery.py::TestPermissionIsHonoured::test_none_opens_nothing_at_all PASSED [  5%]
tests/test_node_discovery.py::TestPermissionIsHonoured::test_none_yields_a_permission_stage_event PASSED [ 11%]
tests/test_node_discovery.py::TestPermissionIsHonoured::test_this_machine_touches_only_loopback PASSED [ 16%]
tests/test_node_discovery.py::TestPermissionIsHonoured::test_this_machine_tries_both_known_ports PASSED [ 22%]
tests/test_node_discovery.py::TestPermissionIsHonoured::test_named_host_touches_only_that_host PASSED [ 27%]
tests/test_node_discovery.py::TestPermissionIsHonoured::test_a_named_host_with_a_port_is_honoured_exactly PASSED [ 33%]
tests/test_node_discovery.py::TestPermissionIsHonoured::test_no_permitted_scope_posts_to_an_unpermitted_host PASSED [ 38%]
tests/test_node_discovery.py::TestCandidates::test_none_has_no_candidates PASSED [ 44%]
tests/test_node_discovery.py::TestCandidates::test_this_machine_is_loopback_on_both_ports PASSED [ 50%]
tests/test_node_discovery.py::TestCandidates::test_a_bare_named_host_tries_both_ports PASSED [ 55%]
tests/test_node_discovery.py::TestCandidates::test_a_full_url_is_taken_as_given PASSED [ 61%]
tests/test_node_discovery.py::TestCandidates::test_local_network_is_refused_legibly PASSED [ 66%]
tests/test_node_discovery.py::TestTheStream::test_events_arrive_before_the_scan_finishes PASSED [ 72%]
tests/test_node_discovery.py::TestTheStream::test_each_event_carries_a_human_message PASSED [ 77%]
tests/test_node_discovery.py::TestTheStream::test_a_found_computer_is_carried_on_the_event PASSED [ 83%]
tests/test_node_discovery.py::TestTheStream::test_the_last_event_is_marked_finished PASSED [ 88%]
tests/test_node_discovery.py::TestTheStream::test_a_stage_failure_keeps_what_was_already_found PASSED [ 94%]
tests/test_node_discovery.py::TestTheStream::test_nothing_found_still_finishes_cleanly PASSED [100%]

============================= slowest 5 durations ==============================
0.00s call     tests/test_node_discovery.py::TestPermissionIsHonoured::test_this_machine_touches_only_loopback
0.00s call     tests/test_node_discovery.py::TestCandidates::test_local_network_is_refused_legibly
0.00s call     tests/test_node_discovery.py::TestPermissionIsHonoured::test_this_machine_tries_both_known_ports
0.00s call     tests/test_node_discovery.py::TestTheStream::test_each_event_carries_a_human_message
0.00s call     tests/test_node_discovery.py::TestPermissionIsHonoured::test_named_host_touches_only_that_host

============================== 18 passed in 0.08s ==============================
```

The file went from 20.09s (round 1) to 0.08s — confirming no test still reaches the real network. Also re-ran the full suite as a regression check: `760 passed, 41 skipped in 48.51s` (up from 757 passed, reflecting the 3 new tests; no failures, no FROZEN paths touched).

### Decisions made

- Passed `post=fetch.post` into every `discover(...)` call, including the `ScanScope.NONE` ones, for consistency — those calls never reach `post` in practice, but leaving the real default active anywhere invites the same class of bug the coordinator flagged.
- Kept `test_no_permitted_scope_posts_to_an_unpermitted_host` as its own named test even though, once every other test also passes `post=fetch.post`, it exercises the same assertion shape as `test_named_host_touches_only_that_host`. The coordinator asked for it by name so the POST-specific intent survives independent of the GET-path tests, which is a legitimate reason to keep the apparent duplication.
- `Recorder.post`'s refusal policy (`OSError` for hosts outside `answering`) mirrors `Recorder.__call__` exactly, so a single `answering` set governs both verbs — no test needs to configure GET and POST permission separately.

### Remaining concerns

None outstanding from this round. The full suite is green, the target file runs in a fraction of a second, and no FROZEN paths were touched.
