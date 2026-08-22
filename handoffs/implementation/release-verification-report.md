# Release verification report

**Date:** 2026-08-21
**Verified by:** `claude-opus-5`, phase 8.
**Branch:** `claude/handoff-master-verification-37e5d2` off
`feature/human-cooperative-workflow-runtime`.
**Platform:** Linux 5.15, Python 3.12.13, `uv` 0.11.

> ## This is not the independent verification §11.7 asks for
>
> The master handoff assigns release verification to **Jules**, and the point
> of that assignment is *independence* — a second agent that did not write the
> code checking whether the code does what it claims. This report was produced
> by the agent that wrote most of phase 7, 7b and 8. It cannot supply
> independence by asserting it.
>
> What it does supply: every check §11.7 lists that can be performed without a
> second party, run and recorded, so Jules's pass starts from evidence rather
> than from zero. **Jules's independent pass remains an open Gate G item and an
> operator action** — this agent cannot invoke it.

## Suite

| Invocation | Result |
|---|---|
| `xvfb-run -a pytest -q` (as CI runs it) | **682 passed, 1 skipped** |
| `pytest -q` (no display) | **642 passed, 41 skipped** |

The 41 skips are the display-gated view tests plus the deliberate
adversarial-fixture skip. Run it **both ways**: the plain invocation silently
skips 40 tests that only execute under a display.

Baseline history on this release branch:

| Point | xvfb | no display |
|---|---|---|
| Phase 7 head | 559 | 544 + 15 |
| Phase 7b (§16 complete) | 622 | 582 + 40 |
| Phase 8 (this report) | **682 + 1** | **642 + 41** |

123 tests added since phase 7 head. **No test was weakened, skipped or
`xfail`ed** to reach green. One existing assertion moved — from the text log to
the findings table — and got wider in the move.

## §11.7 checklist

| Task | Status |
|---|---|
| Reproduce baseline | **done** — recorded above, and matches the phase-7 note exactly |
| Create adversarial fixtures | **partial** — three new domain fixtures from the Gate C review; Grok Build's §11.4 pass has still not happened |
| Test every validator rule | **done** — 16 rules, positive and negative each, 130 tests in `test_workflow_rules.py` |
| Test promotion invariants | **done** — `test_workflow_promotion.py` |
| Test serialization round trips | **done** — `test_workflow_contracts.py`, plus new ledger round-trip cases |
| Test old persisted data behaviour | **done this phase** — `test_hardening.py::TestOldPersistedData`, closing the §15.4 gap |
| Test Python/TypeScript fixture compatibility | **void** — no TypeScript exists (defect D1, resolved at Gate A) |
| Test CLI happy and failure paths | **done** — `test_workflow_cli.py`, exit codes 0/1/2/3 each exercised |
| Test desktop service integration | **done** — `test_gui_workflow.py`, including CLI/desktop parity |
| Test offline behaviour | **done this phase** — `test_hardening.py::TestOffline` |
| Test PyInstaller packaging | **partial** — CI builds and smoke-tests a binary on three OSes; no pytest coverage. Phase 9 owns it |
| Produce a verification report | this document |

## What was verified by running it, not by reading it

### The lifecycle end to end

The full pilot sequence was executed against a scratch ledger and every output
in `docs/pilot-walkthrough.md` is real, captured from that run. This is how two
documentation errors were caught before shipping: `accept-risk` takes
`--finding` as an option rather than a positional, and the finding id printed
for a workflow-level finding differs from the one the error message suggests.

Verified behaviours:

- 24 findings on the observed capture, 14 blocking — **and it still saved**;
- promotion **refused** on the unrepaired capture, exit 2;
- 6 findings and 0 blocking after repair, promotion ready;
- promotion advances one step per call and does not repeat a step already taken;
- an override across the `IRREVERSIBLE` floor **refused**, exit 3, with the
  remedy named;
