### Task 3: Backend probes

The only new module that touches the network. Pure functions over an injected fetcher, so no test needs a live server.

**Files:**
- Create: `src/nodes/backends.py`
- Test: `tests/test_node_backends.py`

**Interfaces:**
- Consumes: Task 1's contracts.
- Produces: `Fetcher` (`Callable[[str, float], dict]`), `Poster` (`Callable[[str, dict, float], dict]`), `http_get_json(url, timeout) -> dict`, `http_post_json(url, payload, timeout) -> dict`, `probe_ollama(base_url, fetch, post) -> ProbeResult`, `probe_llamacpp(base_url, fetch) -> ProbeResult`, `ProbeResult(kind, backend_version, models, host, ok, note)`, `PORTS = ((11434, NodeKind.OLLAMA), (8081, NodeKind.LLAMACPP))`.

> **Ollama's `/api/show` is a POST with a JSON body**, not a GET with a query
> string. The probe therefore takes an injected `post` alongside `fetch`,
> mirroring the `Poster` the kernel already defines. A GET-only probe passes
> against a fake and fails against a real server — exactly the class of bug a
> test with a hand-written fake will not catch, so the shape is specified here.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_node_backends.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Reading an inference server's own metadata.

The design's key decision is tested here: hardware facts come from the SERVER,
not from the model. A model does not know what it is running on and would
confabulate; the server reports exactly what it committed.

Every test injects a fake fetcher, so no live server is required and no socket
is opened.
"""

import pytest

from src.nodes.backends import PORTS, probe_llamacpp, probe_ollama
from src.schemas.node import NodeKind

OLLAMA_TAGS = {
    "models": [
        {"name": "llama3.1:8b", "size": 4_700_000_000,
         "details": {"family": "llama", "parameter_size": "8.0B",
                     "quantization_level": "Q4_K_M"}},
        {"name": "phi3:mini", "size": 2_200_000_000,
         "details": {"family": "phi3", "parameter_size": "3.8B",
                     "quantization_level": "Q4_0"}},
    ]
}
OLLAMA_SHOW = {
    "model_info": {"llama.context_length": 8192},
    "capabilities": ["completion", "tools"],
}
OLLAMA_PS = {"models": [{"name": "llama3.1:8b", "size": 4_700_000_000,
                         "size_vram": 4_700_000_000}]}


def ollama_fetch(url, timeout=0.0):
    """Answer GETs like an Ollama server."""
    if url.endswith("/api/version"):
        return {"version": "0.5.4"}
    if url.endswith("/api/tags"):
        return OLLAMA_TAGS
    if url.endswith("/api/ps"):
        return OLLAMA_PS
    raise AssertionError(f"unexpected GET {url}")


def ollama_post(url, payload, timeout=0.0):
    """Answer POSTs like an Ollama server. /api/show is a POST."""
    if url.endswith("/api/show"):
        assert "name" in payload, "/api/show needs the model name in the body"
        return OLLAMA_SHOW
    raise AssertionError(f"unexpected POST {url}")


class TestOllama:
    def test_reads_version_models_and_context(self):
        result = probe_ollama("http://h:11434", ollama_fetch, ollama_post)
        assert result.ok
        assert result.kind is NodeKind.OLLAMA
        assert result.backend_version == "0.5.4"
        assert [m.name for m in result.models] == ["llama3.1:8b", "phi3:mini"]
        assert result.models[0].context_length == 8192
        assert result.models[0].quantization == "Q4_K_M"

    def test_tool_support_is_read_not_guessed(self):
        result = probe_ollama("http://h:11434", ollama_fetch, ollama_post)
        assert result.models[0].supports_tools is True
        assert result.models[0].supports_vision is False

    def test_committed_video_memory_proves_a_graphics_card(self):
        result = probe_ollama("http://h:11434", ollama_fetch, ollama_post)
        assert result.host.gpu_present is True
        assert result.host.vram_bytes == 4_700_000_000

    def test_nothing_loaded_leaves_the_card_unestablished(self):
        # size_vram of 0 does NOT mean there is no card — nothing was loaded.
        def fetch(url, timeout=0.0):
            if url.endswith("/api/ps"):
                return {"models": []}
            return ollama_fetch(url, timeout)

        result = probe_ollama("http://h:11434", fetch, ollama_post)
        assert result.host.gpu_present is None, "absent and unobserved are different"

    def test_an_unreachable_server_is_not_ok(self):
        def fetch(url, timeout=0.0):
            raise OSError("connection refused")

        result = probe_ollama("http://h:11434", fetch, ollama_post)
        assert not result.ok
        assert "connection refused" in result.note

    def test_a_failed_model_list_still_yields_a_reachable_server(self):
        def fetch(url, timeout=0.0):
            if url.endswith("/api/tags"):
                raise OSError("boom")
            return ollama_fetch(url, timeout)

        result = probe_ollama("http://h:11434", fetch, ollama_post)
        assert result.ok, "a listing failure must not discard the whole probe"
        assert result.models == []


class TestLlamaCpp:
    def test_reads_context_and_offload(self):
        def fetch(url, timeout=0.0):
            if url.endswith("/health"):
                return {"status": "ok"}
            if url.endswith("/props"):
                return {"default_generation_settings": {"n_ctx": 4096},
                        "model_path": "/models/q4.gguf"}
            if url.endswith("/v1/models"):
                return {"data": [{"id": "q4.gguf"}]}
            raise AssertionError(url)

        result = probe_llamacpp("http://h:8081", fetch)
        assert result.ok
        assert result.kind is NodeKind.LLAMACPP
        assert result.models[0].context_length == 4096


class TestPorts:
    def test_the_two_known_ports_are_declared_once(self):
        assert PORTS == ((11434, NodeKind.OLLAMA), (8081, NodeKind.LLAMACPP))
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `.venv/bin/python -m pytest tests/test_node_backends.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.nodes.backends'`

- [ ] **Step 3: Write the implementation**

```python
# src/nodes/backends.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Reading what an inference server says about itself.

**This module is the only new place in the runtime that opens a socket**, and
it is deliberately narrow. It is config-time, it runs only after a person has
granted permission, and it is not on any authoritative path — validation,
promotion, classification and export never reach it.

The design decision this module embodies: hardware facts come from the
**server**, never from the model. A language model does not know what it is
running on, and asked about its own graphics card it will produce a confident,
plausible, wrong answer. The server knows exactly, and says so for free.

Every function takes an injected ``fetch``, so tests describe a backend's API
shape without a live server and without a socket.
"""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

