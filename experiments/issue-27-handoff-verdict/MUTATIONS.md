# Issue #27 — Mutation Check Log (`src/governance/package_consistency.py`)

Round-2 review finding: the 9 mutations the implementer said were applied
in round 1 were not recorded anywhere, so the reviewer had to write their
own (11) to re-verify the claim. This file is that record, so every
mutation below can be redone exactly, by anyone, without re-deriving them.

**Method:** each mutation is a one-line (or one-block) change to
`src/governance/package_consistency.py`, applied by hand against a saved
copy of the file, run against `tests/test_package_consistency.py` +
`tests/test_package_consistency_rollback.py`, then reverted and diffed
against the saved copy to confirm an exactly clean restoration. All 14
were run together in one pass, immediately before the commit that added
them; the full pass ended "FINAL STATE CLEAN" (`diff` empty).

Line numbers below are as of this commit (the file at this exact commit
is the reference point — they will drift on future edits; match by the
quoted original/mutated text, not the number, if the file has since
changed).

| # | What it breaks | Original line | Mutated to | Caught by |
|---|---|---|---|---|
| M1 | Angela-PASS detection disabled | `if angela.angela_value == "PASS":` | `if False:` | `test_angela_pass_alone_blocks_with_no_shipping_section_at_all`; `test_adversarial_cases_from_independent_review[angela_nbsp]` |
| M2 | Only the FIRST shipping line is checked | `for label, value in shipping.shipping_values:` | `for label, value in shipping.shipping_values[:1]:` | `test_every_shipping_line_is_checked_not_just_the_first` |
| M3 | The "neither field attempted at all" early ABSTAIN is removed | `if not angela.attempted and not shipping.attempted:` | `if False:` | `test_abstain_branch_neither_field_present_isolated_from_amendment_4_on_a_pass_report` (a HOLD-report version of this scenario is now ALSO caught by Amendment 4's own both-fields check, so it no longer isolates this specific branch — the PASS-report test does) |
| M4 | Angela `UNKNOWN` accepted as a normal, non-abstaining value | `if token == "UNKNOWN":` (+ its `return`) | `if False:` | `test_angela_unknown_with_shipping_present_still_abstains` (the shipping-absent variant, `test_angela_unknown_alone_abstains`, no longer isolates this specific branch either, for the same Amendment-4 reason as M3) |
| M5 | Exact-value allowlist loosened back to a `startswith` check (reintroduces the original v1 bug) | `if value.lower() not in _ALLOWED_SHIP_VALUES:` | `if not any(value.lower().startswith(v) for v in _ALLOWED_SHIP_VALUES):` | `test_adversarial_cases_from_independent_review[html_comment_hidden]`, `[ship_trailing_text]` |
| M6 | The blank-line-split guard is removed (reads only the first paragraph of a split section) | `if len(paragraphs) > 1:` | `if False:` | `test_adversarial_cases_from_independent_review[blank_between_bullets]` |
| M7 | The duplicate-Shipping-Decision-section guard is removed | `if len(headers) > 1:` | `if False:` | `test_adversarial_cases_from_independent_review[two_sections]` |
| M8 | The duplicate-Angela-line guard is removed (silently uses the first match) | `if len(matches) > 1:` | `if False:` | `test_adversarial_cases_from_independent_review[multi_angela_second_pass]` |
| M9 | The PASS-report-with-findings guard is removed | `if findings or finding_counts:` | `if False:` | `test_abstain_branch_pass_report_with_findings`; `test_pass_report_findings_shape_variants_from_independent_review[findings_str-...]` |
| M10 | NFKC normalization removed (reverts to raw text matching) | `normalized = unicodedata.normalize("NFKC", text)` / `return normalized.replace(...)` | `return text.replace("\r\n", "\n").replace("\r", "\n")` (no NFKC call at all) | `test_adversarial_cases_from_independent_review[angela_nbsp]`, `[fullwidth_ship]` |
| M11 | Amendment 4's both-fields-required-for-CONSISTENT rule is reverted (brings back the round-2 H1-residual bug) | `if angela.attempted and shipping.attempted:` | `if True:` | `test_consistent_on_hold_requires_both_fields_angela_side`; `test_consistent_on_hold_requires_both_fields_shipping_side`; 14 more `ADVERSARIAL_CASES` entries from `adv2.py` |
| M12 | Report verdict matching case-folded (`"hold"` accepted as `"HOLD"`) | `if verdict not in _VALID_REPORT_VERDICTS:` | `if str(verdict).upper() not in _VALID_REPORT_VERDICTS:` | `test_report_variants_from_independent_review[lower_hold-...]` |
| M13 | The quality-report-missing/malformed ABSTAIN branch is removed | `if report_verdict is None:` | `if False:` | `test_abstain_branch_quality_report_none`; `test_abstain_branch_quality_report_invalid_verdict_value` |
| M14 | The handoff-missing/empty ABSTAIN branch is removed | `if handoff_text is None or not handoff_text.strip():` | `if False:` | `test_nonstr_handoff_text_raises_rather_than_silently_passing` (crashes instead, since `_normalize(None)` raises `TypeError`); `test_abstain_branch_handoff_none` |

## Notes on M3 and M4 (why they needed NEW tests, not just re-running old ones)

Both mutations initially appeared to "survive" against the test suite as
it stood right after the H1-residual (Amendment 4) fix — 0 failures. The
reason in both cases is the SAME: Amendment 4's "both fields required for
CONSISTENT on a HOLD report" check is a strictly WIDER safety net that
happens to also catch the specific gap these two older checks guard
against, when the scenario is tested on a HOLD report:

* M3's scenario (neither field attempted at all) on a HOLD report already
  reaches Amendment 4's `if angela.attempted and shipping.attempted:` as
  `False and False` → `ABSTAIN` — the SAME outcome the removed early
  check would have produced, just via a different code path.
* M4's scenario (Angela `UNKNOWN`, no Shipping section at all) on a HOLD
  report reaches the same Amendment 4 branch as `True and False` →
  `ABSTAIN` even with the UNKNOWN-specific rejection deleted, because the
  Shipping field was never attempted either way.

This does not mean M3/M4 are meaningless mutations — it means the
EXISTING fixtures for them had stopped isolating them once Amendment 4
shipped. The fix was to add a scenario for each where the OTHER mechanism
cannot also produce the right answer by coincidence:

* M3: a **PASS**-report version (`test_abstain_branch_neither_field_present_isolated_from_amendment_4_on_a_pass_report`)
  — the PASS branch never reaches Amendment 4's check at all, so only the
  early "neither attempted" check can produce ABSTAIN there.
* M4: a version where the Shipping Decision section IS present and clean
  (`test_angela_unknown_with_shipping_present_still_abstains`) — both
  fields are "attempted" by Amendment 4's definition, so only the
  UNKNOWN-specific rejection can produce ABSTAIN there.

## Reproducing this

```bash
cd Fukasawa-AgentFoundry-Runtime  # this worktree
cp src/governance/package_consistency.py /tmp/pc_orig.py
# apply one mutation from the table above by hand, e.g.:
sed -i '421s/.*/        if False:  # MUTATION M1/' src/governance/package_consistency.py
.venv/bin/pytest -q tests/test_package_consistency.py tests/test_package_consistency_rollback.py
cp /tmp/pc_orig.py src/governance/package_consistency.py
diff /tmp/pc_orig.py src/governance/package_consistency.py  # must be empty
```
