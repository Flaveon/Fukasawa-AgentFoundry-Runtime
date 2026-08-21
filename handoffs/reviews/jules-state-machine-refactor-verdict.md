# Verdict: the Jules refactor of `src/runtime/state_machine.py`

**Date:** 2026-08-21
**Decided by:** `claude-opus-5`, on operator delegation ("your call — re-verify").
**Subject:** commit `3d3bea4`, `google-labs-jules[bot]`, 2026-08-05, 128 lines,
merged to `main` via PR and inherited by the feature branch.
**Raised by:** phase 7's completion note, under "New risks or defects".

## The verdict

**Accept the refactor. Harden the seam it left open. Do not revert.**

Reverting would discard a genuine readability improvement to buy back a
guarantee that a five-line change buys back more cheaply and more permanently.

## What the refactor did

`WorkflowRuntime.advance` was one long method holding three paths: no valid
transition, valid transition with missing evidence, and the conforming move.
Jules split the first two into `_handle_invalid_transition` and
`_handle_missing_evidence`, and the third into `_perform_transition`.

The decomposition is correct and the boundaries are the right ones. `advance`
went from ~58 lines to ~15 and now reads as the three cases it is.

## What it broke, which is not behaviour

Both new helpers were typed `-> None` and **raised internally**. `advance`
called them as statements:

```python
if transition is None:
    self._handle_invalid_transition(brief, capsule, to_state, evidence, run)

if transition.evidence_required and not evidence.strip():   # transition is None here
    ...
```

Behaviour was preserved — the helper always raised, so control never reached
line 3. But the *guarantee* moved. Before the refactor, `raise` was inline in
`advance`: the reader saw the stop where the branch was. After it, `advance`
reads as though control continues, and only the helper's body says otherwise.

The hazard that creates: a later maintainer changing a helper to record-and-
return — a completely ordinary edit, and one the `-> None` signature invites —
turns a governed refusal into an `AttributeError` on
`transition.evidence_required`. That is:

* not a `NonConformanceError`, so callers catching one do not catch it;
* not recorded as a non-conformance, so the ledger never learns the attempt
  happened;
* raised five lines away from the branch that caused it.

### Demonstrated, not asserted

Monkeypatching `_handle_invalid_transition` to return instead of raise, against
the real pilot brief and a real ledger:

```
CONTROL  invalid transition -> NonConformanceError  (correct)
MUTANT   invalid transition -> AttributeError: 'NoneType' object has no attribute 'evidence_required'
```

Nothing in the 559-test suite failed on the mutant. The freeze on this file
existed so that nobody would have to re-derive whether the proven runtime's
behaviour had changed; a green suite is not evidence about a guarantee no test
was ever pointed at.

## The fix applied

The helpers are renamed `_refuse_invalid_transition` and
`_refuse_missing_evidence`, typed `-> NonConformanceError`, and **return** the
exception. `advance` raises it:

```python
if transition is None:
    raise self._refuse_invalid_transition(brief, capsule, to_state, evidence, run)

if transition.evidence_required and not evidence.strip():
    raise self._refuse_missing_evidence(brief, capsule, to_state, transition, run)
```

Everything the helpers recorded, they still record — the capsule freezes, the
ledger event and the structured non-conformance record are written, a tracked
run is marked FAILED. Only the stop moved back to where the reader is.

Why return rather than annotate `-> NoReturn`: `NoReturn` documents the
contract but does not enforce it at runtime, and this repository has no type
checker in CI. Returning the exception makes the wrong version *impossible to
write silently* — a helper that returned `None` now fails at the `raise` with a
`TypeError` at the boundary, immediately and loudly.

`tests/test_state_machine.py::TestRefusalIsLocal` holds the shape, including the
mutation as a permanent test.

## Verification

| Check | Result |
|---|---|
| Full suite, xvfb | 622 passed |
| Full suite, no display | 582 passed, 40 skipped |
| `tests/test_state_machine.py` | 11 passed (7 before, 4 added) |
| Golden `graph_fingerprint` tripwire | passing |
| Behavioural diff vs. pre-refactor `advance` | none — same records written, same exception type, same message text |

## The governance question, which is the more important one

Directive §3 lists `src/runtime/state_machine.py` as **FROZEN** and §7 makes
touching it a stop-and-escalate condition. Jules edited it, plus
`src/runtime/ledger.py` (241 lines, `301ca83`), `src/foundry/validator.py`
(`693328b`) and `src/governance/maturity.py` (`0f2d6b4`), across four merged PRs,
with no handoff, note, or register entry.

**The freeze has already been spent and does not come back.** This verdict
accepts the outcome; it does not restore the guarantee. Two recommendations
follow from that, and neither is optional if the remaining freezes are meant to
mean anything:

1. **Review the other three Jules commits the same way.** `ledger.py` at 241
   lines is the largest and the one phase 3 owns; it has had no equivalent
   read. This verdict covers `state_machine.py` only.
2. **Make the ownership rules mechanical.** Directive §3 and
   `file-change-map.md` are prose, and the one non-Claude agent working this
   repository does not read them. Branch protection on the FROZEN paths, or a
   CI job failing a diff that touches them without an accompanying waiver file,
   would bind where prose does not. Cheap, and a natural phase 9 item.

A third, smaller: Jules changes code without changing the contracts that
describe it, which is the exact drift `docs/source-to-contract-map.md` exists to
detect. When code and a document disagree in this repository, check
`git log --author=jules -- <file>` before concluding the document is stale.
