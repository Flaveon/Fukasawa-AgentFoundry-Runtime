# Task 5 Report: Storage and endpoint resolution

## Scope completed

Implemented all six steps of the brief exactly as specified, verbatim:

1. Wrote the failing test file `tests/test_node_store.py`.
2. Confirmed it failed before implementation existed (`ModuleNotFoundError`).
3. Wrote `src/nodes/store.py` (`NodeStore`: `load`, `save`, `upsert`, `forget`,
   `set_consent`, `default_path`) and `src/nodes/registry.py`
   (`merged_endpoints`), both copied verbatim from the brief.
4. Ran the tests to green.
5. Confirmed no FROZEN file was touched via the exact grep in the brief.
6. Committed with the exact message given.

## Files created / modified

- Created: `src/nodes/store.py`
- Created: `src/nodes/registry.py`
- Created: `tests/test_node_store.py`
- Nothing else touched. `src/kernel/models.py` was imported from
  (`DEFAULT_ENDPOINTS`, `ModelEndpointRegistry`) but not edited.

## Test command and output

```
$ .venv/bin/python -m pytest tests/test_node_store.py -q
.............                                                            [100%]
13 passed in 0.11s
```

Note: the brief's Step 4 says "Expected: PASS, 14 tests." I counted the test
methods in the brief's own test file by hand: `TestEmptyStore` (2) +
`TestRoundTrip` (3) + `TestUpsert` (5) + `TestEndpointResolution` (3) = 13.
The test file was transcribed verbatim from the brief with no methods added
or removed, so 13 is the correct count for the file as specified — the "14"
in the brief's expected-output line appears to be a miscount, not a sign of
a missing test. Flagging this rather than silently treating it as resolved.

Full regression run, to check nothing else in the tree broke:

```
$ .venv/bin/python -m pytest -q
........................................................................ [  8%]
........................ssss............................................ [ 17%]
.............................ssssssssssssssssssssssssssssssssssss....... [ 26%]
........................................................................ [ 35%]
........................................................................ [ 44%]
........................................................................ [ 53%]
........................................................................ [ 61%]
........................................................................ [ 70%]
........................................................................ [ 79%]
........................................s............................... [ 88%]
........................................................................ [ 97%]
......................                                                   [100%]
773 passed, 41 skipped in 47.39s
```

