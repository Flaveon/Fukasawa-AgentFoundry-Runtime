# SDD ledger — plan: docs/superpowers/plans/2026-08-23-node-and-capability.md

Task 1: complete (commits 17d215f..c0aabfa, review clean)
Task 1: minor (deferred): max_context_length and ScanConsent.granted have no direct test — both are exercised by Tasks 2 and 5-7, so coverage arrives downstream. Final review to confirm.
Task 2: fix round 1/5 (4 addressed, 0 open — dead SummaryRow.source removed per spec §3.6; commits fd0a6b0..915387d)
Task 2: complete (commits c0aabfa..915387d, review clean)
Task 3: fix round 1/5 (3 addressed, 0 open — llama.cpp tri-state + degradation coverage, the only path that can produce gpu_present=False; commits 46deb37..eb8aff3)
Task 3: complete (commits 8e15b83..eb8aff3, review clean)
Task 3: minor (deferred): ProbeResult.note is overwritten by whichever late-stage failure lands last; diagnostic only.
Task 3: minor (deferred): MAX_MODELS_EXAMINED=12 truncation has no test.
Task 4: fix round 1/5 (4 addressed, 0 open — CRITICAL: privacy tests could not see POST traffic and made real outbound calls; Recorder now records both verbs into one asserted set. 20.09s -> 0.08s, hermetic under a socket block I verified independently; commits c85f0f9..5a212bc)
Task 4: complete (commits eb8aff3..5a212bc, review clean)
Task 5: fix round 1/5 (3 addressed, 0 open — CRITICAL: node-id collision silently dropped a computer; discovery ids now host-derived and NodeStore suffixes collisions. Reproduction independently re-run and now keeps both; commits fe20d56..3d81d36)
Task 5: complete (commits 5a212bc..3d81d36, review clean)
Task 5: minor (deferred): upsert compares URLs as exact strings — no scheme/trailing-slash canonicalisation, so semantically identical addresses read as different computers.

--- SESSION PAUSED 2026-08-24, operator request (context high) ---
Task 6: IMPLEMENTED BUT NOT REVIEWED (commit 3d81d36..HEAD).
  A dispatch was interrupted before writing task-6-report.md or committing.
  I committed the work so it survives; it is green (12 new tests, full suite
  789 passed / 41 skipped, no FROZEN path) but has had NO task review and has
  NO implementer report.
  [SUPERSEDED 2026-08-25 — this instruction has been carried out. Do not act on
  it. See the RESUME HERE block at the end of this file.] Original text: "do not
  re-dispatch a Task 6 implementer. Generate a review package over the Task 6
  commit and dispatch the task reviewer. If it needs a report, ask a fresh
  implementer to write one from the diff."
Remaining after that: Task 7 (GUI service layer), Task 8 (Environment tab),
  Task 9 (doctrine tests, docs, phase note), then the final whole-branch review.

--- 2026-08-25 01:59 UTC ---
Task 6: review package generated and reviewer DISPATCHED. Verdict not yet in.
  Package: .superpowers/sdd/2026-08-23-node-and-capability/review-3d81d36..209df87.diff
    (423 lines; header + commit list + --stat + full diff, same format as the
    nine earlier packages in this directory).
  Range reviewed: 3d81d36..209df87. No implementer was re-dispatched; 209df87 is
    untouched.
  Reviewer brief additionally carried: the no-implementer-report caveat; spec
    §3.1.1/§3.1.2 copy rules with a required mutation check on TestCopyRules
    (confirm the mutation landed before trusting red, confirm the revert before
    finishing); the three defects this loop already caught (non-hermetic privacy
    tests blind to POST, the node-id collision that silently deleted a computer
    — pointed at `node add`'s slugify(label) id derivation, which is the same
    hazard one layer up — and /api/show being a POST); the worktree-venv trap;
    read-only discipline; the FROZEN-path check.
  Open question handed to the reviewer, not yet answered: task-6-brief.md Step 4
    says "13 tests" but the classes it lists total 12, and the commit claims 12.
    Probably the brief's arithmetic; the reviewer was asked to confirm against
    the actual file rather than assume.

  [SUPERSEDED — the verdict arrived. See the 02:04 block below.]

