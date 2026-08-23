# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Contracts for an inference node and what it can do."""

import pytest
from pydantic import ValidationError

from src.schemas.node import (
    SCHEMA_VERSION,
    HostCapability,
    InferenceNode,
    ModelCapability,
    NodeKind,
    Provenance,
    ScanConsent,
    ScanScope,
    slugify,
)


class TestSlug:
    @pytest.mark.parametrize(
        "label,expected",
        [
            ("Home PC", "home-pc"),
            ("  Studio   Mac  ", "studio-mac"),
            ("GPU box #2", "gpu-box-2"),
            ("Ollama", "ollama"),
        ],
    )
    def test_labels_become_slugs(self, label, expected):
        assert slugify(label) == expected

    def test_a_label_with_nothing_usable_falls_back(self):
        # An id is required, so an unusable label must still yield one rather
        # than an empty string that fails validation later.
        assert slugify("!!!") == "computer"


class TestInferenceNode:
    def test_minimal_node_is_valid(self):
        node = InferenceNode(node_id="home-pc", label="Home PC",
                             kind=NodeKind.OLLAMA, url="http://localhost:11434")
        assert node.schema_version == SCHEMA_VERSION
        assert node.reachable is False
        assert node.models == []
        assert node.host.gpu_present is None

    def test_node_id_must_be_a_slug(self):
        with pytest.raises(ValidationError):
            InferenceNode(node_id="Home PC", label="x",
                          kind=NodeKind.OLLAMA, url="http://h")

    def test_unknown_field_is_refused_by_name(self):
        with pytest.raises(ValidationError) as exc:
            InferenceNode(node_id="a", label="x", kind=NodeKind.OLLAMA,
                          url="http://h", speed="fast")
        assert "speed" in str(exc.value)

    def test_round_trips_through_json(self):
        node = InferenceNode(
            node_id="home-pc", label="Home PC", kind=NodeKind.OLLAMA,
            url="http://localhost:11434", reachable=True,
            models=[ModelCapability(name="llama3.1:8b", context_length=8192)],
            host=HostCapability(gpu_present=True, vram_bytes=6_000_000_000),
            provenance={"models": Provenance.DETECTED},
        )
        again = InferenceNode.model_validate(node.model_dump(mode="json"))
        assert again == node

    def test_source_of_reports_unknown_for_unrecorded_fields(self):
        node = InferenceNode(node_id="a", label="x", kind=NodeKind.OLLAMA,
                             url="http://h",
                             provenance={"label": Provenance.DECLARED})
        assert node.source_of("label") is Provenance.DECLARED
        assert node.source_of("host.vram_bytes") is Provenance.UNKNOWN


class TestConsent:
    def test_defaults_to_no_scanning(self):
        # The safe default: nothing is scanned until somebody says so.
        assert ScanConsent().scope is ScanScope.NONE

    def test_records_who_and_when(self):
        consent = ScanConsent(scope=ScanScope.THIS_MACHINE, granted_by="sam")
        assert consent.granted_by == "sam"
