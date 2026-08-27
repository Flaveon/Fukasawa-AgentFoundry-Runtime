# Task 6 Report: the `fukasawa node` command line

This report has two halves. The first describes the original implementation,
which was committed without one — that absence measurably weakened its review,
because the reviewer could not tell which gaps were decisions and which were
oversights, and said so. It is reconstructed from the diff at `209df87`, so it
records what the code does, not what anyone intended. The second half is the
fix round that followed the review.

---

## Part 1 — The original implementation (`209df87`)

### Scope delivered

A `node` sub-app on the existing Typer application, 244 lines in `src/cli.py`
and a 137-line test file. Six commands, matching design §3.7:

- **`node scan`** — the permission question, then discovery, then a summary.
  Non-interactive via `--scope`, `--host`, `--label`, `--yes`, `--json`.
- **`node list`** — every computer on file, plus the "what this means when
  steps run" panel. `--json` for machine consumption.
- **`node show <id>`** — one computer's card: whether it answered, speed,
  graphics card, and every model with its longest input.
- **`node add`** — record a computer by hand, marking label, address and kind
  as `DECLARED`.
- **`node forget <id>`** — remove one.
- **`node consent [--set]`** — show or change how far a scan may reach.

### How it is put together

- `_discover` and `_node_store` are one-line indirections over
  `src/nodes/discovery.discover` and `src/nodes/store.NodeStore`, existing so
  a test can substitute discovery and never open a socket.
- `_SCOPE_FLAGS` / `_SCOPE_WORDS` declare the scope vocabulary once in both
  directions: hyphenated on the command line, underscored in the enum,
  sentences on screen.
- `_scope_from` turns a flag value into a `ScanScope` or exits 1 naming the
  choices.
- `_render_summary` prints `src/nodes/summary.summarise`'s rows and its single
  consequence line. Its docstring records why no provenance column appears:
  each figure is a maximum taken across computers, so "found it" would beg the
  question "on which one?"
- Rendering is delegated throughout — `human_words`, `human_rate`,
  `human_bytes`, `source_label` all come from `src/nodes/summary.py`, so the
  CLI holds no formatting rules of its own.
- Discovery findings are printed one line at a time as the generator yields
  them, per design §3.4, rather than collected and printed at the end.
- Imports inside command bodies follow the deliberate existing style of
  `src/cli.py` (confirmed at review; no change needed).

### What it got right, and what it did not

The register is right: sentences, not terse output, and the vocabulary rules
of §3.1 are visibly observed — no *endpoint*, no *VRAM*, no bare *token*
anywhere on screen. The Task 5 node-id collision fix is relied on rather than
re-implemented.

Three things it did not do, all closed in Part 2: it did not use the
`_emit_json` helper that already existed in the same file for exactly its
`--json` problem; it did not escape any interpolated value, in a file that
escapes 24 times elsewhere; and it wrote the scan permission to disk before
checking whether the chosen scope could be acted on.

Its test file covered `list`, `scan`, `add`, `forget` and `consent`, and
enforced the copy rules on two commands.

### A note on the brief

The Task 6 brief was stale against later work in two places, and the
implementation followed it into one of them.

- It rendered a `SummaryRow.source` attribute that Task 2's review had
  deleted. The implementation did **not** copy this — `_render_summary`
  prints label and value only, with a docstring explaining why. Caught.
- It contained `console.print(jsonlib.dumps(...))` at both `--json` sites.
  This **was** copied verbatim, and is critical finding C1 below. Not caught.

---

## Part 2 — Fix round 1

Eight findings were handed over: two critical, four important, two minor, with
M9 explicitly no-action. All eight are addressed. Two are closed with a
recorded decision rather than a code change, and both are flagged below.

Every fix was driven test-first, and every test was watched fail for the right
reason before the code changed. Where a test asserted behaviour that already
existed (the `show` and permission-prompt coverage), the assertions were
mutation-checked instead — the production code was broken in specific ways and
the tests confirmed red, then reverted, with the tree verified clean after.

### Commits

| Commit | Covers |
|---|---|
| `6b2f749` | C1, I3 |
| `b9d1b39` | C2 |
| `e27671d` | M7, M8 (comment only) |
| `7eecc6d` | I4, I5, I6 |