--- 2026-08-25 02:04 UTC ---
Task 6: REVIEWED. Verdict NOT READY — with fixes. 2 critical, 4 important,
  3 minor, 0 addressed so far. Reviewer confirmed the suite claim exactly
  (789 passed / 41 skipped in 51.77s; 12 new tests in 0.32s, so the brief's
  "13" was its own arithmetic error) and confirmed no FROZEN path is touched.
  Tests are hermetic (Task 4 defect not repeated) and the Task 5 collision fix
  is correctly relied on rather than re-implemented (verified: two labels that
  slugify alike both survive).

  I independently re-verified both criticals before recording them:
  C1  Both `node --json` paths use console.print(jsonlib.dumps(...)) at
      src/cli.py:1473 and :1499. Rich hard-wraps to terminal width, so the
      output is unparseable on a narrow terminal and Rich also eats markup in
      stored labels, making --json disagree with the YAML. src/cli.py:1890
      already defines _emit_json, used 10x elsewhere in this same file, whose
      docstring names this exact failure. The helper was simply not used.
      The passing test hides it: CliRunner defaults to width 80 and the
      fixture label is short, so the test cannot see this class of bug.
  C2  `node scan --scope local-network` persists consent at src/cli.py:1466
      and THEN crashes: candidate_addresses (src/nodes/discovery.py:83) has no
      LOCAL_NETWORK branch and falls through to `raise ConsentRefused`, which
      nothing catches. Because the consent write lands before the crash, the
      state is sticky — every later bare `node scan --yes` reads the stored
      LOCAL_NETWORK and crashes identically. Recovery needs `node consent
      --set this-machine`, which nothing tells the person to run.
      The plan promised the opposite, at
      docs/superpowers/plans/2026-08-23-node-and-capability.md:3142 — "Task 6's
      _scope_from accepts it, so the refusal is legible rather than a crash."
      The legible refusal was never written. Also reachable from interactive
      menu option 3 (src/cli.py:1444).

  Important: (I3) zero escape() calls in 244 new lines while the rest of
    src/cli.py uses it 24x — a label or a REMOTE SERVER's model name containing
    Rich markup crashes the print, and `node list` then crashes permanently on
    the stored value; (I4) `node show` has no tests at all, one of the six
    deliverable commands; (I5) TestCopyRules covers only 2 of 6 commands and
    its word lists do not match spec §3.1.1/§3.1.2 — missing "limited",
    "sufficient", "plenty", "only" and ownership phrase "my network", while
    adding "weak" which the spec does not list; (I6) the four-rung consent
    prompt (rule three, the privacy centerpiece) has no test on any path.
  Minor: (M7) --yes still prompts for --host; (M8) "Refused" + exit 3 is the
    wrong response to interactive option 4, which is a choice, not a refusal;
    (M9) function-local imports checked and confirmed consistent with the
    file's existing deliberate style — no change needed.

  Mutation check on TestCopyRules was performed and reverted, in memory, tree
    verified clean before and after: 3 mutations, all turned it red, baseline
    green after revert. So the assertions genuinely bite — for the 2 commands
    they cover. They are blind to `show` and `scan`.

  Reviewer could not determine whether the local-network refusal and the
    narrowed copy-rule word lists were deliberate or missed, because there is
    still no implementer report. Both were copied verbatim from the brief,
    which suggests neither was a considered decision.

  CROSS-TASK WARNING: the brief for this task was stale in two places the
    implementer had to work around or fell into — _render_summary's row.source
    (correctly caught: Task 2's review had removed SummaryRow.source) and both
    console.print(jsonlib.dumps(...)) call sites (not caught). Task 7 and 8
    briefs were written from the same plan. CHECK THEM for the same two
    patterns before dispatching either.

  [SUPERSEDED — operator authorised the fix round at 02:30. See below.]

--- 2026-08-25 02:30 UTC ---
Task 6: FIX ROUND DISPATCHED, operator-authorised. Outcome not yet in.
  Scope handed to the fixer: C1, C2, I3, I4, I5, I6, M7, M8. M9 explicitly
  no-action (function-local imports confirmed consistent with file style).
  Constraints given: TDD with the failure watched before the fix; changes
  confined to src/cli.py and tests/test_node_cli.py; must not regress the
  789/41 baseline; separate commits per concern; no Co-Authored-By trailer
  (this branch has zero, and operator convention forbids them); must not
  implement the /24 sweep, which is out of scope for this plan.
  Also asked to write the missing task-6-report.md, covering the original
  implementation reconstructed from the diff plus its own fix round — its
  absence measurably weakened the review.

  TWO TRAPS I FLAGGED TO THE FIXER, worth knowing regardless of outcome:

  (a) SPEC CONTRADICTION, unresolved, operator's call.
      §3.1.1's example table (spec line 80) lists "steps needing more than
      6,000 words STAY WITH YOU" as an ALLOWED example. §3.1.2 explicitly
      FORBIDS "stays with you" and gives the replacement "is likely to fail on
      these computers". §3.1.2 is later, more specific, and matches what the
      operator actually said, so it governs — but the §3.1.1 table is stale.
      The fixer was told to surface it, NOT to edit the spec. Only the
      operator should change a spec. THIS IS STILL OPEN.

  (b) "only" cannot be substring-matched. §3.1.1 forbids "only" as a
      judgement about hardware ("8 GB is only..."), but the spec's own
      approved §3.2 first-run copy reads '"Look for it" only checks this
      computer unless you say otherwise' — a correct adverb. A blunt
      `if word in output` check over the four words I5 wants added (limited,
      sufficient, plenty, only) will fail against copy the spec endorses.
      The fixer was told to build a discriminating mechanism and comment it,
      or to leave a word out and say so — never to quietly drop words or
      quietly rewrite approved copy to make a test pass.

  [SUPERSEDED — the fix round ran. See the 2026-08-26 block below.]

--- 2026-08-26 01:02 UTC ---
Task 6: fix round 1/5 (7 addressed, 1 open by decision — commits
  209df87..7eecc6d, four commits: 6b2f749 json+markup, b9d1b39 local-network,
  e27671d --yes/host, 7eecc6d test coverage).
  C1 closed, C2 closed, I3 closed, I4 closed, I5 closed, I6 closed, M7 closed.
  M8 NOT closed, deliberately — see below. M9 no action, as directed.

  I re-verified the following myself rather than taking the report's word:
    - 4 commits exist; HEAD 7eecc6d; working tree clean.
    - Range touches ONLY src/cli.py (+93) and tests/test_node_cli.py (+480),
      547 insertions / 26 deletions. No FROZEN path. Nothing else committed.
    - Full suite run independently: 826 passed, 41 skipped in 53.57s. Matches
      the reported figure exactly. Node CLI tests 12 -> 49.
    - C1: node list now uses _emit_json (src/cli.py:1553); node scan uses a
      plain print (src/cli.py:1525) with a comment saying why _emit_json's
      indent=2 is wrong for a one-object-per-line stream.
    - C2: the refusal fires at src/cli.py:1498, BEFORE the set_consent write
      at src/cli.py:1513. The stickiness is gone, not just the traceback.
      Message states what the program does and names two working
      alternatives; no judgement, no ownership claim. Reasoning commented
      at the call site.

  Fixer's own honesty notes, carried forward because they matter:
    - I4 and I6 assert behaviour that already worked, so there was no genuine
      red to watch. Mutation-checked instead: 4 mutations each, all red, tree
      verified byte-clean after revert. I5 got 5, each red in the right
      command.
    - Two I3 tests initially passed for the WRONG reason and were tightened
      until they failed first: `[b]` is a real Rich tag that aborts nothing
      and silently eats brackets, printing a model name the remote never
      sent; and a markup abort surfaces as exit 1, the same code the
      "nothing stored" path returns on purpose.
    - I5 LIMITATION, do not let this be quietly deleted: the allowlist
      mechanism is proven to discriminate but is NOT yet load-bearing.
      Emptying the allowlist fails only its own unit test, no command case,
      because today's §3.7 CLI menu carries shorter rung labels than §3.3's
      radio list, so neither endorsed phrase is currently printed. It becomes
      load-bearing at Task 8. Do not remove it as dead code.

  DECISIONS TAKEN (both defensible, both reversible, flagging for the record):
    - C2 exits 1, not 3. src/cli.py:35 documents 1 as "your input was wrong"
      and 3 as "understood and refused as a matter of doctrine". Nothing is
      refusing anyone; the feature does not exist yet — the same condition as
      an unrecognised scope, which already exits 1. The --scope none -> 3
      contract is untouched and its test still passes.
    - I5 discrimination is allowlist-strip then \b word-boundary match. The
      allowlist holds ONLY the two phrases the spec itself writes and
      endorses (§3.2 "only checks this computer", §3.3 "I check that one
      only"). All ten §3.1.1 words and all five §3.1.2 phrases now enforced.
      No word dropped, no approved copy rewritten.

  STILL OPEN, NEEDS THE OPERATOR:
    1. The §3.1.1 / §3.1.2 "stays with you" contradiction (trap (a) in the
       02:30 block). Tests enforce §3.1.2. The spec was NOT edited — only the
       operator should change a spec.
    2. M8: "Refused" + exit 3 for interactive option 4, which is a choice and
       not a refusal. Splitting the paths is trivial; deciding what the
       chosen route should RETURN turns on whether anything reads that exit
       code, and nobody has said. Code left as is, question written at the
       site, per CLAUDE.md's rule against guessing.

  task-6-report.md IS WRITTEN (18KB) but is NOT committed — .superpowers/ is
    gitignored and zero files under it are tracked, including task-5-report.md.
    The fixer matched the existing convention rather than force-adding one
    divergent file. It dies with the worktree, like the ledger and the briefs.

  [PARTLY SUPERSEDED — C1 turned out NOT to be fully closed, and two more
  commits have landed since. See the 2026-08-26 02:36 block below. The
  review-209df87..7eecc6d.diff package is now STALE: it covers only part of
  the fix range.]

--- 2026-08-26 02:36 UTC ---
Operator reviewed the fix range by asking what still needed fixing, rather
than dispatching a reviewer over it. Two things came out of that, both now
committed by me directly (no subagent). HEAD is now e5b86f5.

  adc76e3  docs: spec §3.1.1 table brought into line with §3.1.2.
    OPERATOR-AUTHORISED, operator's own decision. The "stays with you"
    contradiction recorded as trap (a) in the 02:30 block is now CLOSED.
    The table row reads "steps needing more than 6,000 words are likely to
    fail on these computers", with a note underneath saying §3.1.2 governs
    and that being a fact about the program does not exempt copy from the
    ownership rule.

  e5b86f5  fix: C1 WAS NOT FULLY CLOSED by the fix round. Reopened and now
    closed properly.
    `node scan --json` still wrote human text into the stream: a blank line
    before the first object (console.print("") ran unconditionally), and the
    whole summary panel after the objects whenever the scan FOUND something
    (_render_summary was not guarded on as_json). Seven non-JSON lines on
    every SUCCESSFUL scan — the normal case, not an edge case. Confirmed
    empirically with a probe outside the suite before changing anything.
    Both now guarded on `not as_json` (src/cli.py:1516 and :1552).

    WHY THE FIX ROUND'S OWN TEST MISSED IT — this is the recurring pattern
    in this task and worth naming: the stand-in yielded DiscoveryEvents with
    NO node attached, so `found` stayed empty and the panel never ran, and
    the test filtered blank lines out before parsing. A fixture that avoids
    the condition under test. That is the SAME SHAPE as the original C1
    blind spot (CliRunner's default width + a short label) and the same
    shape as the Task 4 defect (a fake that could not see POST). Three
    times now. When reviewing anything in this task, check what the fixture
    AVOIDS, not only what it asserts.

    SECOND TEST WAS REQUIRED, and this is the part worth keeping: NOTHING in
    the suite asserted the summary panel is ever printed at all. Nothing
    matched "What this means when steps run". So `if found and not as_json`
    and `if False` were indistinguishable — the guard could have deleted the
    feature outright and the whole suite would still have been green. Added
    a human-mode scan test asserting the panel and a figure with its unit.
    Mutation-checked: mutation confirmed present in the file by grep, test
    red, revert verified byte-identical by md5. Do not delete that test; it
    is the only thing telling a guard apart from a deletion.

  Suite after: 827 passed, 41 skipped (was 826 — the one new test). Human
  scan path verified by hand to still print blank line, findings, and panel.

  ENVIRONMENT CORRECTION, sharper than the handoff's version: this worktree
  HAS its own .venv and `src` STILL resolves to the MAIN CHECKOUT for any
  plain `python script.py`. The editable install points at the main tree.
  `python -c` masks it (cwd goes on sys.path) and pytest masks it (rootdir
  insertion). A probe script failed with "No module named 'src.nodes'" until
  run as `PYTHONPATH=$PWD .venv/bin/python script.py`. Anything not run under
  pytest needs PYTHONPATH pinned. My earlier "venv verified clean" was true
  for pytest only.

  [Task 6 closed out here. Task 7 began at 02:46 — see the block at the end.]

  RESUME HERE (Task 6 portion, still accurate): Task 6 code is believed
  complete. HEAD e5b86f5 as of that entry.
  Do NOT re-dispatch a fixer or an implementer for Task 6.
  The existing review-209df87..7eecc6d.diff is STALE — it predates adc76e3
  and e5b86f5. If a re-review is wanted, generate a FRESH package over
  209df87..e5b86f5 and dispatch a reviewer over that. As of this entry the
  operator had NOT authorised a re-review dispatch and had asked to move to
  Task 7 instead; ask before dispatching. Hand any such reviewer: this block,
  task-6-report.md, and the still-open M8 question so it is not re-reported
  as new.
  STILL OPEN AND NEEDING THE OPERATOR: M8 only (trap (a) is now closed).
  Interactive menu option 4 still answers a deliberate choice with "Refused"
  and exit 3; the question is written at the call site in src/cli.py.
  After Task 6 closes: Task 7 (GUI service layer), Task 8 (Environment tab),
  Task 9 (doctrine tests, docs, phase note), then the final whole-branch
  review. Before dispatching Task 7 or 8, check their briefs for the two stale
  patterns Task 6's brief carried — a removed SummaryRow.source, and
  console.print(jsonlib.dumps(...)) where _emit_json is correct.

NOTE ON THIS FILE'S DURABILITY: .superpowers/ is gitignored (.gitignore:14).
  This ledger, all six task briefs, and every review-*.diff exist ONLY on this
  worktree's disk — not in git, not on the remote. Removing this worktree
  destroys the resume map. Decide deliberately before any worktree cleanup.

--- 2026-08-26 02:46 UTC ---
Task 7 (GUI service layer): IMPLEMENTER DISPATCHED, operator-authorised.
  Brief written at task-7-brief.md (it did not exist; briefs are generated
  per task from the plan). Base is plan lines 2307-2707. Outcome not yet in.

  I CHECKED THE PLAN AGAINST CURRENT SOURCE BEFORE DISPATCHING, which is what
  the Task 6 cross-task warning asked for. The two stale patterns that broke
  Task 6's brief (removed SummaryRow.source, console.print(jsonlib.dumps))
  appear ONLY in the plan's Task 6 range, lines 1886-2307. Tasks 7 and 8 are
  clean of both. Confirmed: Task 7's summary_rows line reads
  [(r.label, r.value) ...] and never touches .source.

  BUT THE PLAN'S TASK 7 IS WRONG IN THREE OTHER PLACES. All three are
  corrected in the brief, which is marked authoritative over the plan text:

  C1 (critical) THE PLAN'S OWN TEST WOULD MAKE REAL NETWORK CALLS.
    The plan's service scan() takes only fetch= and forwards only fetch.
    discover() takes fetch AND post, keyword-only (discovery.py:114-121), and
    probe_ollama does `post = post or http_post_json` (backends.py:99) then
    POSTs /api/show for every model listed (backends.py:131). The plan's test
    returns a model named "m" from /api/tags and injects only fetch — so it
    would POST to a real address. THIS IS THE TASK 4 DEFECT VERBATIM, the one
    that cost a review round and took the discovery suite 20.09s -> 0.08s.
    Brief requires: scan() accepts and forwards BOTH; the test injects both
    and asserts on recorded calls across both verbs; reuse the Recorder
    already in tests/test_node_discovery.py rather than writing a second one.

  C2 (important) THE SERVICE HAS TASK 6'S LOCAL_NETWORK HOLE.
    Plan's scan() guards only NONE. candidate_addresses raises ConsentRefused
    for LOCAL_NETWORK (discovery.py:83) because the /24 sweep is deliberately
    not built this phase. At the CLI this was a review Critical — uncaught
    traceback plus a persisted unusable consent. Task 6 fixed it for the CLI
    only (cli.py:1480-1498). Task 8 is about to build a tab on this service.
    Brief requires a refusal ScanEventView, and NOT implementing the sweep.

  C3 (minor) TestServicesStayTkFree uses a cwd-relative path, which can pass
    by reading nothing from another directory. Derive from module __file__.

  VERIFIED STILL CORRECT in the plan, do not let anyone "fix" these: Outcome's
    shape (workflow.py:90); NodeListResult's dataclass inheritance is valid;
    DiscoveryEvent.progress exists as tuple[int,int] (discovery.py:54);
    source_of() is a plain dict lookup (node.py:184) so dotted keys work;
    max_context_length is an int property, 0 when unestablished (node.py:189).

  Brief also carries forward: the three-times-repeated fixture blind spot
    lesson (ask what a fixture makes IMPOSSIBLE, not what it asserts); the
    PYTHONPATH trap; the copy rules with an instruction to REUSE
    test_node_cli.py's TestCopyRules word-boundary matcher rather than write a
    second list that can drift, since Task 8 needs the same one.

  RESUME HERE: an implementer is (or was) running Task 7 against e5b86f5.
  Do NOT dispatch a second implementer. Check in this order:
    1. `git log e5b86f5..HEAD`. If commits exist, the task ran; read
       task-7-report.md.
    2. If commits and report exist: generate a review package over
       e5b86f5..<new HEAD> and dispatch a reviewer, as for Tasks 1-5. Ask the
       operator first — as of this entry they had authorised the implementer
       dispatch only.
    3. If nothing exists and nothing is running, the dispatch was interrupted
       (this has happened twice in this plan). Re-dispatch the IMPLEMENTER
       using task-7-brief.md, which already exists — do not rewrite it.
  Still open and needing the operator: M8 from Task 6 (interactive menu option
    4 answers a deliberate choice with "Refused" and exit 3).
  After Task 7: Task 8 (Environment tab) — check its plan section against
    current source the same way before dispatching; Task 9; then the final
    whole-branch review.

--- 2026-08-26 03:29 UTC ---
Task 7: COMPLETE, NOT YET REVIEWED. Commit b8541f7 (one commit, three files,
  +720, no deletions): src/gui/services/nodes.py (new, 295), __init__.py
  re-exports (+26), tests/test_gui_nodes.py (new, 399). task-7-report.md
  written (10.8KB). Tree clean. No FROZEN path.

  All three brief corrections landed, verified by me in the source:
    C1  scan() takes fetch=None AND post=None and forwards both
        (src/gui/services/nodes.py:171-172). The Task 4 defect was NOT
        re-created.
    C2  LOCAL_NETWORK refused in scan() (nodes.py:191) — no ConsentRefused
        escapes into the view.
    C3  Tk-free test derives its path from service.__file__
        (tests/test_gui_nodes.py:397), not a cwd-relative string.

  Copy rules REUSED, not duplicated: tests/test_gui_nodes.py:38 imports
    judgements_in / ownership_in from tests.test_node_cli. One list, as asked.

  MY OWN INDEPENDENT VERIFICATION, not the implementer's word:
    - Full suite: 861 passed, 41 skipped in 52.60s. Matches the report.
      861 = 827 + 33 new + 1 (the services import-law test is parametrised
      over a glob of src/gui/services/*.py, so the new file adds a case).
    - HERMETICITY PROVEN INDEPENDENTLY, which is the whole point of C1:
      ran tests/test_gui_nodes.py under my own socket block that patches
      socket.socket.connect / connect_ex — 33 passed in 0.39s, nothing
      opened a connection. Then PROVED THE BLOCKER WAS LIVE rather than a
      no-op by calling http_get_json under it and confirming it raised.
      A block that does not block gives the same green as a hermetic suite.

  IMPLEMENTER'S OWN HONESTY NOTE, worth more than the green: one of its
    fourteen mutations LIED on the first pass. Its "delete scan()'s
    LOCAL_NETWORK guard" pattern matched the FIRST occurrence of that
    condition in the file, which is in save_consent (defined above scan).
    The mutation went red — for the other guard's test. scan()'s guard was
    never mutated at all. Caught and re-run against a unique anchor with the
    anchor asserted present. This is exactly the "verify the mutation
    applied" failure mode: a red result that proves nothing about the line
    you meant to test.

  JUDGEMENT CALLS (all recorded in task-7-report.md, all reversible):
    1. save_consent ALSO refuses LOCAL_NETWORK — beyond what the brief
       required. Reason: a permission nothing can act on is read back and
       refused by every later scan, and §3.7 says the CLI matches.
       Counter-argument recorded; reversible by deleting two lines + a test.
    2. scan() refuses NAMED_HOST with an empty address, else the candidate
       list is built from "http://" and reaches for "http://:11434". The CLI
       already had this guard.
    3. The socket guard patches urllib.request.urlopen rather than the two
       helpers in src.nodes.backends — patching the helpers would ALSO hide a
       service that forgot to forward, which is the defect being guarded.
    4. LOOPBACK derived from backends.PORTS, not hand-typed. It hardcoded
       {11434, 8080} first and the scope test failed: llama.cpp is on 8081.
       A wrong hand-typed constant makes the assertion describe a scan
       nobody performs.
    5. Only label and url are editable. No MEASURED figure is editable:
       typing over a reading would flip its source to "you told me" — an
       honest label on an invented number.

  OPEN, HANDED BACK (none blocking):
    - The copy-rule helpers live in a test file that another test file
      imports (tests.test_node_cli). Works, satisfies "one list not two",
      but test_node_cli is now imported under two names and TASK 8 IS THE
      THIRD CONSUMER. Right home is tests/copy_rules.py — a fourth file plus
      an edit to a fifth, both outside Task 7's three. DO THIS AS PART OF
      TASK 8 rather than letting a third importer accumulate.
    - list_nodes keeps the plan's "{n} computer(s) recorded." — breaks no
      copy rule but is not a sentence anybody writes.
    - update_field accepts "kind" but §3.5's card shows no row for it.
    - add_node slugs node_id from the label and leans on
      NodeStore._with_unique_id: two hand-added "Home PC"s silently become
      home-pc and home-pc-2 with nothing telling the person. Note this is the
      Task 5 collision fix working as designed, but SILENTLY — the same
      hazard shape, one layer up, now at the GUI.
    - ScanEventView.stage is an unenumerated vocabulary (permission,
      not-built, address, plus everything discovery emits). Today "stop and
      show a refusal" means ok=False and finished.

  RESUME HERE: Task 7 is implemented and NOT reviewed. Every other task in
  this plan was reviewed before the next began; Task 6 is the cautionary tale
  for skipping it.
  Next action: generate a review package over e5b86f5..b8541f7 and dispatch a
  reviewer. As of this entry the operator had authorised the IMPLEMENTER
  dispatch only — ask before dispatching a reviewer.
  Hand any reviewer: this block, task-7-report.md, task-7-brief.md (which is
  authoritative over the plan text and says why), and the open items above so
  they are not re-reported as new findings.
  Still open and needing the operator: M8 from Task 6.
  After Task 7: Task 8 (Environment tab) — CHECK ITS PLAN SECTION AGAINST
  CURRENT SOURCE BEFORE DISPATCHING, exactly as was done for Task 7. Two of
  the three Task 7 corrections existed because tasks landing after the plan
  was written changed the code underneath it. That will keep happening.

--- 2026-08-26 22:28 UTC ---
Task 7: REVIEWER DISPATCHED, operator-authorised. Verdict not yet in.
  Package: review-e5b86f5..b8541f7.diff (767 lines).
  Range: e5b86f5..b8541f7.
  Reviewer was told what I had ALREADY verified (suite 861/41; hermeticity
  proven under my own socket block with the blocker itself proven live; the
  three corrections present; copy-rule helpers imported not duplicated; clean
  tree, no FROZEN path) and asked to spend its effort on what inspection
  cannot settle: correctness, whether the tests prove what they claim, and
  whether the seam Task 8 builds on is sound.
  It was given task-7-brief.md (marked authoritative over the plan), the
  implementer's report, this ledger block, and the list of known open items
  with instructions NOT to re-report them as new — but to say if it thinks any
  is more serious than recorded.
  It was also given the three-times-repeated fixture blind-spot pattern, the
  mutation-that-matched-the-wrong-line failure the implementer self-reported,
  and the Task 5 silent-collision shape now present in add_node.

  MODEL POLICY, operator's answer 2026-08-26: SUB-AGENTS STAY ON OPUS.
  The Agent tool's model override accepts only sonnet / opus / haiku / fable
  — there is no version pinning, so a specific older Opus cannot be selected.
  Operator asked about 4.6 for throughput, was told it is not selectable and
  that the real lever is sonnet, and decided to stay on Opus. Do not downgrade
  reviewers: each review in this plan has found a genuine Critical, and one
  found a defect hidden inside the fix for the previous defect.

  RESUME HERE: a reviewer is (or was) running over e5b86f5..b8541f7.
  Do NOT re-dispatch an implementer and do NOT regenerate the package.
    1. If a verdict came back, record it in the Tasks 1-5 style and act on it.
    2. If no verdict and nothing running, the dispatch was interrupted (twice
       already in this plan) — re-dispatch the REVIEWER over the existing
       package.
  Still open and needing the operator: M8 from Task 6.
  After Task 7 closes: Task 8 (Environment tab). CHECK ITS PLAN SECTION
  AGAINST CURRENT SOURCE FIRST, as was done for Task 7 — two of that task's
  three corrections existed only because later tasks changed the code under
  the plan. Also fold in the copy-rule helper move to tests/copy_rules.py:
  Task 8 would be the third importer of tests.test_node_cli.

--- 2026-08-27 00:47 UTC ---
Task 7: REVIEWED. Verdict WITH FIXES. 1 critical, 7 important, 7 minor.
  Reviewer left tree clean (sha256 of nodes.py identical before/after, HEAD
  b8541f7, suite back at 861/41 in 52.57s). It ran 11 behavioural probes, 2
  CLI-parity probes, 3 add-path probes, and 3 mutation checks.

  I INDEPENDENTLY CONFIRMED THE FOUR THAT MATTER:
  C1  src/gui/services/nodes.py has ZERO except clauses, while list_nodes'
      docstring (nodes.py:139) claims "Never refuses" and the sibling module
      states the package rule at workflow.py:280-285 — "Never raises for the
      expected failure modes. The GUI shows a bad file as a message, exactly
      as the CLI does — a traceback is not an error message." A malformed
      nodes.yaml propagates out of all six entry points. schemas/node.py:13
      says these files are HAND-EDITABLE by design, so malformed content is
      an expected failure mode. Task 8's tab calls list_nodes on open, and
      the tab is the only route to the screen that would let a person fix it.
  I1  Mutation-proven unpinned: message=, ok=, finished= in the discovery
      passthrough (nodes.py:224-227) each replaced by a constant -> 33 passed
      all three times. The assertions LOOK like coverage but are positioned
      where they cannot fail: line 282 asserts events[-1].finished, which
      stays true when EVERY event is forced finished. ok and message on that
      path are not asserted at all. The passthrough is the only path where
      ok/finished can vary — the three refusal branches build their own
      literals.
  I2  CONFIRMED, AND IT CORRECTS SOMETHING I WROTE IN THIS LEDGER.
      discovery.py:209-214 yields stage="done", ok=False, finished=True for
      "Didn't find anything answering. You can type it in instead." That
      satisfies the "ok=False and finished" refusal contract exactly and is
      NOT a refusal — it is the most common outcome of a first scan. My
      03:29 entry filed this as "unenumerated stage vocabulary, today the
      answer is ok=False and finished". The recorded answer IS the defect.
      A Task 8 tab built to it renders "didn't find anything" in a refusal
      treatment and cannot tell "we looked and found nothing" from "we did
      not look". Fix: enumerate REFUSAL_STAGES = {"permission","not-built",
      "address"} beside EDITABLE, with a test that discovery's "done" is not
      in it. The stage strings already separate the cases.
  I3  CONFIRMED: cli.py:1643-1657 node_consent has NO LOCAL_NETWORK guard —
      it calls _scope_from (which accepts local-network) then set_consent.
      So `node consent --set local-network` exits 0 and stores it, while the
      service now refuses. The report justified the service guard as CLI
      consistency; that premise is backwards — it CREATES a §3.7 divergence
      on the consent verb while closing the one on scan. Reviewer and I both
      think the SERVICE is right and cli.py's node_consent should get the
      same guard, per cli.py's own argument at 1478-1489 about never storing
      an unactionable permission. NEEDS OPERATOR INTENT either way.

  Remaining important, not independently re-verified by me (reviewer showed
  measured output for each): I4 update_field writes unvalidated values —
  empty label and whitespace URL both accepted where add_node refuses them,
  and it bypasses upsert so store.py:76-114's "two computers may never share
  a URL" invariant is not enforced; I5 add_node at an already-stored URL says
  "Added Kitchen Box." while storing nothing new and discarding a corrected
  kind (different from, and worse than, the collision already in the ledger —
  that one makes an extra row, this one makes none and still says yes); I6
  scan() neither consults nor records stored consent, so a tab wiring the
  scope radio straight to scan() scans without the permission ledger ever
  recording it, on the feature whose whole pitch is the privacy promise;
  I7 scan() upserts per event on the worker thread while update_field does a
  whole-file read-modify-write on the UI thread — no lock, no mtime check,
  store.py:71 is a plain write_text so a crash mid-write truncates.

  Minors: M1 six full YAML load+dump cycles per computer found (CLI collects
  and upserts once); M2 an assertion that cannot fail (hasattr on a
  dataclass field); M3 the Tk-free test is a weaker duplicate of an existing
  AST-based one in test_gui_workflow.py that also catches `from tkinter
  import Tk`; M4 NOT_BUILT not re-exported; M5 the route both refusals
  recommend — type one in by hand — lands on a panel saying nothing can run,
  because summarise gates on reachable; M6 scan() is a generator so refusals
  do not exist until first next(); M7 the plan names a ScanResult type that
  was never defined and is not needed.

  SEAM FINDING worth acting on before Task 8 exists: ScanEventView drops
  event.node, so a scan finding two computers yields one interleaved prose
  stream with no way to tell which computer a row belongs to except ordering
  — against §3.4's "fills a card row by row". Adding node_id: str = "" now is
  nearly free; retrofitting after the tab is written is not.

  Reviewer's own honesty note: one restore attempt tripped its own uniqueness
  guard because "            finished=True,\n" is NOT unique in the file (the
  permission and address refusal blocks use the same literal at the same
  indent). It aborted rather than replacing the wrong line, and restored from
  a pristine cp. Same failure mode the implementer self-reported, arriving
  from the other direction. Anchor uniqueness is a recurring trap in this
  file specifically.

  RESUME HERE: Task 7 needs a FIX ROUND. Do NOT re-dispatch an implementer
  and do NOT regenerate the review package. Suggested grouping:
    pass 1 (contract, cheap now and structural after Task 8):
      C1 error handling + docstring correction; I2 REFUSAL_STAGES; I1 the
      test that pins the passthrough; the ScanEventView.node_id seam fix.
    pass 2 (data integrity): I4, I5, I6.
    pass 3 (write down, do not fix): I7 as a docstring constraint that Task 8
      must not offer editing during a scan.
  NEEDS THE OPERATOR FIRST: I3 — confirm the service guard stays and cli.py's
  node_consent gets the same one, or the service guard is reverted.
  Also still open: M8 from Task 6.
  As of this entry the operator had authorised the reviewer dispatch only.

--- 2026-08-27 01:33 UTC ---
Task 7: FIX ROUND DISPATCHED, operator-authorised. Outcome not yet in.
  Working from HEAD b8541f7.

  OPERATOR RULING ON I3, recorded so nobody re-litigates it: the SERVICE
  guard STAYS, and src/cli.py's node_consent GETS THE SAME GUARD. The
  implementer's stated justification for the service guard was backwards
  (it cited CLI consistency, but cli.py:1643-1657 has no guard and stores
  local-network happily), yet the behaviour it produced is the correct one —
  per cli.py's own argument at 1478-1489 about never storing a permission
  nothing can act on. Do not revert the service guard. Do not implement the
  /24 sweep.

  FILE SCOPE WIDENED for this round, deliberately: src/cli.py and
  tests/test_node_cli.py are now in scope, but ONLY for I3's guard and its
  test. Everything else stays in the three Task 7 files.

  Scope handed to the fixer, in priority order:
    P1 contract (cheap now, structural once Task 8 renders a tab):
       C1 error handling + the false "Never refuses" docstring;
       I2 REFUSAL_STAGES, with the fixer told to verify the three stage
          strings against what scan() actually emits rather than trust mine;
       I1 a test that pins message/ok/finished on the discovery passthrough,
          then mutation-checked to prove it catches all three;
       seam: ScanEventView gains node_id, populated from event.node.
    P2 integrity: I3 (per the ruling above), I4, I5, I6.
    P3 write down, do not fix: I7 as a docstring constraint — Task 8 must not
       offer editing while a scan runs.
    Minors: M1 (collect and upsert once, matching the CLI), M2 (delete the
       assertion that cannot fail), M4 (export NOT_BUILT + REFUSAL_STAGES),
       M3 fixer's call, M6 one docstring line. M5 EXPLICITLY OUT OF SCOPE —
       it is summary.py:113, Task 3's contract; note only.

  I6 was handed over as a genuine choice (record consent inside scan(), or
  document the required call order and pin it), with the fixer required to
  say which it chose and why. It is the privacy promise, so a tab wiring the
  scope radio straight to scan() must not scan without the ledger recording.

  ANCHOR-UNIQUENESS TRAP passed forward explicitly — it has now bitten two
  agents in this one file, from opposite directions: the implementer's
  LOCAL_NETWORK mutation matched save_consent instead of scan (red for the
  wrong test), and the reviewer's restore tripped its own guard because
  "            finished=True,\n" appears in the permission and address
  refusal blocks at the same indent. Fixer told to assert anchor uniqueness,
  read the line back after mutating, and verify the revert by checksum.

  FIXTURE BLIND SPOT passed forward as the fourth variation: POST-blind fake;
  CliRunner at 80 columns testing narrow wrapping; a stand-in with no node so
  the guarded path never ran; and now assertions positioned where forcing
  every event finished=True still passes. All four passed honestly and proved
  nothing.

  RESUME HERE: a fix-round subagent is (or was) running against b8541f7.
  Do NOT dispatch an implementer, do NOT regenerate the review package.
    1. `git log b8541f7..HEAD`. If commits exist, the round ran; read the fix
       report (task-7-report.md updated, or task-7-fix-report.md).
    2. If commits and report exist: record the round in the Tasks 1-5 style,
       then generate a FRESH package over b8541f7..<new HEAD> and dispatch a
       reviewer over the fix commits only. Ask the operator first.
    3. If nothing exists and nothing is running, the dispatch was interrupted
       (this has now happened twice in this plan) — re-dispatch the FIXER
       over the same findings.
  Still open and needing the operator: M8 from Task 6 — interactive menu
  option 4 answers a deliberate choice with "Refused" and exit 3; the
  question is written at the call site in src/cli.py.
  After Task 7 closes: Task 8 (Environment tab). CHECK ITS PLAN SECTION
  AGAINST CURRENT SOURCE FIRST — two of Task 7's three brief corrections
  existed only because later tasks moved the code under the plan. Also fold
  in the copy-rule helper move to tests/copy_rules.py: Task 8 would be the
  third importer of tests.test_node_cli.

--- 2026-08-27 02:52 UTC ---
Task 7: fix round 1/5 (8 closed + 5 minors, 1 PARTLY closed, 1 confirmed out
  of scope — commits b8541f7..4999df2, ten commits). HEAD 4999df2.
  Report: task-7-fix-report.md (separate from task-7-report.md, which is the
  implementer's own account).

  VERIFIED BY ME: 907 passed / 41 skipped in 52.48s (was 861/41). Ten commits.
  Five files, and src/cli.py touched ONLY for I3 as authorised. Tree clean.
  nodes.py now has 8 except clauses (was 0) and list_nodes' false "Never
  refuses" docstring is gone. cli.py's node_consent guard matches the scan
  site's wording and its exit-1 reasoning.

  Closed: C1 (6b4dbf0), I2 (3f17c76), I1 (ba5e21e), seam node_id (311457b),
    I3 (07d6b42), I4 (c0182cd), I6 (c771e9c), I7 written down (c56b9fb),
    M1/M2/M3/M4/M6.
  Every one watched fail first — 18 reds for C1 alone, one traceback per
    exception class — then watched pass, then mutation-checked where the test
    could not be red before the fix.

  JUDGEMENT CALLS:
  - I6 chose option (a): scan() RECORDS the consent it acts under. Reasoning:
    a documented call order is a rule the view can break silently, on the one
    feature whose whole pitch is that nothing is examined beyond what was
    permitted; recording makes the failure impossible rather than forbidden.
    scan() deliberately does NOT consult stored consent — the scope argument
    is the request, as --scope is for the CLI, and gating on the record would
    make a first scan impossible. Ordering pinned three ways, including
    inserting the write above the guards (8 failures).
  - REFUSAL_STAGES HAS FOUR MEMBERS, NOT THE THREE I NAMED. C1's error
    handling introduced a fourth stop stage, "store". Not a doctrinal refusal,
    but it stops a scan the same way, and rendered as an ordinary finding row
    it would bury the only message telling somebody their file is broken.
    THIS VINDICATES TELLING THE FIXER TO VERIFY MY LIST RATHER THAN TRUST IT —
    my three were correct at the time I wrote them and stale by the time the
    fix landed, because C1 changed the code underneath.
  - I5's real behaviour was WORSE than the review described: with the seeded
    provenance the old code applied the typed label and kind to the EXISTING
    row — "Added Kitchen Box." while silently RENAMING Home PC.

  NOT CLOSED, honestly reported: I5 in src/cli.py's node_add. The round scoped
    cli.py to I3 only, so a fix there could not have carried a test. The exact
    patch is in the fix report. THIS LEAVES THE TWO FRONT ENDS DISAGREEING ON
    `add` — the same §3.7 divergence I3 was about, one verb over. Pick it up.
  M5 confirmed and not fixed, out of scope: summarise gates on reachable
    (summary.py:113) and hand-added nodes default reachable=False, so the
    route BOTH refusals recommend lands on "No step can be assigned to an
    agent." This is Task 3's contract, not Task 7's to change.

  ANCHOR-UNIQUENESS TRAP FIRED TWICE MORE, both caught by the guard rather
    than by a misleading red: set_consent(ScanConsent.granted(scope, actor))
    now appears twice (save_consent and scan) — the THIRD arrival of that
    exact failure in this file — and `if chosen is ScanScope.LOCAL_NETWORK:`
    is not unique in cli.py. Passing the trap forward in the brief worked.

--- OPERATOR DECISIONS ON M8, 2026-08-27 02:22-02:52 ---
M8 is Task 6's open question: interactive menu option 4 ("Don't look — I'll
type it in") answers a deliberate choice with "Refused" and exit 3.

  RULED: exit 0. Choosing an offered route and having it honoured is success.
    `--scope none` KEEPS exit 3 — that is a real refusal of an explicit
    request and a test holds it.
  RULED: on choosing option 4, prompt for a name and address and record it.
    (Operator said "capture boxes"; in a terminal that is an inline prompt.
    The actual boxes are Task 8's Environment tab — decide the flow once and
    have both front ends match, per §3.7.)
  RULED: ASK PERMISSION BEFORE LISTENING. Typing an address is NOT permission
    to contact it. Reaching a named address is a scan at NAMED_HOST scope and
    needs its own yes. So a typed-in computer is recorded UNCHECKED unless the
    person separately permits a probe. This follows the four-rung doctrine
    rather than carving an exception into it.

  TWO OPERATOR ASSUMPTIONS I CHECKED AND CORRECTED BEFORE BUILDING:
  1. "This scenario is only when there are no nodes recorded already" — FALSE.
     node_scan loads the store but reads only the CONSENT from it. The menu
     appears whenever `node scan` runs without --scope and without --yes,
     however many computers are recorded. Someone with three machines looking
     for a fourth gets the same menu. So "enter desired Node name and
     location" is wrong copy for them. BRANCH ON WHETHER THE STORE IS EMPTY —
     they are genuinely different moments.
  2. "Obviously we can't do evals" — FALSE, and putting it on screen would
     have been a false statement about the tool. run_eval_case runs against a
     RunLedger and recorded run artifacts; src/governance/ contains ZERO
     references to nodes, inference, ollama or llama. Evals evaluate what
     already happened, not live inference. The TRUE and narrower consequence
     is the one the summary panel already states: steps whose actor is an
     agent cannot run. SAY NOTHING ABOUT EVALS.

  DEFERRED, NOT LOST — needs its own spec section and task, NOT M8:
    Workflow placeholders. Operator wants a workflow creatable with no node
    recorded, using placeholders and subscripts so it asks for the node at
    activation. This touches WorkflowStep.actor and step assignment — the
    workflow schema, not the node feature. Folding it into a one-line
    exit-code fix is how scope becomes unreviewable. FILE IT AS A REQUIREMENT.

  RESUME HERE for M8: src/cli.py is now FREE (the fix round finished). M8 is
  unimplemented. Implement per the rulings above. Its natural companion is the
  I5 cli.py node_add fix left open by the fix round, since both are src/cli.py
  and both are §3.7 parity.

  RESUME HERE for Task 7: the fix round is unreviewed. Generate a package over
  b8541f7..4999df2 and dispatch a reviewer over the fix commits only. Ask the
  operator first. Hand the reviewer this block, task-7-fix-report.md, and the
  open I5/M5 items so they are not re-reported as new.
  After that: Task 8 (Environment tab) — CHECK ITS PLAN SECTION AGAINST
  CURRENT SOURCE FIRST; fold in the copy-rule helper move to
  tests/copy_rules.py; and carry the M8 flow into the tab.
