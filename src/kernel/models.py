# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Model adapter — how an agent node actually calls a model.

Phase 5 wires the runtime into user models. This is the point where an
``agent`` node stops merely shelling out and instead delegates bounded
reasoning to a model, through the same Adapter protocol the kernel already
speaks.

Doctrine boundaries this respects:

* **Local-first, not cloud-locked.** The reference backends are Ollama and
  llama.cpp — LAN or localhost inference. This is a deliberate, narrow
  relaxation of the original "no network at runtime" rule: local model calls,
  not cloud dependencies. Cloud backends can register later without kernel
  changes; that decision (and its API-key handling) stays the operator's.
* **No hardcoded model identifiers.** Endpoints are named in config and
  referenced by name from graph YAML, so a graph says ``endpoint: gpu-node``,
  not an IP. The runtime resolves the name.
* **Adapters report failure, never raise.** An unreachable model makes the
  node fail, and the kernel's retry/block policy takes over — a model outage
  becomes a blocked run with a clear reason, not a crash.
"""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import yaml

from src.kernel.adapters import AdapterResult

#: Built-in defaults — localhost only, so nothing here reveals a private
#: network. Add your own LAN or remote hosts in
#: $FUKASAWA_HOME/model_endpoints.yaml (see config/model_endpoints.example.yaml).
DEFAULT_ENDPOINTS: dict[str, dict] = {
    "local-llama": {"kind": "llamacpp", "url": "http://localhost:8081"},
    "local-ollama": {"kind": "ollama", "url": "http://localhost:11434"},
}

#: A poster takes (url, payload, timeout) and returns the decoded JSON dict.
#: Injectable so the kernel can be tested without a live model node.
Poster = Callable[[str, dict, float], dict]


def http_post_json(url: str, payload: dict, timeout: float) -> dict:
    """POST a JSON body and return the decoded JSON response (stdlib only)."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


@dataclass
class ModelEndpoint:
    """One named model endpoint: a backend kind and a base URL."""

    name: str
    kind: str  # 'ollama' | 'llamacpp'
    url: str


class ModelEndpointRegistry:
    """Named model endpoints, resolved from defaults + an optional config file."""

    def __init__(self, endpoints: Optional[dict[str, dict]] = None) -> None:
        """Build from an explicit mapping, else the built-in defaults."""
        source = endpoints if endpoints is not None else DEFAULT_ENDPOINTS
        self._endpoints = {
            name: ModelEndpoint(name=name, kind=spec["kind"], url=spec["url"])
            for name, spec in source.items()
        }

    @classmethod
    def from_config(cls, path: str | Path) -> "ModelEndpointRegistry":
        """Load endpoints from a YAML file (falls back to defaults if absent)."""
        p = Path(path)
        if not p.exists():
            return cls()
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        merged = {**DEFAULT_ENDPOINTS, **data.get("endpoints", {})}
        return cls(merged)

    def get(self, name: str) -> ModelEndpoint:
        """Resolve an endpoint name. Unknown names raise KeyError with the roster."""
        if name not in self._endpoints:
            raise KeyError(
                f"no model endpoint '{name}' (known: {sorted(self._endpoints)})"
            )
        return self._endpoints[name]

    def names(self) -> list[str]:
        """Return the configured endpoint names."""
        return sorted(self._endpoints)


def _extract_ollama(response: dict) -> str:
    """Pull the assistant text out of an Ollama /api/chat response."""
    return (response.get("message") or {}).get("content", "")


def _extract_openai(response: dict) -> str:
    """Pull the assistant text out of an OpenAI-compatible response."""
    choices = response.get("choices") or []
    if not choices:
        return ""
    return (choices[0].get("message") or {}).get("content", "")


class ModelAdapter:
    """Adapter that delegates an agent node to a configured model endpoint.

    params:
        endpoint:    name of a configured endpoint (e.g. 'local-ollama', 'local-llama')
        model:       model identifier the endpoint should load
        prompt:      the user prompt (already variable-substituted by the kernel)
        system:      optional system prompt
        temperature: optional sampling temperature (default 0.2)
        timeout:     seconds before the call is abandoned (default 120)
    """

    name = "model"

    def __init__(
        self,
        registry: Optional[ModelEndpointRegistry] = None,
        poster: Poster = http_post_json,
    ) -> None:
        """Bind to an endpoint registry and a JSON poster (injectable for tests)."""
        self.registry = registry or ModelEndpointRegistry()
        self.poster = poster

    def execute(self, params: dict) -> AdapterResult:
        """Call the named model and return its text as evidence and output."""
        prompt = params.get("prompt", "")
        if not prompt:
            return AdapterResult(ok=False, note="model node has no prompt")
        try:
            endpoint = self.registry.get(params.get("endpoint", ""))
        except KeyError as exc:
            return AdapterResult(ok=False, note=str(exc))
        model = params.get("model", "")
        if not model:
            return AdapterResult(ok=False, note="model node has no model identifier")

        messages = []
        if params.get("system"):
            messages.append({"role": "system", "content": params["system"]})
        messages.append({"role": "user", "content": prompt})
        temperature = float(params.get("temperature", 0.2))
        timeout = float(params.get("timeout", 120))

        try:
            if endpoint.kind == "ollama":
                response = self.poster(
                    f"{endpoint.url}/api/chat",
                    {
                        "model": model,
                        "messages": messages,
                        "stream": False,
                        "options": {"temperature": temperature},
                    },
                    timeout,
                )
                text = _extract_ollama(response)
            elif endpoint.kind == "llamacpp":
                response = self.poster(
                    f"{endpoint.url}/v1/chat/completions",
                    {"model": model, "messages": messages, "temperature": temperature},
                    timeout,
                )
                text = _extract_openai(response)
            else:
                return AdapterResult(
                    ok=False, note=f"unknown endpoint kind '{endpoint.kind}'"
                )
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            # Local model unreachable or misbehaving: fail the node so the
            # kernel blocks the run with a clear reason. Never crash.
            return AdapterResult(
                ok=False,
                note=f"model endpoint '{endpoint.name}' ({endpoint.url}) failed: {exc}",
            )

        if not text.strip():
            return AdapterResult(
                ok=False,
                note=f"model '{model}' at '{endpoint.name}' returned empty text",
            )
        return AdapterResult(
            ok=True,
            evidence=text.strip()[:500],
            outputs={
                "response": text.strip(),
                "model": model,
                "endpoint": endpoint.name,
            },
        )
