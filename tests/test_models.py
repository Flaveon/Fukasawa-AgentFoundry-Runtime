# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Model adapter tests — using an injected poster, no live model node needed.

Verifies the two reference backends' request/response shapes, endpoint
resolution by name, graceful failure on an unreachable model, and that a
model node drives a real capsule transition through the kernel.
"""

from pathlib import Path

import pytest

from src.kernel.adapters import AdapterRegistry
from src.kernel.kernel import GraphRunner
from src.kernel.models import ModelAdapter, ModelEndpointRegistry
from src.runtime.ledger import RunLedger
from src.schemas.graph import GraphRunStatus, GraphSpec

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_BRIEF = ROOT / "examples" / "q2c-production-handoff.yaml"


def _ollama_poster(recorder=None):
    """A fake poster mimicking Ollama /api/chat."""

    def post(url, payload, timeout):
        if recorder is not None:
            recorder.append((url, payload))
        return {"message": {"content": f"drafted from: {payload['messages'][-1]['content'][:20]}"}}

    return post


def _llamacpp_poster():
    """A fake poster mimicking an OpenAI-compatible /v1/chat/completions."""

    def post(url, payload, timeout):
        return {"choices": [{"message": {"content": "llamacpp says hi"}}]}

    return post


class TestModelAdapter:
    def test_ollama_shape_and_endpoint_resolution(self):
        recorder = []
        adapter = ModelAdapter(
            ModelEndpointRegistry({"gpu-node": {"kind": "ollama", "url": "http://x:11434"}}),
            poster=_ollama_poster(recorder),
        )
        result = adapter.execute(
            {"endpoint": "gpu-node", "model": "qwen", "prompt": "write a draft"}
        )
        assert result.ok
        assert "drafted from" in result.evidence
        assert result.outputs["endpoint"] == "gpu-node"
        url, payload = recorder[0]
        assert url == "http://x:11434/api/chat"
        assert payload["model"] == "qwen"
        assert payload["stream"] is False

    def test_llamacpp_openai_shape(self):
        adapter = ModelAdapter(
            ModelEndpointRegistry(
                {"local": {"kind": "llamacpp", "url": "http://localhost:8081"}}
            ),
            poster=_llamacpp_poster(),
        )
        result = adapter.execute(
            {"endpoint": "local", "model": "qwen", "prompt": "hi"}
        )
        assert result.ok and result.evidence == "llamacpp says hi"

    def test_unknown_endpoint_fails_gracefully(self):
        adapter = ModelAdapter(ModelEndpointRegistry({}), poster=_llamacpp_poster())
        result = adapter.execute({"endpoint": "ghost", "model": "m", "prompt": "x"})
        assert not result.ok and "no model endpoint 'ghost'" in result.note

    def test_unreachable_model_fails_not_raises(self):
        def boom(url, payload, timeout):
            raise OSError("connection refused")

        adapter = ModelAdapter(
            ModelEndpointRegistry({"n": {"kind": "ollama", "url": "http://x"}}),
            poster=boom,
        )
        result = adapter.execute({"endpoint": "n", "model": "m", "prompt": "x"})
        assert not result.ok and "failed" in result.note


    def test_json_decode_error_fails_not_raises(self):
        import json
        def boom_json(url, payload, timeout):
            raise json.JSONDecodeError("msg", "doc", 0)

        adapter = ModelAdapter(
            ModelEndpointRegistry({"n": {"kind": "ollama", "url": "http://x"}}),
            poster=boom_json,
        )
        result = adapter.execute({"endpoint": "n", "model": "m", "prompt": "x"})
        assert not result.ok and "failed" in result.note

    def test_empty_response_is_a_failure(self):
        adapter = ModelAdapter(
            ModelEndpointRegistry({"n": {"kind": "ollama", "url": "http://x"}}),
            poster=lambda u, p, t: {"message": {"content": "   "}},
        )
        result = adapter.execute({"endpoint": "n", "model": "m", "prompt": "x"})
        assert not result.ok and "empty" in result.note

    def test_ollama_missing_message_key(self):
        adapter = ModelAdapter(
            ModelEndpointRegistry({"n": {"kind": "ollama", "url": "http://x"}}),
            poster=lambda u, p, t: {"something_else": "val"},
        )
        result = adapter.execute({"endpoint": "n", "model": "m", "prompt": "x"})
        assert not result.ok and "empty" in result.note

    def test_missing_prompt_or_model(self):
        adapter = ModelAdapter(ModelEndpointRegistry({"n": {"kind": "ollama", "url": "u"}}))
        assert not adapter.execute({"endpoint": "n", "model": "m"}).ok
        assert not adapter.execute({"endpoint": "n", "prompt": "p"}).ok


class TestEndpointConfig:
    def test_defaults_present(self):
        registry = ModelEndpointRegistry()
        assert "local-llama" in registry.names()
        assert registry.get("local-ollama").kind == "ollama"
        # Defaults are localhost only — no private hosts leak into the repo.
        assert all("localhost" in registry.get(n).url for n in registry.names())

    def test_config_file_merges_over_defaults(self, tmp_path):
        cfg = tmp_path / "model_endpoints.yaml"
        cfg.write_text(
            "endpoints:\n  house:\n    kind: ollama\n    url: http://house:11434\n"
        )
        registry = ModelEndpointRegistry.from_config(cfg)
        assert "house" in registry.names()
        assert "local-llama" in registry.names()  # defaults still there

    def test_missing_config_falls_back(self, tmp_path):
        registry = ModelEndpointRegistry.from_config(tmp_path / "nope.yaml")
        assert "local-ollama" in registry.names()


class TestModelNodeInKernel:
    """A model node drives a real capsule transition through the governed runtime."""

    def test_model_node_advances_capsule(self, tmp_path):
        registry = AdapterRegistry(
            model_adapter=ModelAdapter(
                ModelEndpointRegistry({"n": {"kind": "ollama", "url": "http://x"}}),
                poster=_ollama_poster(),
            )
        )
        runner = GraphRunner(
            RunLedger(tmp_path / "t.db"), registry=registry, handoff_dir=tmp_path / "h"
        )
        brief = runner.runtime.load_brief(EXAMPLE_BRIEF)
        graph = GraphSpec.model_validate(
            {
                "graph_id": "model-graph",
                "workflow": "q2c-production-handoff",
                "nodes": [
                    {
                        "node_id": "draft",
                        "kind": "agent",
                        "adapter": "model",
                        "params": {
                            "endpoint": "n",
                            "model": "qwen",
                            "prompt": "Draft an article about {topic}",
                        },
                        "produces_transition": {
                            "to_state": "DRAFT_READY",
                            "evidence_template": "draft by {model}: {response}",
                        },
                    }
                ],
            }
        )
        state = runner.start(graph, brief, variables={"topic": "agent governance"})
        state = runner.run(graph, state)
        assert state.status is GraphRunStatus.COMPLETE
        capsule = runner.ledger.load_capsule(state.capsule_id)
        assert capsule.state == "DRAFT_READY"
        # The model's output became the transition evidence in the ledger.
        assert "draft by qwen" in capsule.evidence
