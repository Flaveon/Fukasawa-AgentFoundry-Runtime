# Node and capability — design

**Date:** 2026-08-23
**Status:** approved for implementation
**Phase:** 10a. The follow-on (10b) is named under *Deferred*.

---

## 1. The problem

Fukasawa decides which workflow steps an agent may perform. It does this
knowing nothing about whether the person using it owns a machine that could
run one.

That was tolerable while the only user was the author. It is not tolerable for
a product handed to other people: **the person who receives it runs their own
hardware, and the runtime has to learn what they have from them.**

Today the only way to tell it anything is to hand-write YAML at
`~/.fukasawa/model_endpoints.yaml` — a path that until recently appeared in one
line of source and no user-facing document — and the only thing you can say is
a name, a kind and a URL.

This spec closes that.

## 2. Scope

**In scope**

1. Contracts for an inference node and its capabilities.
2. Consent-gated discovery that fills those contracts in automatically.
3. Local storage, with the existing endpoint config still working.
4. A CLI flow and a desktop **Environment** tab for capturing and editing.

**Deferred to 10b — capability matching.** Using capabilities to answer "can
this operator's hardware actually run this step?" inside cooperation
assessment. It is the payoff, but it is a separate design question — does a
missing capability block promotion, downgrade `AutomationReadiness`, or only
warn? — and it cannot be built before nodes exist.

**Explicitly not built.** No cloud identity, no OAuth, no hosted agent, no
remote management, no per-node credentials. Local-first is unchanged.

## 3. The human experience

This section is the specification. Sections 4 onward describe what makes it
work; where they disagree with this one, this one is right.

### 3.1 Vocabulary

No sentence shown to a user contains *endpoint*, *provenance*, *scope*,
*capability*, *VRAM*, or a bare *token*. Internally the code says `node`; on
screen a node is a **computer**.

The one exemption is `node` as a **CLI command noun** — `fukasawa node scan` —
because that is an identifier the user types, not prose describing their
situation. It never appears in a sentence.

### 3.1.1 State outputs. Never judge them.

**No screen text characterises the user's hardware.** Not *slow*, *fast*,
*good*, *poor*, *powerful*, *limited*, *adequate*, *sufficient*, *plenty*, or
*only*. Report the measured figure with its unit and stop.

Five words a second is twice a fast typist. Whether that is slow depends
entirely on the task, and the person who knows the task is the user, not this
program.

This is the product's own doctrine applied to its own interface. The validator
never says a workflow is bad; it says what is missing, where, and what the rule
was, and lets a person decide. An environment screen that says "expect it to be
slow" is the same failure the validator was built to avoid.

The distinction that matters when writing copy:

| | |
|---|---|
| **A judgement about the user's setup** — forbidden | "expect it to be slow", "that should be plenty", "a limited graphics card" |
| **A fact about their setup** — required | "about 40 words a second", "no graphics card detected", "8,192 tokens" |
| **A fact about how this program behaves** — allowed | "steps needing more than 6,000 words stay with you", "promotion never requires a computer" |

The third row is not editorialising: it is mechanical consequence, and stating
it is the whole reason the screen exists.

| Internal | On screen |
|---|---|
| `InferenceNode` | "computer" / the label the user gave it |
| `Provenance.DETECTED` | *found it* |
| `Provenance.MEASURED` | *measured* |
| `Provenance.DECLARED` | *you told me* |
| `Provenance.UNKNOWN` | *not sure* |
| `context_length` | "longest input", in words |
| `tokens_per_second` | "speed", in words a second |
| `vram_bytes` | "graphics card", in GB, always "or more" |

### 3.2 First run

The Environment tab, empty:

```
   Fukasawa can take some steps off your hands — but only
   using AI running on a computer you control. Nothing here
   talks to the cloud.

   Do you have something like Ollama or llama.cpp running?

          [ Look for it ]      [ I'll type it in ]

   Not sure? "Look for it" only checks this computer
   unless you say otherwise.
```

### 3.3 Permission

Shown before anything opens a socket. Stored locally, revocable, changeable at
any time from the same screen.