Nothing outside `src/cli.py`, `tests/test_node_cli.py` and this report was
touched. `209df87` was not amended and nothing was rebased.

### C1 — `--json` emitted unparseable JSON. **Closed** (`6b2f749`)

Both `--json` paths went through Rich, which hard-wraps to the terminal width.
On any terminal narrower than the content a string value was split across
lines and the output stopped being JSON; Rich also read markup inside stored
values, so a label containing `[red]` came back altered and `--json` disagreed
with the YAML on disk.

- `node list` now uses `_emit_json`, the helper at `src/cli.py:1890` whose
  docstring names this exact failure and which is used ten times elsewhere in
  the same file.
- `node scan` uses a plain `print(jsonlib.dumps(...))` instead. `_emit_json`
  indents across several lines, and design §3.7 calls this output a stream of
  one object per line. The reason is commented at the call site.

The old test could not see either bug: `CliRunner` defaults to width 80 and
the fixture label was short. The replacement drives a 60-column window with a
label longer than that, and asserts the parsed label equals the stored label
byte for byte. Both new tests were watched fail with
`JSONDecodeError: Unterminated string`.

### C2 — `local-network` crashed, and stuck. **Closed** (`b9d1b39`)

`--scope local-network` persisted the permission and then reached
`candidate_addresses`, which has no branch for that scope and raises past
every handler. The permission landing first was the worse half: once
`LOCAL_NETWORK` is on file, every later bare `node scan --yes` reads it back
and dies identically, and recovery requires knowing to run `node consent --set
this-machine`, which nothing mentions.

The refusal now fires **before** `store.set_consent`, so nothing unusable is
ever written. It is reachable both ways it was before — the flag and menu
choice 3 — and both are covered. The /24 sweep is **not** implemented; it
remains out of scope for this plan.

The copy, against §3.1.1/§3.1.2:

> Looking at every computer on this network is not built yet.
> To look at one other computer, run `fukasawa node scan --scope named-host --host <address>`.
> To record a computer without looking for it, run `fukasawa node add`.

It states what the program does rather than judging anything, says "this
network" rather than claiming anyone owns it, and points at the two routes
that work — the same shape as the existing `--scope none` refusal pointing at
`node add`.

**Exit code decision: 1, not 3.** The file's documented contract
(`src/cli.py:35`) is `0` success, `1` your input was wrong, `2` understood and
blocked, `3` understood and refused as a matter of doctrine. Nothing here is
refusing anyone anything — the part being asked for does not exist yet. That
is the same condition as naming a scope the program does not recognise, which
`_scope_from` already answers with exit 1. The `--scope none` contract of exit
3 is untouched, and its test still passes.

Four tests, all watched fail: the flag, the menu, the permission file left
alone, and — the one that proves the trap is gone — a later bare scan being
handed `THIS_MACHINE`, checked by recording what discovery was asked for
rather than by exit code, which the stand-in would have answered either way.

### I3 — no `escape()` in 244 new lines. **Closed** (`6b2f749`)

Confirmed by test before fixing: `node add --label "Box [/dim] X"` stored the
node and *then* aborted on its own confirmation line, after which `node list`
aborted permanently on the value already on disk — the primary read command
bricked by data the program itself had written.

Escaped: the summary panel's first row (it lists the labels people chose), the
scan finding line (it quotes model names read off another computer), both
label-and-address headers in `list` and `show`, the model name column, the
`add` confirmation, both "nothing stored called X" sentences, the `forget`
confirmation, and the two argument echoes in `_scope_from` and `node add`'s
kind check.

In the model column the padding is applied before the escaping —
`escape(f'{model.name:<28}')` — so the column still lines up; the backslashes
`escape` adds are not printed.

Two of the five tests initially passed, for the wrong reasons, and were
tightened until they failed: `[b]` is a real Rich tag so it aborts nothing and
merely swallows the brackets, printing a model name the other computer never
reported; and a markup abort surfaces through `CliRunner` as exit 1, which is
the same code the "nothing stored" path returns deliberately. Both now assert
on the text itself.

### I4 — `node show` had no tests. **Closed** (`7eecc6d`)

