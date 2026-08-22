# Pilot walkthrough

One real workflow, captured messy and carried to something the runtime can run.
Every command below was executed against the pilot and every output is real.

The subject is `examples/workflows/substack-publication/` — see its `README.md`
for what the workflow is and which problems are seeded in it.

## Before you start

```bash
uv venv --python 3.12 .venv && uv pip install -e ".[dev,gui]"
```

Work in a scratch directory so you never edit the committed artifacts:

```bash
mkdir -p /tmp/pilot && cp examples/workflows/substack-publication/observed-workflow.yaml /tmp/pilot/observed.yaml
```

Every command takes `--db`. Without it the ledger goes to the default path;
pointing it at a scratch file keeps this walkthrough self-contained.

---

## 1. Validate the honest capture

```bash
fukasawa workflow validate /tmp/pilot/observed.yaml --db /tmp/pilot/pilot.db
```

```
             substack-publication — 24 finding(s), rule set v1
┏━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┓
┃ Rule   ┃ Policy   ┃ Where           ┃ Problem          ┃ Remediation     ┃
┡━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━┩
│ HW-003 │ blocking │ publish-post.a… │ step             │ Name the        │
│        │          │                 │ 'publish-post'   │ person, role,   │
│        │          │                 │ has no actor —   │ or system that  │
│        │          │                 │ nobody is named  │ performs this   │
│        │          │                 │ as performing it │ step.           │
│ HW-005 │ blocking │ publish-post.n… │ step             │ Add the missing │
│        │          │                 │ 'publish-post'   │ step, or        │
│        │          │                 │ points to        │ correct the     │
│        │          │                 │ 'promote-post',  │ which is not a  │
│        │          │                 │ declared step    │ existing one.   │
└────────┴──────────┴─────────────────┴──────────────────┴─────────────────┘
```

**24 findings — 14 blocking.** That is the expected result, not a failure. The
capture is honest and honest captures have holes in them.

Note what did *not* happen: nothing refused to read the file, and nothing
refused to store it. Blocking means blocking **promotion**.

The exit code is machine-readable:

```bash
fukasawa workflow validate /tmp/pilot/observed.yaml --db /tmp/pilot/pilot.db > /dev/null; echo $?
# 2
```

| Exit | Meaning |
|---|---|
| `0` | validated, promotion-ready |
| `1` | a user error — bad path, missing prerequisite |
| `2` | validated, blocking findings present |
| `3` | a doctrine refusal — the runtime understood and declined |

Add `--json` anywhere for machine-readable output.

## 2. Try to promote it anyway

```bash
fukasawa workflow promote /tmp/pilot/observed.yaml --by operator --db /tmp/pilot/pilot.db
```

Refused, with the fourteen blocking findings printed and exit `2`. The gate is
real: a workflow does not become accountable by being declared so.

## 3. Repair it

A person fixes the blocking findings. The result is committed as
`repaired-workflow.yaml` so you can skip the typing:

```bash
cp examples/workflows/substack-publication/repaired-workflow.yaml /tmp/pilot/repaired.yaml
fukasawa workflow validate /tmp/pilot/repaired.yaml --db /tmp/pilot/pilot.db
```

```
6 finding(s), rule set v1
...
Promotion ready. Next: fukasawa workflow promote /tmp/pilot/repaired.yaml --by <your name>
```

**Six findings remain and promotion is ready.** All six are HW-013 — the
unwritten rules the capture admitted to. They are advisory by design: recording
that "artwork is optional in practice" is the honest act this tool exists to
encourage, and blocking on it would teach people to stop writing them down.

Either write each rule into the step it governs, or accept it on the record.
Finding ids come from `--json`, or from the error message if you get one wrong:

```bash
fukasawa workflow validate /tmp/pilot/repaired.yaml --db /tmp/pilot/pilot.db --json \
  | python -c "import json,sys; [print(f['finding_id']) for f in json.load(sys.stdin)['findings']]"
```