```
   Where should I look?

   (•) Just this computer
       I'll check whether AI is running here.
       Nothing leaves this machine.

   ( ) A computer I'll name
       You give me its address; I check that one only.

   ( ) Everything on my network
       I'll look at other computers nearby. Takes about a
       minute. Some workplaces don't allow this — check first.

   ( ) Don't look at anything
       I'll type it in myself.

   You can change this later.          [ Cancel ]  [ Look ]
```

### 3.4 Discovery cycles

Findings appear **one at a time, as they are learned** — never as a finished
block. The pending row shows a spinner.

```
   Looking on this computer...

     ✓  Something's listening on port 11434
     ✓  It's Ollama 0.5.4
     ✓  3 models available
     ✓  Biggest is Llama 3.1 8B
     ✓  Longest input — about 6,000 words
     ✓  Graphics card in use — 6 GB or more
     ⠋  Timing a short reply...
     ✓  About 40 words a second

   Found one computer.
```

A stage that fails does not end the scan. Everything already found is kept and
the failed row reads plainly, e.g. *couldn't measure the speed*.

### 3.5 The card

Every fact carries where it came from, so the user can see at a glance which
rows to check.

```
  Ollama, on this computer                        found it

    Models it can run    3 — biggest is Llama 3.1 8B  found it
    Longest input        about 6,000 words            found it
    Graphics card        Yes — 6 GB or more in use    found it
    Speed                about 40 words a second      measured
    Address              localhost:11434              found it
    Call it              Home PC                     you told me

    [ Looks right ]   [ Change something ]   [ Check again ]


  What this means for your workflows
  You can hand off drafting and routine steps. Anything needing
  very long documents stays with you — your models top out
  around 6,000 words.
```

Editing any field flips that field's source to *you told me*.

### 3.6 What this means for your workflows

The closing panel is the reason to capture any of this. It is computed
deterministically, and per §3.1.1 it **states figures and mechanical
consequences — never a verdict**.

```
  What this means for your workflows

    Steps can be handed off to     Home PC
    Longest input any model takes  about 6,000 words   (8,192 tokens)
    Fastest measured speed         about 40 words a second
    Graphics card                  yes, on Home PC — 6 GB or more

    Steps needing more than 6,000 words of input stay with you.
```

**The rows.** Each is a figure with a unit, or "not sure" where nothing was
learned. Word figures are rounded to two significant digits and the exact token
count is shown beside them, so a lay reader and a technical one both get what
they need.

**The consequence line.** Exactly one, and only when it follows arithmetically:
the largest `context_length` across all models on all reachable computers
becomes "Steps needing more than N words of input stay with you." Nothing is
inferred about whether N is enough — that depends on the work, which the user
knows and this program does not.

**With nothing configured:**

```
  What this means for your workflows

    Steps can be handed off to     nothing yet

    Every step stays with you. Capture, validation, promotion and
    export do not require a computer.
```

The second sentence is a fact about this program, not reassurance. A user with
no hardware needs to know that the lifecycle still works, because otherwise the
empty state reads as a failure.

**When a graphics card was not detected**, the row says so and nothing more:
`Graphics card — none detected`. No prediction about how that will feel. Note
also that a card can be present and unobserved (§4.1), so the row distinguishes
*none detected* from *not sure*.

### 3.7 The CLI matches

Same register, same cycling, same words. Not terse.

```
$ fukasawa node scan

  Fukasawa can take some steps off your hands — but only using
  AI running on a computer you control.

  Where should I look?
    1  Just this computer         nothing leaves this machine
    2  A computer I'll name
    3  Everything on my network   takes about a minute; some workplaces
                                 disallow this
    4  Don't look — I'll type it in

  Choose [1]: 1

  Looking on this computer...
    ✓  Something's listening on port 11434
    ...

  Found one computer.
  What should I call it? [Home PC]:
  Saved.
```

Non-interactive use is supported and skips every prompt:
`--scope this-machine|named-host|local-network|none`, `--host`, `--label`,
`--yes`, `--json`. With `--json`, each discovery event is emitted as one JSON
object per line so the stream is still a stream.

## 4. Contracts — `src/schemas/node.py`