A `TestShow` class: the figures rendered in words a reader can use (speed,
graphics card, model, longest input), unmeasured figures reading "not sure",
a computer with no models, and a name matching nothing exiting 1 while naming
what was asked for.

These assert existing behaviour, so they were mutation-checked rather than
watched fail: four separate breakages of the rendering (dropping `human_rate`,
hard-coding the graphics card row, dropping the model's longest input, and
dropping the name from the not-found sentence) each turned the class red, and
the file was verified byte-identical afterwards.

### I5 — `TestCopyRules` under-enforced the rules. **Closed** (`7eecc6d`)

Three changes.

**All six commands, not two.** Twelve parametrized cases now cover `list`,
`show`, `consent` (both forms), `add`, `forget`, and `scan` on five paths —
the flag-driven scan, the two refusals, and three of the four menu rungs. The
scan cases reach discovery through a stand-in whose *lines come from
discovery's own `_describe`*, so what is checked is product copy, not copy
invented by the test. No test in the file opens a socket.

**The spec's word list, and only the spec's.** Added *limited*, *sufficient*,
*plenty* and *only* from §3.1.1; added *my network* from §3.1.2; removed
*weak*, which §3.1.1 does not list. A test that invents its own rules stops
being evidence about the rules that exist.

**The `only` problem — the mechanism, and why it is not simpler.** §3.1.1
forbids *only* as a verdict about hardware ("8 GB is only…"), and the same for
*plenty* and *limited*. It does not forbid the ordinary adverb of restriction,
and the spec's own approved copy uses it twice — §3.2's *"Look for it" only
checks this computer* and §3.3's *I check that one only* — precisely to
promise that nothing beyond the granted permission is examined. A plain
`word in output` check fails against the sentences the spec endorses.

The check therefore strips a short, commented allowlist of spec-endorsed
phrases from the output, then matches what remains on **word boundaries**.
Both halves earn their place, and both are held open by their own unit tests
so that an allowlist swallowing every *only* could not pass for one that
works:

- `judgements_in('"Look for it" only checks this computer.')` → `[]`
- `judgements_in("8 GB is only enough for small models.")` → `["only"]`
- `judgements_in("Fastest measured speed  40 words a second")` → `[]`
- `judgements_in("This computer is fast.")` → `["fast"]`

The boundary matching is not incidental: §3.6's *"Fastest measured speed"* is
a comparison between figures rather than a verdict on any one of them, and
`\bfast\b` leaves it alone.

No word was dropped and no approved copy was rewritten. All ten §3.1.1 words
and all five §3.1.2 phrases are enforced.

Five mutations confirmed the widened rules bite, each in the right command:
*plenty* injected into the panel (3 cases red), *only* as a verdict in `show`
(1), *my network* in the new refusal (2), *your models* in `add` (1),
*limited* in the menu (3).

**One honest limitation.** Emptying the allowlist entirely fails only the
discrimination unit test, not any command case — so the allowlist is not
load-bearing against today's CLI copy. That is expected and correct: §3.7's
CLI menu deliberately carries shorter rung labels than §3.3's radio list, so
the CLI does not currently print either endorsed phrase. The mechanism is in
place, and proven to discriminate, for when Task 8 renders §3.2 and §3.3 in
full. It is documented here rather than left to be discovered as dead code.

### I6 — the four-rung permission prompt was untested. **Closed** (`7eecc6d`)

Rule three of §3.1 and the centre of the privacy story, and no test reached it
— every existing scan case passed `--scope` or `--yes` and skipped straight
past. A `TestTheConsentPrompt` class now drives it through stdin: the four
choices offered in sentences, each rung reaching its outcome (this computer;
a named computer, which asks for the address and is handed it; the whole
network, refused; and not looking, exit 3), the bare Enter taking the route
where nothing leaves the machine, and an answer off the menu doing the same.
The chosen permission is checked to be remembered.

Discovery is substituted on every path that reaches it, and what it was asked
to look at is recorded and asserted — exit code alone would not distinguish
the rungs. Four mutations to the menu mapping and its default each turned the
class red.

### M7 — `--yes` did not skip the host prompt. **Closed** (`e27671d`)