```bash
fukasawa workflow accept-risk /tmp/pilot/repaired.yaml \
    --finding "HW-013:unwritten_rules/Artwork is optional in practice, even th" \
    --by operator --why "Known and deliberate; artwork is a nice-to-have." \
    --db /tmp/pilot/pilot.db
```

```
Accepted HW-013 (HW-013:unwritten_rules/Artwork is optional in practice,
even th) as residual risk.
Recorded by operator: Known and deliberate; artwork is a nice-to-have.

This records a decision. It does not change whether the workflow may be
promoted — advisory findings never blocked it.
```

Validation is stateless, so re-running it recomputes every finding from
scratch — but the acceptance is reattached from the ledger, and the finding
comes back marked accepted rather than looking untouched. `--by` and `--why` are
both **required**: an acceptance without a name and a reason is not a decision.

Try it on a blocking finding and you get exit `3`. Waiving one would turn the
promotion gate into a formality.

**The guided step editor in the desktop app does the same job with the rule's
remediation printed beside every field.** See `docs/desktop-guide.md`.

## 4. Promote, twice

Promotion moves **one step** up the maturity ladder. There is no path from
`OBSERVED` to `RUNTIME_READY`.

```bash
fukasawa workflow promote /tmp/pilot/repaired.yaml --by operator --db /tmp/pilot/pilot.db   # OBSERVED  → MAPPED
fukasawa workflow promote /tmp/pilot/repaired.yaml --by operator --db /tmp/pilot/pilot.db   # MAPPED    → ACCOUNTABLE
```

```
Recorded as promotion wpromo-ef79fbbd in /tmp/pilot/pilot.db.
```

Run it a third time and it advances again rather than repeating: **content comes
from your file, progress from the ledger.** Editing the YAML between promotions
is picked up; a step already taken is not re-taken.

Promotion produces a **new artifact** and leaves the draft alone. The
`AccountableWorkflow` records who promoted it, when, and under which rule-set and
schema versions.

## 5. Assess cooperation

```bash
fukasawa workflow assess-cooperation substack-publication --db /tmp/pilot/pilot.db
```

```
               Cooperation assessment — substack-publication
┏━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━┓
┃ Step          ┃ Executor      ┃ Floor        ┃ Supervision   ┃ Readiness ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━┩
│ capture-idea  │ HUMAN_LED_AI… │ -            │ EVERY_OUTPUT… │ PILOT     │
│ scope-check   │ HUMAN_ONLY    │ -            │ NONE          │ NOT_READY │
│ deep-research │ HUMAN_LED_AI… │ -            │ EVERY_OUTPUT… │ PILOT     │
│ draft-article │ HUMAN_ONLY    │ -            │ NONE          │ NOT_READY │
│ request-artw… │ AGENT_EXECUT… │ -            │ EVERY_OUTPUT… │ READY     │
│ review-and-a… │ HUMAN_ONLY    │ IRREVERSIBLE │ NONE          │ NOT_READY │
│ publish-post  │ AGENT_PREPAR… │ IRREVERSIBLE │ APPROVAL_REQ… │ PILOT     │
│ archive-notes │ DETERMINISTI… │ -            │ SPOT_CHECK    │ READY     │
└───────────────┴───────────────┴──────────────┴───────────────┴───────────┘
Saved 8 assessment(s) to /tmp/pilot/pilot.db.
```

**No model produced this.** It is a published decision table reading the
characteristics declared on each step, which is what lets you disagree with a
recommendation *before* running it.

Two steps hit an `IRREVERSIBLE` safety floor. Watch what that means:

```bash
fukasawa workflow assess-cooperation substack-publication --db /tmp/pilot/pilot.db \
    --override "publish-post=BOUNDED_AUTONOMOUS_AGENT" --by operator --why "faster"
```