from src.schemas.node import HostCapability, ModelCapability, NodeKind

#: A fetcher takes (url, timeout) and returns decoded JSON from a GET.
Fetcher = Callable[[str, float], dict]

#: A poster takes (url, payload, timeout) and returns decoded JSON from a POST.
#: Named to match the kernel's existing alias, because it is the same idea.
Poster = Callable[[str, dict, float], dict]

#: The ports each backend conventionally answers on. One declaration, so the
#: scanner and the tests cannot disagree about what is worth trying.
PORTS: tuple[tuple[int, NodeKind], ...] = (
    (11434, NodeKind.OLLAMA),
    (8081, NodeKind.LLAMACPP),
)

#: Models examined in detail per server, so one machine with a large library
#: cannot make a scan run unboundedly long.
MAX_MODELS_EXAMINED = 12


def http_get_json(url: str, timeout: float = 5.0) -> dict:
    """GET a URL and decode JSON. Raises OSError on any failure."""
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    return _send(request, timeout)


def http_post_json(url: str, payload: dict, timeout: float = 10.0) -> dict:
    """POST a JSON body and decode the JSON reply. Raises OSError on failure."""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return _send(request, timeout)


def _send(request: urllib.request.Request, timeout: float) -> dict:
    """Send a prepared request, normalising every failure to OSError.

    One exception type out means callers degrade one stage rather than
    enumerating urllib's error taxonomy at six call sites.
    """
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, ValueError, TimeoutError) as exc:
        raise OSError(str(exc)) from exc


@dataclass
class ProbeResult:
    """What one server reported about itself."""

    kind: NodeKind
    ok: bool = False
    backend_version: str = ""
    models: list[ModelCapability] = field(default_factory=list)
    host: HostCapability = field(default_factory=HostCapability)
    note: str = ""


