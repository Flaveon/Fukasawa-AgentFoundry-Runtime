# Release notes

## v1.0 — Human & Cooperative Workflow Runtime

**Status:** release candidate. Gates A–F met; Gate G has two items that need a
human rather than an agent — see [Known limitations](#known-limitations).

### What this release adds

A workflow that involves both people and AI agents fails in a specific way: not
because the model is bad, but because nobody wrote down who is accountable for
what. The gaps were there before any agent arrived. This release adds the layer
that makes you write the workflow down, tells you deterministically where the
accountability holes are, refuses to promote it until they are closed, and only
then asks which steps an agent should touch.

```
map → validate → repair → cooperate → export
```

The existing runtime — state machine, ledger, review gates, kernel, package
generator, bundle format — is **consumed unchanged**. This is a front end to
governance, not a second runtime.

### New capabilities

**Capture.** `HumanWorkflowDraft` records a process as it actually happens,
including unwritten rules, observed exceptions and known pain points. A draft
full of gaps saves, reloads and resumes — refusing to record an unfinished
process would guarantee the tool never learned the truth.

**Validate.** Sixteen deterministic rules (`HW-001`–`HW-016`) across structure,
accountability, information, reasoning load and resilience. Each finding carries
a stable rule id, an exact location, a severity, a blocking policy and a
remediation. **No model is involved**, so the same workflow always produces the
same findings and a finding is arguable rather than an opinion.

> "Blocking" means blocking **promotion**. It never blocks capture, save or
> reload.

**Repair or accept.** Fix a finding, or — for advisory ones — accept it with
your name, the time and a reason, all three mandatory. A blocking finding cannot
be accepted; waiving one would make the gate a formality.

**Promote.** An eight-state maturity ladder, one step per promotion. Promotion
produces a **new artifact** and leaves the source alone, recording who, when,
and under which rule-set and schema versions. Refusals are recorded too.

**Assess cooperation.** Seven executor classes ordered by delegated judgment,
chosen by a published decision table from facts declared on each step. Every
characteristic defaults to `UNKNOWN`, and `UNKNOWN` always resolves toward human
control. Safety floors (irreversible, high risk, sensitive data, undefined
authority) are **one-directional**: a human may always pull work back toward a
person, never push a floored step toward autonomy.

**Build and export.** Approved assignments flatten into the existing
`WorkflowBrief`. A step needing human authorization becomes three states — the
agent's work, a wait, the person's decision — so the approval is somewhere the
work sits and something the ledger records.

### Two surfaces

- **CLI** — `fukasawa workflow {init,validate,findings,accept-risk,promote,assess-cooperation,build-cooperative,export-agent-brief,status}`, with `--json`, stable exit codes (`0` ok, `1` user error, `2` blocking findings, `3` doctrine refusal) and no stack traces on ordinary mistakes.
- **Desktop** — the CustomTkinter Workflow tab covers all fifteen §16 capabilities, including a guided step editor whose advice beside each field is read live from the rule registry, findings grouped by severity and location, a cooperation table, and mandatory-reason dialogs for accepting a risk and overriding an executor.

Both call **the same service functions**. Neither owns a rule, and `TestParity`
asserts they reach identical results, including identical refusals.

### Pilot

`examples/workflows/substack-publication/` carries a real workflow with real
problems: **24 findings, 14 blocking**. After repair, 6 findings and 0 blocking
— all six the unwritten rules the capture honestly admitted to. Walk it with
`docs/pilot-walkthrough.md`, where every command was executed and every output
is real.

### Upgrading

**No manual migration.** The ledger's DDL is additive; an older `fukasawa.db`
opened by this build gains the new tables empty and keeps every row.
`docs/migration-notes.md` has the details and the two rules that govern future
changes.

Contracts are at `schema_version` 1 and the rule set at version 1, both recorded
on every persisted artifact so an audit can tell which logic produced it.

### Fixed in this release cycle

- **The built wheel was missing `src/gui/services/`.** A hand-written package
  list was not updated when phase 7 split that module into a package, so every
  wheel installed a GUI that could not import its own service layer — invisible
  to a green suite, which runs from the source tree. Packages are now discovered
  and a test builds a real wheel and reads its manifest.
- **Bundled examples were unreachable from the binary.** All 39 files were in
  the executable and every documented example command failed with "No such
  file". `src/resources.py` resolves them, with the working directory always
  winning.
- **HW-014 matched ambiguous terms inside longer, precise words** — "goods
  receipt", "cleanroom", "completeness" were reported as vague. The term
  boundary was anchored on the leading edge only.
- **The state machine's refusal path lost its local guarantee.** A
  behaviour-preserving refactor moved the `raise` into helpers typed `-> None`,
  leaving `advance` reading as though control continued past them. The helpers
  now return the exception and the caller raises it.
- **The rule catalog claimed to be generated. It was not**, and no generator
  ever existed, so "cannot drift from the code" rested on memory. A test now
  enforces it.

### Known limitations

- **Jules's independent verification pass has not happened.** Master handoff
  §11.7 assigns release verification to a second agent *for the independence*;
  the agent that wrote most of this cannot supply that by asserting it.
  `handoffs/implementation/release-verification-report.md` records every check
  that does not need a second party. **Open Gate G item, operator action.**
- **Three commits on phase-owned files remain unreviewed** —
  `src/runtime/ledger.py` (241 lines) foremost. The one that *was* reviewed
  turned out to have moved a real safety property while preserving behaviour and
  passing 559 tests, so "the suite is green" is known not to settle this.
- **Windows and macOS binaries are built and smoke-tested by CI but not
  hand-verified.** Linux is verified end to end — see `docs/packaging-guide.md`.
- **A bare wheel install does not ship `examples/`.** Deliberate; the reasoning
  is in the packaging guide. Use a checkout or the binary for the pilot.
- **HW-013 and HW-014 have a measured residual.** "wiped **clean** with IPA",
  "the **quality** inspection report", "the cache **remembers**" still fire.
  Both rules are non-blocking for exactly this reason, and
  `handoffs/reviews/gate-c-false-positive-review.md` records why each fix was
  rejected.
- **Old-version load is tested against one schema version.** The tests pin
  current behaviour so the first real migration changes it deliberately.
- **No TypeScript.** Master handoff §3 describes a mixed Python/TypeScript
  runtime; this repository has never had any. Resolved at Gate A as defect D1 —
  JSON Schema export is the seam for any future consumer.
- **You cannot register your own inference nodes from the product, and an
  endpoint has no capabilities.** This is the largest known gap and it is a
  product one, not a defect: the runtime resolves *named* endpoints from
  `~/.fukasawa/model_endpoints.yaml`, but adding one means hand-writing YAML,
  and an endpoint is only a name, a kind and a URL. Nothing therefore checks
  whether the machines you actually own can run a step the cooperation layer
  just said an agent could perform. Those are two different claims and this
  release only makes the first. See *Known gaps* in the README and the
  **Node library** entry in `tasks/backlog.md`.

### Deliberately not built

Not a multi-agent framework, not a swarm, not a node-canvas editor, not a
marketplace, not an orchestration framework, and no LLM in any authoritative
path — validation, promotion eligibility, classification, export and persistence
are all deterministic.

**Not to be confused with the node library**, which is *not* in this list: it is
wanted and not yet built. See *Known limitations*.

### Verifying this release

```bash
uv venv --python 3.12 .venv && uv pip install -e '.[dev,gui]'
xvfb-run -a .venv/bin/python -m pytest -q     # 694 passed, 1 skipped
.venv/bin/python -m pytest -q                 # 654 passed, 41 skipped
```

Run it **both ways**: the plain invocation skips 40 view tests that only execute
under a display.

### Licence

AGPL-3.0-or-later. Every source file carries the SPDX header.