Canonical Pydantic v2 per ADR-001, `extra="forbid"`, every field described,
`SCHEMA_VERSION = "1"`.

Values are **flat**, with a separate `provenance` map, rather than each value
wrapped in `{value, source}`. These files are hand-editable and the wrapped
form doubles their depth.

```python
class ScanScope(str, Enum):
    NONE | THIS_MACHINE | NAMED_HOST | LOCAL_NETWORK

class Provenance(str, Enum):
    DETECTED | MEASURED | DECLARED | UNKNOWN

class NodeKind(str, Enum):
    OLLAMA | LLAMACPP

class ModelCapability(BaseModel):
    name: str                      # "llama3.1:8b"
    family: str = ""
    parameter_size: str = ""       # "8.0B"
    quantization: str = ""         # "Q4_K_M"
    context_length: int = 0        # tokens; 0 = unknown
    supports_tools: bool = False
    supports_vision: bool = False
    size_bytes: int = 0

class HostCapability(BaseModel):
    gpu_present: Optional[bool] = None   # None = genuinely unknown
    vram_bytes: int = 0                  # a FLOOR (see 4.1)
    cpu_count: int = 0                   # local scans only
    ram_bytes: int = 0                   # local scans only
    platform: str = ""                   # local scans only
    tokens_per_second: float = 0.0       # measured
    latency_ms: float = 0.0              # measured

class InferenceNode(BaseModel):
    schema_version: str = "1"
    node_id: str                   # slug, ^[a-z0-9]+(-[a-z0-9]+)*$
    label: str                     # what the user calls it
    kind: NodeKind
    url: str
    is_local: bool = False
    reachable: bool = False
    backend_version: str = ""
    models: list[ModelCapability] = []
    host: HostCapability = HostCapability()
    provenance: dict[str, Provenance] = {}   # field path -> source
    last_probed_at: Optional[datetime] = None
    notes: str = ""

class ScanConsent(BaseModel):
    schema_version: str = "1"
    scope: ScanScope = ScanScope.NONE
    granted_by: str = ""           # self-attested, as everywhere here
    granted_at: Optional[datetime] = None
```

`provenance` keys are dotted field paths (`"host.vram_bytes"`,
`"models"`, `"label"`). A key absent means `UNKNOWN`.

### 4.1 Observed VRAM is a floor

`/api/ps` reports what a **currently loaded** model committed to VRAM. If
nothing is loaded, the number is zero — which does not mean there is no GPU.
So:

- `gpu_present` is a true tri-state: `True` when VRAM > 0 was observed,
  `None` when nothing was loaded, `False` only when the backend positively
  reports no offload (llama.cpp `n_gpu_layers == 0`).
- `vram_bytes` is always rendered "**or more**". Never as a total.

Being honest about the boundary of what was observed is the house style.

## 5. Discovery — `src/kernel/discovery.py`

### 5.1 A stream, not a return value

```python
@dataclass
class DiscoveryEvent:
    stage: str                 # machine-readable: "reachable", "models", ...
    message: str               # the human line, already plain language
    ok: bool = True            # False = this stage failed, scan continues
    node: Optional[InferenceNode] = None   # the node so far, after this stage
    progress: tuple[int, int] = (0, 0)     # (done, total) for sweeps
    finished: bool = False

def discover(
    scope: ScanScope,
    host: str = "",             # required for NAMED_HOST; ignored otherwise
    *,
    connect_timeout: float = 2.0,    # 0.3 for a LOCAL_NETWORK sweep
    read_timeout: float = 10.0,
    speed_timeout: float = 20.0,
) -> Iterator[DiscoveryEvent]:
```

The CLI renders each event as a line. The desktop pushes each onto the phase-7
worker queue and fills the card row by row. **Same service, two renderers** —
ADR-007 §1 unchanged.

Each event carries the node *as it stands*, so a scan interrupted or failed
part way still yields everything learned before that point.

### 5.2 What each rung is permitted to open