```
Refused: step 'publish-post' hit the IRREVERSIBLE safety floor, so it cannot
be moved from AGENT_PREPARED_HUMAN_APPROVED to the more autonomous
BOUNDED_AUTONOMOUS_AGENT. Overrides may always move work toward human
control, never away from it. Change the step's characteristics if the
underlying fact is wrong.
```

Exit `3`. **Overrides are one-directional.** You may always pull work back
toward a person. You may not push a floored step toward autonomy, because the
floor exists because of a fact about the work — and that fact does not change
because someone would prefer it did. The refusal names the remedy: if publishing
really is reversible here, change the *characteristic*, and the recommendation
follows.

Moving toward human control works normally, and requires a reason:

```bash
fukasawa workflow assess-cooperation substack-publication --db /tmp/pilot/pilot.db \
    --override "request-artwork=HUMAN_ONLY" --by operator --why "the illustrator prefers to be asked directly"
```

## 6. Build the assignments and approve them

```bash
fukasawa workflow build-cooperative substack-publication --db /tmp/pilot/pilot.db --approve-by operator
```

```
Agent packages required: archive-notes-agent, publish-post-agent, request-artwork-agent

5 step(s) stay with a person: capture-idea, scope-check, deep-research,
draft-article, review-and-approve

Approved by operator.
```

Every assignment names a **human owner and an escalation target**, including the
fully automated ones. Automation moves the work, never the accountability.

Building without `--approve-by` is deliberate and useful: it lets you read the
assignments before signing them. Export refuses an unapproved workflow.

## 7. Export

```bash
fukasawa workflow export-agent-brief substack-publication --db /tmp/pilot/pilot.db --out /tmp/pilot/brief.yaml
```

Try it before approving and you get exit `1` with the command you actually need.
After approving:

```
Brief written to /tmp/pilot/brief.yaml.
Next: fukasawa run the exported brief, or fukasawa workflow status substack-publication
```

**Eight steps became ten states.** `publish-post` is
`AGENT_PREPARED_HUMAN_APPROVED`, so it splits into three: the agent's work, a
waiting state, and the person's decision. The approval is now somewhere the work
*sits* and something the ledger *records*, rather than an assumption.

## 8. Where am I?

```bash
fukasawa workflow status substack-publication --db /tmp/pilot/pilot.db
```

```
                 Lifecycle — substack-publication
┏━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Stage       ┃ Present ┃ Detail                                 ┃
┡━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ draft       │ yes     │ version 1, MAPPED                      │
│ accountable │ yes     │ version 1, ACCOUNTABLE, 8 steps        │
│ assessed    │ yes     │ 8 step(s); 0 overridden; 0 not ready   │
│ cooperative │ yes     │ approved by operator                   │
│ exported    │ yes     │ 10 states, 3 agent(s), status approved │
│ runs        │ no      │ —                                      │
└─────────────┴─────────┴────────────────────────────────────────┘
```

Safe to run at any point, including on a workflow that does not exist — "nothing
here yet" answers the question rather than failing it. This is the screen you
open when you have lost track.

## The same lifecycle in the desktop app

```bash
fukasawa-gui
```

The Workflow tab has the same six stages down the left. **Both surfaces call the
same service functions** — neither owns a rule, and if they ever disagreed about
a workflow, one of them stopped calling them. `TestParity` in
`tests/test_gui_workflow.py` asserts it on assessment, export, and refusals:
the same override above is refused identically in both, with the same message.

See `docs/desktop-guide.md`.

## What you just proved

```
map → validate → repair → cooperate → export
```

- A messy workflow was **recorded rather than rejected**.
- Fourteen blocking findings each named a location, a rule and a remedy.
- Promotion was **refused** until they were resolved, then produced a traceable
  artifact rather than mutating the source.
- Executor recommendations were **deterministic and arguable**, and a safety
  floor **refused** an override that would have handed publication authority to
  an agent.
- The export **preserved** the human approval as a state the runtime enforces.

Five of eight steps stayed with a person. That is not a shortfall — it is the
answer, stated plainly instead of hidden behind an automation count.
