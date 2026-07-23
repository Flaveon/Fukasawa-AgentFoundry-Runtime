# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Adapter layer — how the kernel touches the world without marrying it.

An adapter is anything that can execute a node's params and report back what
happened, with evidence. The kernel knows the Adapter protocol and nothing
else; a future OpenAI, local-model, or git adapter plugs into the same
registry without kernel changes (architecture doctrine: adapters connect
the runtime to tools without making those tools the architecture).

Phase 4 ships the two local-first adapters the pilot graph needs:

* ``filesystem`` — deterministic file operations (exists, read, write, copy)
* ``shell`` — runs a command and captures its output as evidence

Adapters report failure by returning ok=False, never by raising — the
kernel owns retry and blocking policy, and an adapter that throws steals
that decision.
"""

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol


@dataclass
class AdapterResult:
    """What one adapter execution produced."""

    ok: bool
    evidence: str = ""
    outputs: dict = field(default_factory=dict)
    note: str = ""


class Adapter(Protocol):
    """The kernel's only requirement of a tool: run params, report honestly."""

    name: str

    def execute(self, params: dict) -> AdapterResult:  # pragma: no cover - protocol
        """Execute one node's parameters and return the result."""
        ...


class FilesystemAdapter:
    """Deterministic file operations. Same input, same output, no reasoning.

    params:
        op:   exists | read | write | copy
        path: target path (exists/read/write)
        src, dest: for copy
        content: for write

    Optional ``workspace_root`` confines every path to a jail directory —
    defense-in-depth so even a trusted-but-careless graph cannot read or
    write outside the workspace (e.g. ``~/.ssh``). Without a root, paths are
    unconfined (single-operator local behavior).
    """

    name = "filesystem"

    def __init__(self, workspace_root: str | Path | None = None) -> None:
        """Optionally confine all operations under ``workspace_root``."""
        self.workspace_root = (
            Path(workspace_root).resolve() if workspace_root else None
        )

    def _resolve(self, raw: str) -> Path:
        """Resolve a path, refusing any that escapes the workspace jail."""
        path = Path(raw).resolve()
        if self.workspace_root is not None:
            if not path.is_relative_to(self.workspace_root):
                raise PermissionError(
                    f"path '{raw}' resolves outside the workspace jail "
                    f"'{self.workspace_root}'"
                )
        return path

    def execute(self, params: dict) -> AdapterResult:
        """Perform one file operation and report evidence (paths, sizes)."""
        op = params.get("op", "")
        try:
            if op == "exists":
                path = self._resolve(params["path"])
                if path.exists():
                    return AdapterResult(
                        ok=True,
                        evidence=f"{path} exists ({path.stat().st_size} bytes)",
                        outputs={"path": str(path)},
                    )
                return AdapterResult(ok=False, note=f"{path} does not exist")
            if op == "read":
                path = self._resolve(params["path"])
                content = path.read_text(encoding="utf-8")
                return AdapterResult(
                    ok=True,
                    evidence=f"read {len(content)} chars from {path}",
                    outputs={"path": str(path), "content": content},
                )
            if op == "write":
                path = self._resolve(params["path"])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(params.get("content", ""), encoding="utf-8")
                return AdapterResult(
                    ok=True,
                    evidence=f"wrote {path}",
                    outputs={"path": str(path)},
                )
            if op == "copy":
                src, dest = self._resolve(params["src"]), self._resolve(params["dest"])
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                return AdapterResult(
                    ok=True,
                    evidence=f"copied {src} -> {dest}",
                    outputs={"src": str(src), "dest": str(dest)},
                )
            return AdapterResult(ok=False, note=f"unknown filesystem op '{op}'")
        except (OSError, KeyError, PermissionError) as exc:
            return AdapterResult(ok=False, note=f"filesystem {op} failed: {exc}")


class ShellAdapter:
    """Runs a local command and captures stdout as evidence.

    params:
        command: the command line to run (via the shell, local only)
        cwd:     working directory (optional)
        timeout: seconds before the command is killed (default 60)

    Commands come from graph YAML the operator wrote — the adapter runs the
    operator's own automation, it is not an escape hatch for agents to
    invent commands (agents cannot edit graphs; see CONTRACT boundaries).
    """

    name = "shell"

    def execute(self, params: dict) -> AdapterResult:
        """Run the command; nonzero exit or timeout is a failed attempt."""
        command = params.get("command", "")
        if not command:
            return AdapterResult(ok=False, note="shell node has no command")
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=params.get("cwd") or None,
                capture_output=True,
                text=True,
                timeout=float(params.get("timeout", 60)),
            )
        except subprocess.TimeoutExpired:
            return AdapterResult(
                ok=False, note=f"command timed out: {command}"
            )
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()
        if proc.returncode != 0:
            return AdapterResult(
                ok=False,
                note=f"exit {proc.returncode}: {stderr or stdout or command}",
            )
        return AdapterResult(
            ok=True,
            evidence=stdout[:500] or f"command succeeded: {command}",
            outputs={"stdout": stdout, "command": command},
        )


class AdapterRegistry:
    """Where the kernel finds adapters by name. Extensible by registration."""

    def __init__(
        self,
        workspace_root: str | Path | None = None,
        model_adapter: Optional["Adapter"] = None,
    ) -> None:
        """Start with the built-in local-first adapters.

        ``workspace_root`` jails the filesystem adapter to a directory —
        pass the run's workspace to confine file operations for shared graphs.
        ``model_adapter`` registers a model backend under the name 'model';
        omitted here to avoid importing model config unless it is needed.
        """
        self._adapters: dict[str, Adapter] = {}
        for adapter in (FilesystemAdapter(workspace_root), ShellAdapter()):
            self.register(adapter)
        if model_adapter is not None:
            self.register(model_adapter)

    def register(self, adapter: Adapter) -> None:
        """Add or replace an adapter. Later phases plug model adapters in here."""
        self._adapters[adapter.name] = adapter

    def get(self, name: str) -> Adapter:
        """Look up an adapter. Unknown names raise KeyError with the roster."""
        if name not in self._adapters:
            raise KeyError(
                f"no adapter '{name}' registered (available: {sorted(self._adapters)})"
            )
        return self._adapters[name]
