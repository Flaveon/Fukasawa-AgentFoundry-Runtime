# Session Handoff — resume here

_Last updated: 2026-07-24. Written for a fresh (cold-start) session._

## Where things stand

- **Repo**: `Flaveon/Fukasawa-AgentFoundry-Runtime` (PUBLIC), branch `main`.
- **Released**: `v0.1.0` is tagged and live, with cross-platform binaries
  attached to the GitHub Release (linux-x64, macos-arm64, windows-x64.exe),
  built by CI. HEAD is ahead of the tag by one fix (see below).
- **Tests**: `99 passed, 4 skipped` (the 4 are GUI-view tests that skip
  without a display; they pass under `xvfb-run`).
- **Python**: 3.12 via `uv` in `.venv`. The system Python is 3.10 — do NOT
  use it; the project needs 3.11+.

### Resume checklist
```bash
cd ~/agentic-workspace/OpenAI_GPT_Builds/Fukasawa-AgentFoundry-Runtime
uv pip install --python .venv/bin/python -e '.[dev,gui]'   # if needed
.venv/bin/python -m pytest -q                               # expect 99 passed, 4 skipped
xvfb-run -a .venv/bin/python -m pytest tests/test_gui.py -q # to run the 4 GUI tests
```

## What's done (don't rebuild)

- **Phases 0–4** complete: schemas + state machine + append-only ledger
  (0), durable run state + resume + handoffs (1), agent package generator
  with C-Pax injection (2), evidence-based governance/maturity loop (3),
  orchestration kernel with adapters + signed-graph gating (4).
- **Phase 5 so far**: 5A trust/signing (`src/security/`), 5B model adapters
  (`src/kernel/models.py`, Ollama + llama.cpp), 5D PyInstaller packaging
  (`packaging/`), 5E CustomTkinter GUI (`src/gui/`). CI at
  `.github/workflows/build.yml`.
- **Recent fixes**: removed real LAN IPs/node names from model endpoint
  defaults + example (localhost-only now); private signing key created
  0600 atomically + identity dir 0700 (`5234a9a`, landed AFTER v0.1.0 — so
  it ships in the next tag, not v0.1.0).

## Tomorrow's work

### 1. gitleaks across ALL repos (cross-repo, do first — it's quick)
Goal: make "no secrets in git" machine-enforced everywhere, so the LAN-IP
leak that happened here can't recur.
- Add a **gitleaks GitHub Action** to each repo (scans on push/PR).
- Add a **pre-commit hook** (`gitleaks protect --staged`) so commits with
  IPs/keys/tokens are blocked locally before they're ever pushed.
- Run a **one-time historical scan** (`gitleaks detect`) per repo to find
  anything already committed; remember RFC1918 IPs are low-severity, real
  secrets (API keys/tokens) need **rotation**, not just deletion.
- List the operator's repos first (`gh repo list --limit 100`) and decide
  scope. A shared reusable workflow or an org-level ruleset avoids copying
  the same YAML into every repo by hand.

### 2. Phase 5C — signed export/import bundle format
The last Phase 5 piece: let people share whole WORKFLOWS (not just the app),
safely, using the 5A trust layer.

Design sketch (confirm before building):
- A **bundle** = an archive containing the workflow brief, its graph(s), the
  generated agent packages, and eval cases, plus a **manifest** listing
  every file with its SHA-256, plus a **detached signature** over the
  manifest (Ed25519, via `src/security/signing.py`).
- **Export**: `fukasawa bundle export <brief> --graph <g> --out x.fkz` —
  collect artifacts, hash each into a `BundleManifest`
  (`src/schemas/bundle.py`), sign the manifest with the local identity.
- **Import**: `fukasawa bundle import x.fkz` — verify the signature against
  the trust store (reuse the `TrustStore.is_trusted_signature` gate, same as
  graph running), verify each file's hash matches the manifest, THEN unpack.
  Refuse untrusted or tampered bundles — mirror the `UntrustedGraphError`
  pattern in `src/kernel/kernel.py`.
- Tests to write: roundtrip export→import; tamper a file → import refused;
  untrusted signer → refused; trusted signer → accepted.
- This closes the roadmap's Phase 3/5 "export/import format" deliverable.

## Key context / conventions

- **Doctrine precedence**: the project `CLAUDE.md` supersedes the older
  July-18 `specs/` where they conflict (operator ruling). ObservationPacket
  is a draft schema. See the `[[fukasawa-doctrine-precedence]]` memory.
- **Working style this project uses**: build each phase/sub-phase end to
  end (code + tests + a live demo proving the exit criteria), then commit
  with a conventional-commit message and push. No `Co-Authored-By` trailers.
- **Security posture that's now load-bearing**: append-only ledger + signed
  graphs + trust store. 5C extends the same trust model to bundles.
- `src/` layout: `schemas/`, `runtime/`, `foundry/`, `governance/`,
  `kernel/`, `security/`, `gui/`; entry point `src/app_entry.py`
  (no-args → GUI, args → CLI).
