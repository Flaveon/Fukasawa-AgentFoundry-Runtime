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
from typing import Callable, Optional

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
    post: Optional[Poster] = None,
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
