# Task 3 Report — Backend probes

## Scope completed

All seven steps from `task-3-brief.md` executed in order:

1. Wrote the failing test file `tests/test_node_backends.py` (verbatim from the brief).
2. Ran it and confirmed the expected failure (`ModuleNotFoundError: No module named 'src.nodes.backends'`).
3. Wrote the implementation `src/nodes/backends.py` (verbatim from the brief).
4. Ran the new test file and confirmed it passes.
5. Updated `tests/test_hardening.py::TestOffline::test_only_the_model_adapter_reaches_the_network` to widen the network-import guard to name `src/nodes/backends.py` alongside `src/kernel/models.py`, with the reason recorded in the assertion message (verbatim from the brief).
6. Ran the hardening suite and confirmed it still passes in full.
7. Committed.

## Files created / modified

- Created: `src/nodes/backends.py`
- Created: `tests/test_node_backends.py`
- Modified: `tests/test_hardening.py` (widened the two-module network-import allowlist)

No other files were touched. `pyproject.toml` was not modified — implementation uses only `urllib.request`/`urllib.error`/`json` from the standard library, per the constraint. `src/kernel/`, `src/security/`, `src/schemas/graph.py`, `src/schemas/bundle.py`, `src/foundry/generator.py`, `src/runtime/state_machine.py`, `src/runtime/bundle.py` were not touched.

## Test commands and output

### New test file

```
$ .venv/bin/python -m pytest tests/test_node_backends.py -q
........                                                                 [100%]
8 passed in 0.16s
```

Note: the brief's Step 4 says "Expected: PASS, 9 tests," but the verbatim test file it specifies in Step 1 contains 8 test methods (`TestOllama` × 6, `TestLlamaCpp` × 1, `TestPorts` × 1). I copied the test file exactly as given rather than adding a 9th test to match the stated count, since the brief says the test file's contents are authoritative ("It contains the complete test file"). All 8 pass. Flagging this discrepancy under "unsure about" below.

Before the implementation existed (Step 2), the same command failed with:

```
ModuleNotFoundError: No module named 'src.nodes.backends'
```

as expected.

### Hardening suite

```
$ .venv/bin/python -m pytest tests/test_hardening.py -q
...............                                                          [100%]
15 passed in 1.18s
```

### Full suite (extra verification beyond the brief's steps)

```
$ .venv/bin/python -m pytest -q
736 passed, 41 skipped in 49.11s
```

## Decisions made

- Followed the brief's code verbatim for both the test file and the implementation — no deviations in logic, structure, or the two API-shape details called out (Ollama's `/api/show` as POST with a JSON body; `gpu_present` staying `None` rather than `False` when `size_vram` is 0 and nothing is loaded, vs. `False` only when llama.cpp positively reports `n_gpu_layers == 0`).
- `ProbeResult.host` defaults via `field(default_factory=HostCapability)`; `HostCapability()` with no args is valid since all its fields have defaults, confirmed by the passing tests.
- Left the `note` field un-cleared on later partial failures (e.g. a successful `/api/ps` call after a failed `/api/tags` call does not overwrite the earlier note) — this matches the brief's code exactly, and the tests only check `note` in the two failure-path tests, so behavior is as specified.
- Commit message and file set for `git add`/`git commit` matched the brief's Step 7 exactly.

## Unsure about / flagged

- The brief's Step 4 states "Expected: PASS, 9 tests" but the verbatim test file from Step 1 defines 8 tests, and 8 is what runs and passes. I did not add a test to reconcile the count, since the brief presents the test file's code as authoritative and complete ("It contains the complete test file and the complete implementation"). Worth a maintainer check in case a 9th test was meant to exist and was dropped when the brief was written.

## Fix round 1

Review found a genuine coverage gap in the brief, not a defect in the implementation: `TestLlamaCpp` exercised only the happy path with `n_gpu_layers` omitted, so neither branch of the `gpu_present` tri-state was tested on the llama.cpp side — the only path in the codebase able to produce `False` — and none of llama.cpp's degradation paths (`/health`, `/props`, `/v1/models` each failing) were covered, unlike the equivalent Ollama paths.

