# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Handoff file tests: the Phase 1 exit criterion made executable.

'Handoff files include artifact paths, next action, and review gate status.'
If any of these sections goes missing, these tests fail — the exit criterion
cannot silently regress.
"""

from pathlib import Path

import pytest

from src.runtime.handoff import write_handoff
from src.runtime.ledger import RunLedger
from src.runtime.state_machine import WorkflowRuntime

EXAMPLE_BRIEF = (
    Path(__file__).resolve().parent.parent / "examples" / "q2c-production-handoff.yaml"
)


@pytest.fixture()
def started(tmp_path):
    runtime = WorkflowRuntime(RunLedger(tmp_path / "test.db"))
    brief = runtime.load_brief(EXAMPLE_BRIEF)
    capsule, run = runtime.start(brief, brief_path=EXAMPLE_BRIEF)
    return runtime, brief, capsule, run, tmp_path


class TestHandoffContents:
    def test_handoff_has_all_required_sections(self, started):
        runtime, brief, capsule, run, tmp_path = started
        path = write_handoff(run, brief, capsule, tmp_path / "handoffs")
        text = path.read_text()
        assert "## Artifact Paths" in text
        assert "## Next Action" in text
        assert "## Review Gate Status" in text

    def test_handoff_lists_actual_artifact_paths(self, started):
        runtime, brief, capsule, run, tmp_path = started
        capsule = runtime.advance(brief, capsule, "DRAFT_READY", "draft done", run=run)
        runtime.add_output_artifact(
            run, "~/substack/2026-07-23/draft.md", kind="draft", produced_by="writer-agent"
        )
        text = write_handoff(run, brief, capsule, tmp_path / "handoffs").read_text()
        # Input brief and produced output both appear with their paths.
        assert str(EXAMPLE_BRIEF) in text
        assert "~/substack/2026-07-23/draft.md" in text
        assert "produced by writer-agent" in text

    def test_blocked_handoff_carries_reason_and_next_action(self, started):
        runtime, brief, capsule, run, tmp_path = started
        runtime.block_run(run, reason="editor unavailable", next_action="resume Monday")
        text = write_handoff(run, brief, capsule, tmp_path / "handoffs").read_text()
        assert "editor unavailable" in text
        assert "resume Monday" in text

    def test_handoff_overwrites_for_same_run(self, started):
        runtime, brief, capsule, run, tmp_path = started
        directory = tmp_path / "handoffs"
        first = write_handoff(run, brief, capsule, directory)
        capsule = runtime.advance(brief, capsule, "DRAFT_READY", "draft done", run=run)
        second = write_handoff(run, brief, capsule, directory)
        assert first == second  # same path — the handoff holds *now*
        assert "DRAFT_READY" in second.read_text()
        assert len(list(directory.glob("*.md"))) == 1
