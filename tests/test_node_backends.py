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