No failures. The 41 skips are pre-existing and unrelated to this change
(present before this task's files were added).

## Step 5: FROZEN check result

```
$ git status --short | grep -E "kernel/|security/|schemas/graph|schemas/bundle|generator\.py|state_machine|runtime/bundle" || echo "no frozen path touched"
no frozen path touched
```

`git status --short` before the grep showed only the three new files
(`src/nodes/registry.py`, `src/nodes/store.py`, `tests/test_node_store.py`),
all untracked additions — nothing modified, nothing under a FROZEN path.

## Decisions made

- Followed the brief's implementation and test text verbatim — no
  deviations, no added/removed logic, no refactors. Given `src/kernel/models.py`
  is FROZEN and consumed unchanged, and the brief was described as containing
  "the complete test file and the complete implementation," the safest path
  was direct transcription rather than independent re-derivation.
- Confirmed pre-flight that `src/schemas/node.py` already defines
  `InferenceNode`, `ModelCapability`, `HostCapability`, `NodeKind`,
  `Provenance`, `ScanConsent`, `ScanScope` exactly as the brief assumes (all
  present, matching field names and enum values), and that
  `src/kernel/models.py` already has `DEFAULT_ENDPOINTS` (`local-llama`,
  `local-ollama`) and `ModelEndpointRegistry.__init__(self, endpoints:
  Optional[dict[str, dict]] = None)` exactly as described. No surprises there.
- No ruff/mypy configuration exists in this repo (checked `pyproject.toml`
  and for a `ruff` binary), so no additional lint/type-check step was run
  beyond the existing test suite.

## Anything unsure about

- The single discrepancy is the "14 tests" expectation in the brief vs. the
  actual 13 test methods in the verbatim test file (see above). This does not
  affect correctness — every test in the file the brief specified passes —
  but it's worth a human glance in case a 14th test was intended and lost in
  the brief's authoring.
- Everything else matched cleanly: no ambiguity in the upsert rule, the
  endpoint merge order, or the FROZEN-file boundary.

## Fix round 1

The coordinator's review of the initial submission found three defects, all
in the brief's own implementation text (not in transcription): one critical
(silent data loss on a node-id collision), two important (a merge crash on a
documented provenance form, and a preservation test that didn't test what it
claimed). All three are fixed. Nothing under a FROZEN path was touched.

### 1. [Critical] Node-id collision silently discarded a computer

`NodeStore.save()` writes `nodes` as a dict keyed by `node_id`, but
`upsert()` only matched an existing record by `url`. Two in-memory nodes
sharing an id collapsed to one on write, with no error — and this was
reachable today: `src/nodes/discovery.py` built
`node_id=slugify(f"{result.kind.value}-{port}")` from kind and port alone,
so two different machines both running Ollama on the default `11434` both
got the id `ollama-11434`.

Fixed both halves, as the design spec (§6.0) already required:

- **`src/nodes/discovery.py`**: the id is now derived from `host:port`
  (the URL's netloc), not port alone. `http://10.0.0.9:11434` now produces
  `ollama-10-0-0-9-11434` instead of `ollama-11434`, so two machines do not
  collide by construction. The human `label` was left exactly as it was —
  only the id changed. No existing discovery test asserted on a `node_id`
  (checked by grep before editing), so none needed updating for the change
  itself; a new test was added instead (below).
- **`src/nodes/store.py`**: added `NodeStore._with_unique_id()`, called from
  the "not found by URL" branch of `upsert()`. When the incoming node's id is
  already held by a *different* URL, it appends a numeric suffix (`-2`,
  `-3`, ...) until the id is unique, and stores under that id instead.
  `save()`/`load()` were not touched — the fix is entirely in not handing
  `save()` a colliding id in the first place. The URL remains the identity
  for "is this the same computer"; the id is just a name.

Tests added:
- `tests/test_node_store.py::TestNodeIdCollision::test_two_different_computers_with_the_same_id_both_survive`
  — two computers upserted at different URLs with the same starting
  `node_id` both survive a save/load round trip with distinct ids.
- `tests/test_node_store.py::TestNodeIdCollision::test_a_third_collision_gets_the_next_suffix`
  — a third collision gets `-3`, confirming the suffix search doesn't stop
  at `-2`.
- `tests/test_node_discovery.py::TestTheStream::test_two_different_hosts_on_the_same_port_get_different_ids`
  — two separate `discover()` calls against different hosts on the same port
  produce different, host-specific ids.

### 2. [Important] The merge crashed on a documented provenance form

`src/schemas/node.py` documents provenance keys as dotted paths (e.g.
`"host.vram_bytes"`), but `upsert()`'s merge loop did
`setattr(merged, key, ...)` for every `DECLARED` key, which raises
`AttributeError` on a dotted key — there is no attribute named
`"host.vram_bytes"` on `InferenceNode`. The comment justifying the old
behavior referred to an `EDITABLE` constant that doesn't exist anywhere in
this codebase (it belongs to a later task), so the code was effectively
written against something imaginary.

Fixed in `src/nodes/store.py`: the copy loop now skips any key containing a
`.` (`if "." in key: continue`), while the dotted key is still carried
through in the merged `provenance` map via `{**node.provenance, **typed}`,
so the record of what a person declared is not lost — only the (impossible)
attribute copy is skipped. Replaced the old comment with one describing what
is actually true: only a top-level field can be copied across by name, a
dotted key records provenance for a nested value, and nothing in the current
UI produces one.

Test added: `tests/test_node_store.py::TestUpsert::test_a_dotted_declared_key_survives_a_rescan_without_raising`
— a stored node with a `DECLARED` dotted provenance key (`"host.vram_bytes"`)
survives an `upsert()` without raising, and the entry is still present and
still `DECLARED` afterward.

### 3. [Important] The DECLARED-preservation test didn't test what it claimed

`test_a_rescan_preserves_what_a_person_typed` asserted the preserved
*value* (`"Kitchen Box"`) but never checked its provenance. A merge that
kept the value while quietly reverting its provenance to `DETECTED` would
have passed this test — and made the value re-overwritable on the very next
rescan, i.e. exactly the bug the test exists to catch, one scan later.

Fixed: added `assert nodes[0].source_of("label") is Provenance.DECLARED`
(with an explanatory failure message) to the existing test in
`tests/test_node_store.py`. No production code change was needed for this
one — the merge already preserved provenance correctly; the test just
wasn't checking it.

### Commands and output

Targeted run:

```
$ .venv/bin/python -m pytest tests/test_node_store.py tests/test_node_discovery.py -v
...
tests/test_node_store.py::TestEmptyStore::test_a_missing_file_is_no_computers_and_no_permission PASSED
tests/test_node_store.py::TestEmptyStore::test_saving_creates_the_file PASSED
tests/test_node_store.py::TestRoundTrip::test_a_computer_survives_save_and_load PASSED
tests/test_node_store.py::TestRoundTrip::test_the_file_is_readable_yaml PASSED
tests/test_node_store.py::TestRoundTrip::test_an_unknown_field_is_refused_by_name PASSED
tests/test_node_store.py::TestUpsert::test_a_new_computer_is_added PASSED
tests/test_node_store.py::TestUpsert::test_rediscovering_the_same_address_updates_in_place PASSED
tests/test_node_store.py::TestUpsert::test_a_rescan_preserves_what_a_person_typed PASSED
tests/test_node_store.py::TestUpsert::test_a_dotted_declared_key_survives_a_rescan_without_raising PASSED
tests/test_node_store.py::TestUpsert::test_forget_removes_one PASSED
tests/test_node_store.py::TestUpsert::test_forgetting_an_unknown_id_reports_it PASSED
tests/test_node_store.py::TestNodeIdCollision::test_two_different_computers_with_the_same_id_both_survive PASSED
tests/test_node_store.py::TestNodeIdCollision::test_a_third_collision_gets_the_next_suffix PASSED
tests/test_node_store.py::TestEndpointResolution::test_defaults_survive_with_no_computers PASSED
tests/test_node_store.py::TestEndpointResolution::test_a_computer_becomes_a_usable_endpoint PASSED
tests/test_node_store.py::TestEndpointResolution::test_the_mapping_fits_the_existing_registry PASSED
tests/test_node_discovery.py::TestPermissionIsHonoured::test_none_opens_nothing_at_all PASSED
tests/test_node_discovery.py::TestPermissionIsHonoured::test_none_yields_a_permission_stage_event PASSED
tests/test_node_discovery.py::TestPermissionIsHonoured::test_this_machine_touches_only_loopback PASSED
tests/test_node_discovery.py::TestPermissionIsHonoured::test_this_machine_tries_both_known_ports PASSED
tests/test_node_discovery.py::TestPermissionIsHonoured::test_named_host_touches_only_that_host PASSED
tests/test_node_discovery.py::TestPermissionIsHonoured::test_a_named_host_with_a_port_is_honoured_exactly PASSED
tests/test_node_discovery.py::TestPermissionIsHonoured::test_no_permitted_scope_posts_to_an_unpermitted_host PASSED
tests/test_node_discovery.py::TestCandidates::test_none_has_no_candidates PASSED
tests/test_node_discovery.py::TestCandidates::test_this_machine_is_loopback_on_both_ports PASSED
tests/test_node_discovery.py::TestCandidates::test_a_bare_named_host_tries_both_ports PASSED
tests/test_node_discovery.py::TestCandidates::test_a_full_url_is_taken_as_given PASSED
tests/test_node_discovery.py::TestCandidates::test_local_network_is_refused_legibly PASSED
tests/test_node_discovery.py::TestTheStream::test_events_arrive_before_the_scan_finishes PASSED
tests/test_node_discovery.py::TestTheStream::test_each_event_carries_a_human_message PASSED
tests/test_node_discovery.py::TestTheStream::test_a_found_computer_is_carried_on_the_event PASSED
tests/test_node_discovery.py::TestTheStream::test_the_last_event_is_marked_finished PASSED
tests/test_node_discovery.py::TestTheStream::test_a_stage_failure_keeps_what_was_already_found PASSED
tests/test_node_discovery.py::TestTheStream::test_nothing_found_still_finishes_cleanly PASSED
tests/test_node_discovery.py::TestTheStream::test_two_different_hosts_on_the_same_port_get_different_ids PASSED

35 passed in 0.24s
```

Full regression run:

```
$ .venv/bin/python -m pytest -q
........................................................................ [  8%]
........................ssss............................................ [ 17%]
.............................ssssssssssssssssssssssssssssssssssss....... [ 26%]
........................................................................ [ 35%]
........................................................................ [ 44%]
........................................................................ [ 52%]
........................................................................ [ 61%]
........................................................................ [ 70%]
........................................................................ [ 79%]
............................................s........................... [ 88%]
........................................................................ [ 96%]
..........................                                               [100%]
777 passed, 41 skipped in 47.29s
```

777 passed (up from 773 before this round — the 4 new tests), 41 skipped
(pre-existing, unrelated), no failures.

### FROZEN check, repeated after this round

```
$ git status --short
 M src/nodes/discovery.py
 M src/nodes/store.py
 M tests/test_node_discovery.py
 M tests/test_node_store.py
$ git status --short | grep -E "kernel/|security/|schemas/graph|schemas/bundle|generator\.py|state_machine|runtime/bundle" || echo "no frozen path touched"
no frozen path touched
```

### Files changed this round

- Modified: `src/nodes/discovery.py` (host-specific node ids)
- Modified: `src/nodes/store.py` (collision-safe id assignment; dotted-key
  copy skip; comment correction)
- Modified: `tests/test_node_discovery.py` (new test for distinct ids across
  hosts)
- Modified: `tests/test_node_store.py` (new collision tests, dotted-key test,
  strengthened DECLARED-provenance assertion)

### Anything unsure about

- None of the three fixes required touching a FROZEN path; all three lived
  entirely in `src/nodes/`.
- `discovery.py` was created by an earlier task and modifying it here is, per
  the coordinator's note, expected — the id defect lives there, not in
  Task 5's own files.