| Scope | Opens | Also reads |
|---|---|---|
| `NONE` | nothing — no socket is created at all | — |
| `THIS_MACHINE` | `127.0.0.1:11434`, `127.0.0.1:8081` | local CPU count, RAM, platform |
| `NAMED_HOST` | exactly the host and port given — including `localhost` | — |
| `LOCAL_NETWORK` | the primary interface's /24, ports 11434 and 8081 | — |

`NAMED_HOST` accepts `host`, `host:port`, or a full URL. A bare host is tried
on both known ports. A bare `host:port` is tried as both backends and the one
that answers wins.

`LOCAL_NETWORK` limits: one interface, one /24, connect timeout 0.3 s, at most
32 concurrent connections, progress yielded every 16 hosts. It never touches
anything outside that /24.

### 5.3 Stages, and what fails how

Per candidate address, in order. Each yields one event.

| Stage | Ollama | llama.cpp | On failure |
|---|---|---|---|
| `reachable` | `GET /api/version` | `GET /health` | no node produced; scan continues to the next address |
| `backend` | version from above | `GET /props` | `backend_version=""`, source *not sure* |
| `models` | `GET /api/tags` | `GET /v1/models` | `models=[]`, row reads "couldn't list the models" |
| `model_detail` | `POST /api/show` per model | `/props` → `n_ctx` | that model keeps its name and size; `context_length=0` |
| `hardware` | `GET /api/ps` → `size_vram` | `/props` → `n_gpu_layers` | `gpu_present=None` |
| `speed` | short generation; `eval_count` / `eval_duration` from the response | short generation; `timings.predicted_per_second` from the response | `tokens_per_second=0.0`, row reads "couldn't measure the speed" |
| `local_host` | `os.cpu_count()`, RAM, `platform` | same | fields stay 0/"" |

The speed stage generates at most 32 tokens with a fixed prompt and a 20-second
timeout. It is the only stage that costs the user compute, and the permission
screen says so.

`model_detail` is capped at the first 12 models to keep a scan bounded.

### 5.4 No LLM in discovery

Every value is read from an API or measured with a clock. The model is never
asked to describe its own host: it does not know, and would confabulate
plausibly enough to be believed. This also keeps discovery clear of the
no-LLM-in-authoritative-paths rule, though discovery is config-time and not
itself authoritative.

### 5.5 A second network module, deliberately

`tests/test_hardening.py::test_only_the_model_adapter_reaches_the_network`
asserts `src/kernel/models.py` is the only module under `src/` importing
network machinery. This adds a second, so that test changes to name both — with
a comment recording that discovery is config-time, is consent-gated, and is not
on an authoritative path.

The guard is widened deliberately and in the open. It is not relaxed.

## 6. Storage

One file, `$FUKASAWA_HOME/nodes.yaml` (default `~/.fukasawa/nodes.yaml`,
matching the trust store). The consent record lives in it rather than in a
second file, because a permission with no nodes beside it is a thing users lose
track of:

```yaml
schema_version: "1"
consent:
  scope: THIS_MACHINE
  granted_by: sam
  granted_at: 2026-08-23T09:14:00Z
nodes:
  home-pc:
    label: Home PC
    kind: ollama
    url: http://localhost:11434
    ...
```

**Backward compatibility.** `ModelEndpointRegistry` resolves in this order,
later winning: built-in defaults → `model_endpoints.yaml` → `nodes.yaml`. An
existing endpoint config keeps working untouched, and a node automatically
becomes a usable endpoint under its `node_id`.

### 6.0 Identity and duplicates

`node_id` is a slug derived from the label the user chose, lowercased with
runs of non-alphanumerics collapsed to a single hyphen ("Home PC" →
`home-pc`). A collision gets a numeric suffix (`home-pc-2`). The user may edit
the id directly in `node edit`; it must match
`^[a-z0-9]+(-[a-z0-9]+)*$` and be unique, and both are enforced with a
message naming the problem.

**Two nodes may not share a URL.** A scan that rediscovers an address already
stored updates that node in place — refreshing detected fields, preserving
every field whose source is *you told me*, and leaving `node_id` and `label`
alone. This is what makes "Check again" safe to press.

### 6.1 Doctrine this file must obey

- **Nodes are referenced by name.** A graph says `endpoint: home-pc`. An
  address never appears in a shared artifact.