def probe_ollama(
    base_url: str,
    fetch: Fetcher = http_get_json,
    post: "Poster" = None,  # type: ignore[assignment]  # defaulted below
) -> ProbeResult:
    """Ask an Ollama server what it is and what it can do.

    A failure after the first reachability check degrades that one fact rather
    than the whole probe: a server that answers but cannot list its models is
    still a server worth recording.
    """
    post = post or http_post_json
    result = ProbeResult(kind=NodeKind.OLLAMA)
    try:
        version = fetch(f"{base_url}/api/version", 5.0)
    except OSError as exc:
        result.note = str(exc)
        return result

    result.ok = True
    result.backend_version = str(version.get("version", ""))

    try:
        listing = fetch(f"{base_url}/api/tags", 10.0)
    except OSError as exc:
        result.note = f"could not list the models: {exc}"
        listing = {"models": []}

    for entry in listing.get("models", [])[:MAX_MODELS_EXAMINED]:
        details = entry.get("details", {})
        result.models.append(
            ModelCapability(
                name=entry.get("name", ""),
                family=details.get("family", ""),
                parameter_size=details.get("parameter_size", ""),
                quantization=details.get("quantization_level", ""),
                size_bytes=int(entry.get("size", 0)),
            )
        )

    for model in result.models:
        try:
            # A POST with the name in the body — Ollama's /api/show is not a GET.
            shown = post(f"{base_url}/api/show", {"name": model.name}, 10.0)
        except OSError:
            continue
        info = shown.get("model_info", {})
        for key, value in info.items():
            if key.endswith(".context_length"):
                model.context_length = int(value)
                break
        capabilities = shown.get("capabilities", [])
        model.supports_tools = "tools" in capabilities
        model.supports_vision = "vision" in capabilities

    # A loaded model's committed video memory is the one hardware fact this API
    # gives away. Nothing loaded means nothing observed -- which is NOT the same
    # as no graphics card, so gpu_present stays None.
    try:
        running = fetch(f"{base_url}/api/ps", 5.0)
        loaded = running.get("models", [])
        vram = max((int(m.get("size_vram", 0)) for m in loaded), default=0)
        if vram > 0:
            result.host.gpu_present = True
            result.host.vram_bytes = vram
    except OSError:
        pass

    return result


def probe_llamacpp(base_url: str, fetch: Fetcher = http_get_json) -> ProbeResult:
    """Ask a llama.cpp server what it is and what it can do."""
    result = ProbeResult(kind=NodeKind.LLAMACPP)
    try:
        fetch(f"{base_url}/health", 5.0)
    except OSError as exc:
        result.note = str(exc)
        return result

    result.ok = True

    context = 0
    try:
        props = fetch(f"{base_url}/props", 10.0)
        settings = props.get("default_generation_settings", {})
        context = int(settings.get("n_ctx", 0))
        layers = settings.get("n_gpu_layers")
        if layers is not None:
            result.host.gpu_present = int(layers) > 0
    except OSError as exc:
        result.note = f"could not read the settings: {exc}"

    try:
        listing = fetch(f"{base_url}/v1/models", 10.0)
        for entry in listing.get("data", [])[:MAX_MODELS_EXAMINED]:
            result.models.append(
                ModelCapability(name=entry.get("id", ""), context_length=context)
            )
    except OSError as exc:
        result.note = f"could not list the models: {exc}"

    return result
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `.venv/bin/python -m pytest tests/test_node_backends.py -q`
Expected: PASS, 9 tests.

- [ ] **Step 5: Update the network guard, deliberately**

The phase-8 test asserting `src/kernel/models.py` is the only module reaching the network now has a second module to name. Widen it in the open, with the reason recorded.

In `tests/test_hardening.py::TestOffline::test_only_the_model_adapter_reaches_the_network`, replace the assertion:

```python
        assert offenders == {
            "src/kernel/models.py": ["urllib.error", "urllib.request"],
            "src/nodes/backends.py": ["urllib.error", "urllib.request"],
        }, (
            f"network imports moved: {offenders}. Two modules may reach the "
            f"network and no more: the model adapter, and node discovery. "
            f"Discovery is config-time, runs only after a person grants "
            f"permission, and is not on an authoritative path — validation, "
            f"promotion, classification and export never call it."
        )
```

- [ ] **Step 6: Run the hardening suite to confirm the guard still guards**

Run: `.venv/bin/python -m pytest tests/test_hardening.py -q`
Expected: PASS. The offline tests must still pass — discovery is not called by the lifecycle.

- [ ] **Step 7: Commit**

```bash
git add src/nodes/backends.py tests/test_node_backends.py tests/test_hardening.py
git commit -m "feat: read an inference server's own metadata, never the model"
```

---

