# ADR-007 — Desktop / service boundary

**Status:** Proposed (Gate A)

## Context

The boundary already exists and is healthy: `src/gui/app.py` (211 lines,
2 tabs) contains only widget wiring; every decision lives in
`src/gui/services.py` (`validate_brief_file() -> BriefValidation`,
`build_workflow() -> BuildOutcome` — typed results, no widget types, doctrine
refusals returned as data not exceptions). GUI tests drive handlers headlessly.
The master handoff demands 15 desktop capabilities (§16), threads that never
block the UI (§16.15), CLI/desktop parity through "the same authoritative
services" (§15.6, Gate F), and no second validator in the UI (§16). The
repository is Python-only; a TS/web client is a future possibility only.

## Decision

1. **`src/gui/services.py` remains the ONLY seam.** Every §16 capability is
   first a typed service function (dataclass in/out, no `customtkinter`
   imports, no `print`); `src/gui/workflow_views.py` renders results. The
   CLI `workflow` sub-app calls the SAME functions — parity is achieved by
   construction, and `tests/test_gui_workflow.py` asserts views hold no
   business logic (risk R3).
2. **Import law (enforceable by a trivial test):** `src/gui/app.py` and
   `workflow_views.py` may import only `src.gui.services`, stdlib, and
   customtkinter. `services.py` may import runtime/governance/foundry/
   schemas — never widgets.
3. **Long operations run on worker threads** started by views; services stay
   synchronous and thread-agnostic; results marshal back via
   `widget.after()`. No async framework.
4. **Future service surface (FastAPI/MCP/TS client) mounts `services.py`
   functions** — that is the whole migration plan, which is why services
   must stay JSON-serializable-in/out (already true: dataclasses of
   str/bool/list).
5. **Desktop is optional forever:** the runtime stays fully operable via
   CLI without a display (`core runtime remains usable without the UI` —
   already proven by the `[gui]` optional dependency split in
   `pyproject.toml`).

## Alternatives considered

- *FastAPI now, GUI as HTTP client*: adds a server, ports, and a serializer
  layer to a local-first single-process app for zero current requirement
  (docs/dependencies.md: FastAPI "only when moving beyond CLI/local files").
  Rejected for this release.
- *Direct runtime calls from views* ("it's all Python anyway"): destroys
  parity testing and the future service path; forbidden by §16. Rejected.

## Consequences

- `services.py` grows substantially (sole Phase-7 owner in the file map);
  if it exceeds ~500 lines, split into a `src/gui/services/` package —
  views' import surface must not change.