- **This file is per-operator and local.** Never committed, never bundled,
  never written into an exported brief. It describes someone's house.
- **Zero nodes must work.** With nothing configured, every step stays with a
  person — already the correct default, and §3.6 says so in words.
- **Nothing about any operator's network ships in the product.** The built-in
  defaults are `localhost` only.

## 7. CLI — `src/cli.py`, `node` sub-app

| Command | Does |
|---|---|
| `node scan` | consent (if not granted) → cycle → name it → save |
| `node list` | the cards, one per computer |
| `node show <id>` | one card plus every model |
| `node add` | manual entry, same fields, all *you told me* |
| `node edit <id>` | prompts field by field, current value as the default, blank keeps it; any value the user changes flips to *you told me*. `--set field=value` for one field non-interactively |
| `node forget <id>` | remove it |
| `node consent [--set ...]` | show or change the permission |

Exit codes follow the existing convention: `0` fine, `1` user error, `3` a
refusal (e.g. scanning when consent is `NONE`).

## 8. Desktop — a fourth tab, "Environment"

`src/gui/environment_views.py`, mounted by `src/gui/app.py`, backed by
`src/gui/services/nodes.py`.

Follows the rules the desktop already lives by: the view decides nothing, it
imports only `src.gui.services` plus stdlib and customtkinter, and long work
runs on the phase-7 worker with results marshalled through the queue. The
import-law test discovers new view files by glob, so it covers this one
automatically.

Screens are §3.2–§3.6. The card is built once and its rows updated as events
arrive.

## 9. Testing

**Permission is the privacy promise, so it is tested, not trusted.**

- `NONE` opens **zero** sockets — asserted with the socket-blocking fixture
  phase 8 already built for exactly this shape.
- Each rung attempts **only** its permitted addresses — a recording fake socket
  captures every address attempted and the test asserts the exact set.
- `LOCAL_NETWORK` never leaves the /24, respects the concurrency cap, and
  yields progress.

**Discovery**

- Events arrive in stage order, each carrying the node so far.
- A failure at any stage keeps everything already found and marks that row.
- An unreachable host produces a legible message, never a traceback.
- Fakes for both backends' API shapes; no live server is required.
- No LLM is called: the model adapter is not invoked by discovery.

**Contracts and storage**

- Round trip through YAML; unknown field refused by name.
- Editing a field flips its provenance to `DECLARED`.
- `nodes.yaml` absent → zero nodes → "every step stays with you".
- An existing `model_endpoints.yaml` keeps resolving.

**Doctrine**

- An exported brief never contains a node URL.
- No private address or operator hostname appears anywhere in the shipped tree
  (the check run by hand in phase 9, made permanent).

**Human layer**

- Token→word and byte→GB conversions, including the "or more" phrasing.
- §3.6's sentence for each branch: no nodes, nodes without GPU, low ceiling,
  fields marked *not sure*.
- **No screen text judges the user's hardware** (§3.1.1). Every rendered
  string is checked against a list — *slow*, *fast*, *good*, *poor*,
  *powerful*, *weak*, *adequate*, *plenty*, *enough*, *limited* — and the
  environment panel is rendered for each branch (no computers, no GPU, tiny
  context, unmeasured speed) to prove none of them produces a verdict.

  The positive half matters as much: each branch must still state its figure
  with a unit, so a screen cannot pass by saying nothing.

- **Prose** shown to a user contains none of: *provenance*, *scope*,
  *VRAM*, *endpoint*, or *capability*. Checked against the rendered strings.

  `node` is exempt **only** as a CLI command noun — `fukasawa node scan` —
  because that is an identifier the user types, not prose describing their
  situation. The test allows it in command names and forbids it in sentences.

## 10. Deferred

- **10b — capability matching.** Connect capabilities to
  `CooperationAssessment.required_tools` and
  `StepAssignment.runtime_requirements` so `AutomationReadiness` can mean
  "ready *here*" rather than "ready in principle".
- Credentials for protected endpoints.
- Backends beyond Ollama and llama.cpp.
- Re-probing on a schedule.