`--scope named-host --yes` with no `--host` asked for the address anyway,
which on a closed input ends as `'Address of the computer:Aborted.'` — half a
question, naming nothing that would have answered it. It now exits 1 and says
to pass `--host`. Both routes are covered: the flag, and a bare `--yes` that
reads `NAMED_HOST` off the permission file.

The test asserts the question is *not asked* and that `--host` is named,
because exit 1 alone proves nothing here — the abort also exits 1. Watched
fail on exactly the reported string.

### M8 — "Refused" for a deliberate choice. **NOT closed, deliberately.**

This is a judgement call with a contract attached, and half of it is not mine
to make. The code is unchanged; a comment now sits at the site
(`src/cli.py`, the `ScanScope.NONE` branch) recording the question.

What is clear: two different situations arrive on that line. `--scope none` is
a refusal of something explicitly asked for, exit 3 fits it, and a test holds
that contract. Menu choice 4 — *"Don't look — I'll type it in"* — is not a
refusal of anything; it is a person taking a route this program offers them,
and answering it with "Refused" and a non-zero exit describes them wrongly.

What is not clear, and what stops me: telling the paths apart in code is
trivial, but deciding what the chosen route should then *return* is not. Exit
0 pointing at `node add`, or exit 3 with different words, turns on whether
anything is expected to read that exit code — and nobody has said. Project
doctrine is explicit that guessing here creates non-conformance, so it is
written down instead. **Needs the operator.**

### M9 — function-local imports. No action, as directed.

---

## Test counts and output

| | node CLI file | full suite |
|---|---|---|
| Before this round (`209df87`) | 12 | 789 passed, 41 skipped |
| After (`7eecc6d`) | 49 | 826 passed, 41 skipped |

37 tests added; no test removed, and no existing assertion weakened. The one
existing test that was replaced (`test_json_output_is_machine_readable`) was
kept and joined by a stronger sibling rather than edited.

```
$ .venv/bin/python -m pytest -q
........................................................................ [ 99%]
...                                                                      [100%]
826 passed, 41 skipped in 54.88s
```

```
$ .venv/bin/python -m pytest tests/test_node_cli.py -q
.................................................                        [100%]
49 passed in 0.68s
```

The full suite was run green before each of the four commits. The 41 skips are
pre-existing and display-gated. `tests/test_workflow_cli.py` was watched for
regressions throughout, since `src/cli.py` is shared; there were none.

FROZEN check over the whole round:

```
$ git diff --name-only 209df87..HEAD
src/cli.py
tests/test_node_cli.py
$ git diff --name-only 209df87..HEAD | grep -E "kernel/|security/|schemas/graph|schemas/bundle|generator\.py|state_machine|runtime/bundle" || echo "no frozen path touched"
no frozen path touched
```

Environment: this worktree's own `.venv`, verified to resolve `src` inside
this worktree rather than the repo-root editable install.

---

## Open questions handed back

1. **Spec contradiction, §3.1.1 vs §3.1.2 — needs the operator.** §3.1.1's
   example table (spec line 80) lists *"steps needing more than 6,000 words
   stay with you"* as an **allowed** example of a fact about the program.
   §3.1.2 explicitly **forbids** *stays with you* and gives the replacement
   *"is likely to fail on these computers"*. §3.1.2 is later, more specific,
   and matches the copy actually shipped in `src/nodes/summary.py`, so it was
   treated as governing and the tests enforce it. The §3.1.1 table appears
   stale. **Only the operator should edit a spec, so nothing was changed** —
   this is surfaced, not fixed.

2. **M8, above.** Whether menu choice 4 should be told apart from `--scope
   none`, and what it should return if so.

3. **The allowlist is not yet load-bearing** (see I5). Not a defect; recorded
   so nobody deletes it as dead weight before Task 8 renders §3.2 and §3.3.

4. **Cross-task warning, carried forward from the review.** The Task 7 and 8
   briefs were written from the same plan as this one. Check both for the two
   stale patterns this brief carried — a `SummaryRow.source` attribute that no
   longer exists, and `console.print(jsonlib.dumps(...))` where `_emit_json`
   is correct — before dispatching either.
