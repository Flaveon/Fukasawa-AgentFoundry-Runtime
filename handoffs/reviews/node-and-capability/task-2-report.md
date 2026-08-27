# Task 2 Report: Unit Conversion and Human-Facing Layer

## Scope Completed

Task 2 implements the human-facing interface layer for inference node management — converting machine figures (tokens, bytes, rates) into readable summaries for users, with strict enforcement of two product doctrine rules:

1. **State outputs, never judge them** — no characterization of hardware as slow/fast/good/bad/etc.
2. **Never assume ownership** — avoid possessive language about the user's work; describe what happens to steps.

Additionally, no user-facing string may contain jargon: provenance, scope, capability, vram (and variants), or endpoint.

## Files Created/Modified

**Created:**
- `src/nodes/__init__.py` — Module package with AGPL-3.0 header
- `src/nodes/summary.py` — 159 lines; the complete human-facing conversion layer
- `tests/test_node_summary.py` — 187 lines; full test suite including all parametrized branches

**No files modified** (only created new ones).

## Test Command and Output

```bash
.venv/bin/python -m pytest tests/test_node_summary.py -q
```

**Final Result:**
```
44 passed in 0.08s
```

### Test Suite Breakdown

- **TestUnits** (8 tests): Verify unit conversions
  - Tokens to words (3/4 ratio)
  - Word figures rounded to 2 significant digits
  - Rates as words/second
  - Bytes as GB floor (never claim total)
  - Source labels in plain language

- **TestSummary** (8 tests): Verify panel output
  - Node labels rendered
  - Context length shown in both words and tokens
  - Consequence statement (falsifiable, about input limits)
  - Empty node list states what program does
  - Unreachable nodes filtered out
  - Graphics card state (present/absent/unknown)
  - No consequence when no context length available

- **TestCopyRules** (28 tests): Parametrized across 7 branches
  - Empty list, single node, unreachable, no GPU, unknown GPU, no context, minimal context
  - No judgment words (slow/fast/good/bad/powerful/weak/adequate/plenty/enough/limited/decent)
  - No ownership assumptions (stays with you / your X / off your hands / my network)
  - No jargon (provenance/scope/vram/endpoint/capability)
  - Every branch still states at least one figure (not just passing rules by silence)

## Key Decisions Made

1. **Rounding for rates**: Used `round()` instead of `int()` in `human_rate()` to properly round 39.75 to 40 before two-significant-digit conversion. This matches the expected behavior that 53 tokens/sec × 0.75 words/token = 40 words/second (rounded).

2. **Label naming to avoid jargon**: Changed "Fastest measured speed" to "Measured speed" to avoid the word "fast" which triggers the judgment-word checker (substring match on "fast"). The label now states what is measured without qualitative adjectives.

3. **Graphics card phrasing**: Used "yes, on {node_label} — {vram}" when GPU is present and measured, "not sure" when present but unobserved (None), and "none detected" when absent (False). This avoids predicting performance.

4. **Consequence text**: Derived consequence uses "likely to fail" (falsifiable: exceeding context produces either error or silent truncation) rather than predictions about speed or capability. Only populated when best_context is known; empty otherwise.

5. **Two-significant-digit rounding**: Implemented as count of digits, then round to that factor. Handles both small (<100) and large (>1M) values correctly (e.g., 39→39, 8192→8100, 131072→98000).

## Constraints Satisfied

✓ Python 3.12, `.venv/bin/python` ✓ AGPL-3.0 license headers on all files ✓ Every function has docstring ✓ No modifications to FROZEN files (kernel/, security/, graph.py, bundle.py, state_machine.py) ✓ No new dependencies ✓ Conventional Commits style ✓ No jargon in user-facing output ✓ No ownership assumptions ✓ No hardware judgments

## Concerns

None. All 44 tests pass, including all parametrized branches that enforce the copy rules. The implementation is straightforward, follows the brief exactly, and all formatting constraints are met.

## Verification

- Test suite exercises all code paths with 8 unit tests, 8 summary tests, and 28 parametrized copy-rule tests
- Judgment-word detection verified across 7 node configurations
- Ownership-language detection verified across all branches
- Jargon detection (provenance/scope/vram/endpoint/capability) verified
- Every branch verified to still state a figure (not passing rules through silence)

## Fix Round 1

**Finding from review:** `SummaryRow.source` was never populated in the production path, and provenance belongs to the per-computer card (not this summary panel). Spec §3.6's panel mockup shows figures only.

**Changes made:**

1. **Removed `source` field from `SummaryRow` dataclass** (`src/nodes/summary.py`, lines 91-100)
   - Deleted the `source: str = ""` field
   - Replaced docstring with explanation: sources belong to per-computer card; on this panel each figure is a maximum across computers, so a source label would beg "on which one?"

2. **Fixed spacing in row value** (`src/nodes/summary.py`, line 142)
   - Changed triple space to single space in "Longest input any model takes" row between word estimate and token count

3. **Updated test render method** (`tests/test_node_summary.py`, lines 165-170)
   - Removed `{r.source}` from the formatted string concatenation
   - Added docstring to `_render()` method: "Concatenate all output into one string for rule checking."

4. **Kept `source_label()` exported and tested**
   - Function remains in module (used by per-computer card in a later task)
   - Unit test for `source_label()` still passes

**Test command:**
```bash
.venv/bin/python -m pytest tests/test_node_summary.py -v
```

**Output:**
```
============================= test session starts ==============================
44 passed in 0.11s
```

All 44 tests pass. No changes to test behavior or coverage — only removed dead code path from production and clarified the design intent via docstring.
