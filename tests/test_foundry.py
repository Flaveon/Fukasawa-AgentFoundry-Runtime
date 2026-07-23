# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Agent Foundry tests: generation gates, package contents, and validation.

The Phase 2 exit criteria, made executable:
* generated packages pass schema validation,
* package output carries no hidden context,
* generated agents cannot silently exceed their declared depth level.
"""

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from src.foundry.generator import (
    BuildRefusedError,
    detect_workspace_profile,
    generate_packages,
)
from src.foundry.validator import validate_package
from src.runtime.state_machine import WorkflowRuntime
from src.schemas.agent_package import AgentCapsuleContract
from src.schemas.workflow_brief import WorkflowBrief

EXAMPLE_BRIEF = (
    Path(__file__).resolve().parent.parent / "examples" / "q2c-production-handoff.yaml"
)


@pytest.fixture()
def brief() -> WorkflowBrief:
    return WorkflowRuntime.load_brief(EXAMPLE_BRIEF)


@pytest.fixture()
def cpax_workspace(tmp_path) -> Path:
    """A minimal C-Pax numbered-directory workspace with a doctrine file."""
    ws = tmp_path / "workspace"
    for d in ("02_context", "05_tasks/ready", "05_tasks/blocked", "07_agents",
              "11_outputs", "12_logs", "13_archive"):
        (ws / d).mkdir(parents=True)
    (ws / "doctrine.md").write_text("# Doctrine\nDirect, builder-minded.\n")
    return ws


class TestBuildGates:
    def test_draft_brief_is_refused(self, tmp_path):
        data = yaml.safe_load(EXAMPLE_BRIEF.read_text())
        data["status"] = "draft"
        draft_brief = WorkflowBrief.model_validate(data)
        with pytest.raises(BuildRefusedError, match="only an approved brief"):
            generate_packages(draft_brief, tmp_path / "out")

    def test_brief_without_agents_is_refused(self, brief, tmp_path):
        brief = brief.model_copy(update={"agents": []})
        with pytest.raises(BuildRefusedError, match="declares no agents"):
            generate_packages(brief, tmp_path / "out")

    def test_level_5_agent_is_refused(self, brief, tmp_path):
        data = yaml.safe_load(EXAMPLE_BRIEF.read_text())
        data["agents"][0]["depth_level"] = 5
        brief5 = WorkflowBrief.model_validate(data)
        with pytest.raises(BuildRefusedError, match="redesign-only"):
            generate_packages(brief5, tmp_path / "out")

    def test_agent_owning_conscious_transition_fails_at_schema(self):
        data = yaml.safe_load(EXAMPLE_BRIEF.read_text())
        # Hand the CONSCIOUS editor-approval transition to the writer agent.
        for t in data["transitions"]:
            if t["to_state"] == "APPROVED":
                t["owner"] = "writer-agent"
        with pytest.raises(ValidationError, match="CONSCIOUS.*owned by a human"):
            WorkflowBrief.model_validate(data)

    def test_generic_workspace_without_paths_is_refused(self, brief, tmp_path):
        with pytest.raises(BuildRefusedError, match="undefined paths are incomplete"):
            generate_packages(brief, tmp_path / "out", workspace_root=None)

    def test_cpax_workspace_without_doctrine_is_refused(self, brief, tmp_path):
        ws = tmp_path / "ws"
        (ws / "05_tasks").mkdir(parents=True)
        (ws / "11_outputs").mkdir()
        with pytest.raises(BuildRefusedError, match="doctrine.md"):
            generate_packages(brief, tmp_path / "out", workspace_root=ws)


class TestGeneration:
    def test_cpax_generation_passes_validation(self, brief, cpax_workspace, tmp_path):
        pkgs, report = generate_packages(
            brief, tmp_path / "out", workspace_root=cpax_workspace
        )
        assert len(pkgs) == 2  # writer-agent, publisher-agent
        for pkg in pkgs:
            assert validate_package(pkg) == []
        assert report.exists()
        assert "Review Checklist" in report.read_text()

    def test_cpax_profile_is_injected(self, brief, cpax_workspace, tmp_path):
        pkgs, _ = generate_packages(
            brief, tmp_path / "out", workspace_root=cpax_workspace
        )
        writer = next(p for p in pkgs if p.name == "writer-agent")
        skill = (writer / "SKILL.md").read_text()
        assert "workspace_profile: c-pax" in skill
        assert "05_tasks/blocked/" in skill
        assert "07_agents/writer-agent/" in skill  # agent_name templated in
        soul = (writer / "SOUL.md").read_text()
        assert "inherits: ../../doctrine.md" in soul

    def test_capsule_derives_from_owned_transitions(self, brief, cpax_workspace, tmp_path):
        pkgs, _ = generate_packages(
            brief, tmp_path / "out", workspace_root=cpax_workspace
        )
        publisher = next(p for p in pkgs if p.name == "publisher-agent")
        capsule = AgentCapsuleContract.model_validate(
            yaml.safe_load((publisher / "process_capsule.yaml").read_text())
        )
        assert capsule.depth_level == 0
        assert any("APPROVED -> PUBLISHED" in s.name for s in capsule.steps)
        # Publisher's evidence requirement flowed into the output schema.
        assert "final filename" in capsule.output_schema.evidence

    def test_no_hidden_context_readme_names_everything(
        self, brief, cpax_workspace, tmp_path
    ):
        pkgs, _ = generate_packages(
            brief, tmp_path / "out", workspace_root=cpax_workspace
        )
        for pkg in pkgs:
            readme = (pkg / "README.md").read_text()
            # Every package file is explained in its own README.
            for name in ("SKILL.md", "SOUL.md", "CONTRACT.md", "process_capsule.yaml",
                         "evals.yaml", "simulations.yaml", "learning_log.md",
                         "permissions.json"):
                assert name in readme, f"{pkg.name} README does not mention {name}"
            assert "draft" in readme  # maturity is stated, not implied

    def test_generic_workspace_with_explicit_paths(self, brief, tmp_path):
        paths = {
            "context": "context/",
            "tasks_ready": "tasks/ready/",
            "tasks_blocked": "tasks/blocked/",
            "outputs": "outputs/",
            "logs": "logs/",
            "agent_config": "agents/",
            "archive": "archive/",
        }
        pkgs, _ = generate_packages(brief, tmp_path / "out", explicit_paths=paths)
        for pkg in pkgs:
            assert validate_package(pkg) == []
            perms = json.loads((pkg / "permissions.json").read_text())
            assert perms["paths"]["tasks_blocked"] == "tasks/blocked/"


class TestDepthBoundary:
    """Exit criterion: generated agents cannot silently exceed declared depth."""

    def test_capsule_step_above_agent_depth_is_invalid(self):
        with pytest.raises(ValidationError, match="reach above"):
            AgentCapsuleContract.model_validate(
                {
                    "task_name": "t",
                    "owner_agent": "a",
                    "depth_level": 1,
                    "inputs": [{"name": "x"}],
                    "steps": [
                        {
                            "name": "overreach",
                            "depth_level": 3,
                            "deterministic": False,
                            "reasoning_justification": "because",
                        }
                    ],
                    "escalation_rules": [{"condition": "c", "target": "human"}],
                    "output_schema": {
                        "status": "done",
                        "evidence": "e",
                        "confidence": "c",
                        "recommended_next_step": "n",
                    },
                }
            )

    def test_tampered_package_depth_is_caught(self, brief, cpax_workspace, tmp_path):
        pkgs, _ = generate_packages(
            brief, tmp_path / "out", workspace_root=cpax_workspace
        )
        writer = next(p for p in pkgs if p.name == "writer-agent")
        # An agent quietly promoting itself in SKILL.md alone gets caught by
        # the cross-file agreement check.
        skill = (writer / "SKILL.md").read_text()
        (writer / "SKILL.md").write_text(
            skill.replace("depth_level: 2", "depth_level: 4")
        )
        findings = validate_package(writer)
        assert any("depth_level disagrees" in f for f in findings)

    def test_self_promoted_maturity_is_caught(self, brief, cpax_workspace, tmp_path):
        pkgs, _ = generate_packages(
            brief, tmp_path / "out", workspace_root=cpax_workspace
        )
        writer = next(p for p in pkgs if p.name == "writer-agent")
        # Maturity bumped everywhere, but evals still pending: caught.
        for name in ("SKILL.md", "process_capsule.yaml"):
            text = (writer / name).read_text()
            (writer / name).write_text(text.replace("maturity: draft", "maturity: validated"))
        manifest = json.loads((writer / "manifest.json").read_text())
        manifest["maturity"] = "validated"
        (writer / "manifest.json").write_text(json.dumps(manifest))
        findings = validate_package(writer)
        assert any("requires passing evals" in f for f in findings)


class TestValidatorFindings:
    def test_missing_file_is_reported(self, brief, cpax_workspace, tmp_path):
        pkgs, _ = generate_packages(
            brief, tmp_path / "out", workspace_root=cpax_workspace
        )
        (pkgs[0] / "CONTRACT.md").unlink()
        assert "missing required file: CONTRACT.md" in validate_package(pkgs[0])

    def test_removed_mandatory_eval_check_is_reported(
        self, brief, cpax_workspace, tmp_path
    ):
        pkgs, _ = generate_packages(
            brief, tmp_path / "out", workspace_root=cpax_workspace
        )
        evals_path = pkgs[0] / "evals.yaml"
        evals = yaml.safe_load(evals_path.read_text())
        del evals["checks"]["scope_compliance"]
        evals_path.write_text(yaml.safe_dump(evals))
        findings = validate_package(pkgs[0])
        assert any("scope_compliance" in f for f in findings)


class TestWorkspaceDetection:
    def test_two_markers_required(self, tmp_path):
        ws = tmp_path / "ws"
        (ws / "05_tasks").mkdir(parents=True)
        assert detect_workspace_profile(ws) == "generic"  # one marker: coincidence
        (ws / "11_outputs").mkdir()
        assert detect_workspace_profile(ws) == "c-pax"
        assert detect_workspace_profile(None) == "generic"