- export **refused** before approval, exit 1;
- 8 steps → 10 states on export, the `AGENT_PREPARED_HUMAN_APPROVED` step
  splitting into agent work, a wait, and a human decision;
- accepting a **blocking** finding refused, exit 3;
- an accepted advisory finding survives re-validation as accepted.

### Clean-environment install

A copy of the tree with no build residue, installed non-editable into a fresh
venv, then run from `/`:

| Check | Result |
|---|---|
| `fukasawa --help` | works |
| All 9 `workflow` subcommands present | works |
| `import src.gui.services` from site-packages | **works — 42 exports** |
| `examples/` bundled in the wheel | **no** — see findings |

The third row is the phase-7b packaging fix confirmed end to end. Before it,
this import raised `ModuleNotFoundError` from every wheel this repository had
ever produced.

### Offline

`socket.socket` and `socket.create_connection` are replaced with raising stubs,
and the whole authoritative lifecycle runs under them: validate → promote ×2 →
assess → build → export. A static check additionally asserts that
`src/kernel/models.py` is the **only** module under `src/` importing network
machinery, and it is not on an authoritative path.

Verified by mutation: a `socket()` call inserted into `validate_workflow` fails
three tests; a `urllib.request` import added to `src/governance/cooperation.py`
or `http.client` to `src/cli.py` fails the static check by name.

> A methodological note worth recording: the first run of that second mutation
> **passed**, and it passed because the anchor string I substituted did not
> exist in the file — the mutation never applied. A green mutation check that
> mutated nothing is indistinguishable from a guard that works. Every mutation
> in this phase was re-run with the change confirmed present in the file first.

## Findings

### 1. `examples/` is not in the wheel — phase 9

`pyproject.toml` ships no package data, so a `pip install` gives you the code
and none of the pilot. The PyInstaller spec **does** bundle it
(`packaging/fukasawa.spec` line 29), so the end-user binary is fine and only the
wheel is affected.

Defensible — a developer installing the wheel has the repository — but §15.7
names "bundled schemas and examples" as a packaging check and this has never
been stated either way. **Phase 9 should decide and document it**, not discover
it.

### 2. Jules's independent pass has not happened — Gate G

See the banner at the top. Operator action; this agent cannot invoke Jules.

### 3. Grok Build's adversarial fixture pass has not happened — §11.4

The Gate C review wrote three fixtures by hand and they are good enough to close
Gate C, but adversarial generation by a different model is a cheap strengthening
that the plan budgeted for and nobody spent.

### 4. Three Jules commits on FROZEN or phase-owned files remain unreviewed

Carried forward, unchanged, and the most substantive item on this list.
`src/runtime/ledger.py` (241 lines, `301ca83`) is the largest.
`src/runtime/state_machine.py` was reviewed in phase 7b and a real latent hazard
was found behind a change that preserved behaviour and passed 559 tests. There
is no reason to assume the other three are cleaner, and "the suite is green" is
already known not to settle it.

### 5. The FROZEN list is still unenforced prose

Branch protection or a CI check on the seven FROZEN paths. It would have
stopped all four unsanctioned edits. Cheap; phase 9.

## Gate status after this phase

| Gate | Status |
|---|---|
| A — architecture approved | met |
| B — contracts stable | met |
| C — validator complete | **met — closed this phase**, see `gate-c-false-positive-review.md` |
| D — accountable promotion | met |
| E — cooperation builder | met |
| F — interfaces complete | met (phase 7b) |
| G — release verified | **open** — items 2–5 above, plus phase 9's packaging and the four remaining §18 documents |

## Reproducing this

```bash
uv venv --python 3.12 .venv && uv pip install -e ".[dev,gui]"
xvfb-run -a .venv/bin/python -m pytest -q     # 682 passed, 1 skipped
.venv/bin/python -m pytest -q                 # 642 passed, 41 skipped
```

A worktree needs **its own** venv. The repository-root one carries an editable
install pointing at the main checkout, so imports resolve there rather than at
your worktree and you will test the wrong tree without noticing.