### Added to `tests/test_node_backends.py::TestLlamaCpp`

Six new standalone tests, each with its own self-contained fake `fetch`, in the same style as `ollama_fetch`. The pre-existing `test_reads_context_and_offload` was left unchanged.

1. `test_positive_offload_proves_a_graphics_card` — `n_gpu_layers: 32` ⇒ `gpu_present is True`.
2. `test_zero_offload_is_the_only_way_to_prove_no_graphics_card` — `n_gpu_layers: 0` ⇒ `gpu_present is False` (asserted with `is False`, not truthiness). Comment notes this is the only place in the codebase that can produce `False`, meaning the backend positively reported no offload rather than nothing having been observed.
3. `test_missing_n_gpu_layers_leaves_the_card_unestablished` — `n_gpu_layers` key absent from `default_generation_settings` ⇒ `gpu_present is None`.
4. `test_an_unreachable_server_is_not_ok` (llama.cpp) — `/health` raises `OSError` ⇒ `result.ok` is `False` and `"connection refused"` appears in `result.note`.
5. `test_a_failed_settings_read_still_yields_a_reachable_server` — `/props` raises `OSError` while `/health` and `/v1/models` succeed ⇒ `ok` is `True`, `models` still populated (`["q4.gguf"]`), `context_length == 0`.
6. `test_a_failed_model_list_still_yields_a_reachable_server` (llama.cpp) — `/v1/models` raises `OSError` while `/health` and `/props` succeed ⇒ `ok` is `True`, `models == []`.

### Minor: `probe_ollama` signature

Changed:
```python
post: "Poster" = None,  # type: ignore[assignment]  # defaulted below
```
to:
```python
post: Optional[Poster] = None,
```
and added `Optional` to the existing `from typing import Callable` import in `src/nodes/backends.py`. The runtime default (`post = post or http_post_json`) is unchanged.

### Test commands and output

```
$ .venv/bin/python -m pytest tests/test_node_backends.py -v
============================= test session starts ==============================
collected 14 items

tests/test_node_backends.py::TestOllama::test_reads_version_models_and_context PASSED [  7%]
tests/test_node_backends.py::TestOllama::test_tool_support_is_read_not_guessed PASSED [ 14%]
tests/test_node_backends.py::TestOllama::test_committed_video_memory_proves_a_graphics_card PASSED [ 21%]
tests/test_node_backends.py::TestOllama::test_nothing_loaded_leaves_the_card_unestablished PASSED [ 28%]
tests/test_node_backends.py::TestOllama::test_an_unreachable_server_is_not_ok PASSED [ 35%]
tests/test_node_backends.py::TestOllama::test_a_failed_model_list_still_yields_a_reachable_server PASSED [ 42%]
tests/test_node_backends.py::TestLlamaCpp::test_reads_context_and_offload PASSED [ 50%]
tests/test_node_backends.py::TestLlamaCpp::test_positive_offload_proves_a_graphics_card PASSED [ 57%]
tests/test_node_backends.py::TestLlamaCpp::test_zero_offload_is_the_only_way_to_prove_no_graphics_card PASSED [ 64%]
tests/test_node_backends.py::TestLlamaCpp::test_missing_n_gpu_layers_leaves_the_card_unestablished PASSED [ 71%]
tests/test_node_backends.py::TestLlamaCpp::test_an_unreachable_server_is_not_ok PASSED [ 78%]
tests/test_node_backends.py::TestLlamaCpp::test_a_failed_settings_read_still_yields_a_reachable_server PASSED [ 85%]
tests/test_node_backends.py::TestLlamaCpp::test_a_failed_model_list_still_yields_a_reachable_server PASSED [ 92%]
tests/test_node_backends.py::TestPorts::test_the_two_known_ports_are_declared_once PASSED [100%]

============================== 14 passed in 0.09s ==============================
```

Full suite re-run for regression safety: `742 passed, 41 skipped` (up from 736 passed before this round, consistent with 6 new tests added).
