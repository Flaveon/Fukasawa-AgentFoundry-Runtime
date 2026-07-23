# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""The orchestration kernel — a small state graph over the governed runtime.

The GraphRunner executes GraphSpec nodes one at a time:

* deterministic and agent nodes run through adapters,
* nodes that declare a transition advance the workflow capsule through the
  SAME state machine as a manual run — same ledger, same evidence rules,
  same non-conformance handling,
* human gates pause the run durably; a decision resumes it,
* failing nodes retry up to their policy, then the run blocks with a stated
  reason, a stated next action, and a written handoff artifact,
* after every node the GraphRunState checkpoint is saved, so a graph run
  survives process death and resumes exactly where it stopped.

The kernel never bypasses governance: it cannot advance without evidence,
cannot approve its own gates, and cannot delete its own trace.
"""

import uuid
from pathlib import Path
from typing import Optional

import yaml

from src.kernel.adapters import AdapterRegistry, AdapterResult
from src.runtime.handoff import DEFAULT_HANDOFF_DIR, write_handoff
from src.runtime.ledger import RunLedger
from src.runtime.review_gate import ReviewDecision
from src.runtime.state_machine import NonConformanceError, WorkflowRuntime
from src.schemas.graph import (
    GraphNode,
    GraphRunState,
    GraphRunStatus,
    GraphSpec,
    NodeExecution,
    NodeKind,
)
from src.schemas.process_capsule import CapsuleStatus
from src.schemas.workflow_brief import WorkflowBrief
from src.security.signing import content_hash
from src.security.trust import TrustStore


class GraphSpecError(Exception):
    """Raised when a graph cannot be run against its brief."""


class UntrustedGraphError(Exception):
    """Raised when signature enforcement is on and a graph is not trusted."""


def graph_fingerprint(graph: GraphSpec) -> str:
    """Stable content hash of a graph, used for pinning and signing.

    Hashes the validated, normalized model dump rather than raw file bytes,
    so equivalent graphs that differ only in YAML formatting share a hash.
    """
    return content_hash(graph.model_dump(mode="json"))


def load_graph(path: str | Path) -> GraphSpec:
    """Load and validate a GraphSpec from YAML."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return GraphSpec.model_validate(raw)


def _render(value, variables: dict[str, str]):
    """Recursively substitute {variable} placeholders in node params."""
    if isinstance(value, str):
        try:
            return value.format(**variables)
        except (KeyError, IndexError) as exc:
            raise GraphSpecError(
                f"param '{value}' references unknown variable: {exc}"
            ) from exc
    if isinstance(value, dict):
        return {k: _render(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [_render(v, variables) for v in value]
    return value


class GraphRunner:
    """Executes workflow graphs against the governed runtime."""

    def __init__(
        self,
        ledger: RunLedger,
        registry: Optional[AdapterRegistry] = None,
        handoff_dir: str | Path = DEFAULT_HANDOFF_DIR,
        trust_store: Optional[TrustStore] = None,
    ) -> None:
        """Bind the runner to a ledger, an adapter registry, and a handoff dir.

        Passing a ``trust_store`` turns on signature enforcement: a graph
        will only run if it carries a signature from a key the store trusts.
        Without one, the runner behaves as before (local, unenforced) — safe
        for a single operator, and the CLI opts into enforcement explicitly.
        """
        self.ledger = ledger
        self.runtime = WorkflowRuntime(ledger)
        self.registry = registry or AdapterRegistry()
        self.handoff_dir = Path(handoff_dir)
        self.trust_store = trust_store

    # ------------------------------------------------------------------- start

    def _require_trusted(self, graph: GraphSpec, signature: Optional[str]) -> None:
        """Enforce that a graph is signed by a trusted key, if enforcement is on.

        Signing is the gate that makes a shared graph safe to run: the runner
        executes it only when a human has vouched for the signer. A missing
        or invalid signature is refused, not warned about.
        """
        if self.trust_store is None:
            return
        payload = graph.model_dump(mode="json")
        if not signature:
            raise UntrustedGraphError(
                f"graph '{graph.graph_id}' is unsigned but signature "
                f"enforcement is on. Sign it (fukasawa graph sign) or add the "
                f"author's key to your trust store."
            )
        if not self.trust_store.is_trusted_signature(payload, signature):
            raise UntrustedGraphError(
                f"graph '{graph.graph_id}' is not signed by any trusted key. "
                f"Refusing to run it. Add the author's key with "
                f"'fukasawa trust add' only if you vouch for them."
            )

    def start(
        self,
        graph: GraphSpec,
        brief: WorkflowBrief,
        variables: Optional[dict[str, str]] = None,
        operator: Optional[str] = None,
        brief_path: str | Path | None = None,
        signature: Optional[str] = None,
    ) -> GraphRunState:
        """Validate the graph against the brief and open a checkpointed run.

        When the runner has a trust store, ``signature`` must be a valid
        signature over the graph by a trusted key or the run is refused.
        """
        self._require_trusted(graph, signature)
        findings = graph.validate_against_brief(brief)
        if findings:
            raise GraphSpecError(
                "graph does not fit its brief: " + "; ".join(findings)
            )
        capsule, run = self.runtime.start(
            brief, operator=operator, brief_path=brief_path
        )
        state = GraphRunState(
            graph_run_id=f"graph-{uuid.uuid4().hex[:8]}",
            graph_id=graph.graph_id,
            workflow_id=brief.id,
            run_id=run.run_id,
            capsule_id=capsule.id,
            graph_hash=graph_fingerprint(graph),
            current_node=graph.entry_node.node_id,
            variables=variables or {},
        )
        self.ledger.save_graph_run(state)
        return state

    # -------------------------------------------------------------------- step

    def step(self, graph: GraphSpec, state: GraphRunState) -> GraphRunState:
        """Execute the current node once and checkpoint the outcome.

        Returns the updated state. status tells the caller what happened:
        RUNNING (keep stepping), PAUSED_HUMAN (a gate wants a decision),
        BLOCKED (retries exhausted), COMPLETE, or FAILED (non-conformance).
        """
        if state.status not in (GraphRunStatus.RUNNING,):
            return state
        node = graph.node(state.current_node)

        if node.kind is NodeKind.HUMAN_GATE:
            # Pause durably: the workflow run enters human_review, the
            # handoff artifact says why, and the checkpoint holds position.
            run = self.ledger.load_run(state.run_id)
            self.runtime.enter_human_review(
                run, reason=node.gate_reason, reviewer=run.operator
            )
            state.status = GraphRunStatus.PAUSED_HUMAN
            state.touch()
            self.ledger.save_graph_run(state)
            self._emit_handoff(state)
            return state

        result = self._execute_adapter(node, state)
        attempt = state.attempts_on_current + 1
        state.history.append(
            NodeExecution(
                node_id=node.node_id,
                attempt=attempt,
                ok=result.ok,
                evidence=result.evidence,
                note=result.note,
            )
        )

        if not result.ok:
            state.attempts_on_current = attempt
            if attempt < node.retry.max_attempts:
                # Retry: same node, next step() call attempts again.
                state.touch()
                self.ledger.save_graph_run(state)
                return state
            # Retries exhausted: block the run with reason + next action and
            # leave a blocked-state artifact (the handoff file).
            run = self.ledger.load_run(state.run_id)
            self.runtime.block_run(
                run,
                reason=(
                    f"node '{node.node_id}' failed {attempt} attempt(s): "
                    f"{result.note}"
                ),
                next_action=(
                    f"fix the cause, then: fukasawa graph resume "
                    f"{state.graph_run_id}"
                ),
            )
            state.status = GraphRunStatus.BLOCKED
            state.touch()
            self.ledger.save_graph_run(state)
            self._emit_handoff(state)
            return state

        # Success: perform the node's transition, if it declares one.
        state.attempts_on_current = 0
        if node.produces_transition is not None:
            # Evidence templates may reference run variables and adapter
            # outputs alike; outputs win on name collision.
            template_context = {**state.variables, **result.outputs}
            evidence = (
                node.produces_transition.evidence_template.format(**template_context)
                if node.produces_transition.evidence_template
                else result.evidence
            )
            try:
                self._advance(state, node.produces_transition.to_state, evidence)
            except NonConformanceError as exc:
                # The brief said no. The capsule/run are already frozen and
                # the NCR recorded by the state machine; the graph fails.
                state.status = GraphRunStatus.FAILED
                state.history[-1].note = f"non-conformance: {exc}"
                state.touch()
                self.ledger.save_graph_run(state)
                self._emit_handoff(state)
                return state

        self._move_to_next(graph, node, state)
        return state

    def decide(
        self,
        graph: GraphSpec,
        state: GraphRunState,
        decision: ReviewDecision,
        evidence: str = "",
        note: str = "",
    ) -> GraphRunState:
        """Apply a human's gate decision and continue or fail the run.

        APPROVE advances through the gate's transition (if any). REJECT
        freezes the capsule in NON_CONFORMANCE and fails the run. FLAG
        records the concern and proceeds like APPROVE.
        """
        if state.status is not GraphRunStatus.PAUSED_HUMAN:
            raise GraphSpecError(
                f"graph run {state.graph_run_id} is {state.status.value}, "
                f"not paused at a gate"
            )
        node = graph.node(state.current_node)
        run = self.ledger.load_run(state.run_id)
        brief = self.ledger.load_workflow(state.workflow_id)
        capsule = self.ledger.load_capsule(state.capsule_id)

        if decision is ReviewDecision.REJECT:
            self.runtime.resolve_gate(run, approved=False)
            self.runtime.mark_non_conformance(
                brief, capsule, note or f"rejected at gate '{node.node_id}'", run=run
            )
            state.status = GraphRunStatus.FAILED
            state.history.append(
                NodeExecution(
                    node_id=node.node_id, attempt=1, ok=False,
                    evidence=evidence, note=note or "REJECT",
                )
            )
            state.touch()
            self.ledger.save_graph_run(state)
            self._emit_handoff(state)
            return state

        if decision is ReviewDecision.FLAG:
            self.runtime.flag(brief, capsule, note or "flagged at gate")
        self.runtime.resolve_gate(run, approved=True)
        state.status = GraphRunStatus.RUNNING
        state.history.append(
            NodeExecution(
                node_id=node.node_id, attempt=1, ok=True,
                evidence=evidence, note=decision.value,
            )
        )
        if node.produces_transition is not None:
            try:
                self._advance(state, node.produces_transition.to_state, evidence)
            except NonConformanceError as exc:
                state.status = GraphRunStatus.FAILED
                state.history[-1].note = f"non-conformance: {exc}"
                state.touch()
                self.ledger.save_graph_run(state)
                self._emit_handoff(state)
                return state
        self._move_to_next(graph, node, state)
        return state

    # -------------------------------------------------------------- run/resume

    def run(self, graph: GraphSpec, state: GraphRunState) -> GraphRunState:
        """Step until the run completes, blocks, fails, or pauses for a human."""
        while state.status is GraphRunStatus.RUNNING:
            state = self.step(graph, state)
        return state

    def resume(
        self, graph: GraphSpec, graph_run_id: str, signature: Optional[str] = None
    ) -> GraphRunState:
        """Reload a checkpoint and continue. Blocked runs re-enter RUNNING.

        Paused-at-gate runs stay paused — resuming does not decide for the
        human; the caller must collect a decision and call decide().

        Two integrity checks before anything runs:
        * the supplied graph must hash-match the graph the run started with
          (a resume cannot swap in a different graph), and
        * if trust enforcement is on, the graph must still be trusted-signed.
        """
        state = self.ledger.load_graph_run(graph_run_id)
        if state.graph_hash and graph_fingerprint(graph) != state.graph_hash:
            raise GraphSpecError(
                f"graph does not match the one this run started with "
                f"(hash mismatch). Refusing to resume '{graph_run_id}' under a "
                f"different graph."
            )
        self._require_trusted(graph, signature)
        if state.status is GraphRunStatus.BLOCKED:
            run = self.ledger.load_run(state.run_id)
            # Taking the next action: unblock the workflow run and retry the
            # failed node from a clean attempt count.
            self.runtime.resume_run(run.run_id)
            state.status = GraphRunStatus.RUNNING
            state.attempts_on_current = 0
            state.touch()
            self.ledger.save_graph_run(state)
        if state.status is GraphRunStatus.RUNNING:
            return self.run(graph, state)
        return state

    # ----------------------------------------------------------------- private

    def _execute_adapter(self, node: GraphNode, state: GraphRunState) -> AdapterResult:
        """Render params with run variables and execute the node's adapter."""
        try:
            adapter = self.registry.get(node.adapter)
            params = _render(node.params, state.variables)
        except (KeyError, GraphSpecError) as exc:
            return AdapterResult(ok=False, note=str(exc))
        return adapter.execute(params)

    def _advance(self, state: GraphRunState, to_state: str, evidence: str) -> None:
        """Advance the capsule through the governed state machine."""
        brief = self.ledger.load_workflow(state.workflow_id)
        capsule = self.ledger.load_capsule(state.capsule_id)
        run = self.ledger.load_run(state.run_id)
        self.runtime.advance(brief, capsule, to_state, evidence, run=run)

    def _move_to_next(
        self, graph: GraphSpec, node: GraphNode, state: GraphRunState
    ) -> None:
        """Advance the cursor, or finish the graph when there is no next node."""
        if node.next is not None:
            state.current_node = node.next
            state.status = GraphRunStatus.RUNNING
        else:
            capsule = self.ledger.load_capsule(state.capsule_id)
            # A graph may legitimately end with more workflow left (partial
            # orchestration); only a frozen capsule fails the graph.
            state.status = (
                GraphRunStatus.FAILED
                if capsule.status is CapsuleStatus.NON_CONFORMANCE
                else GraphRunStatus.COMPLETE
            )
        state.touch()
        self.ledger.save_graph_run(state)
        if state.status is not GraphRunStatus.RUNNING:
            self._emit_handoff(state)

    def _emit_handoff(self, state: GraphRunState) -> Path:
        """Write the final/blocked/paused handoff artifact for the graph's run."""
        brief = self.ledger.load_workflow(state.workflow_id)
        capsule = self.ledger.load_capsule(state.capsule_id)
        run = self.ledger.load_run(state.run_id)
        return write_handoff(run, brief, capsule, self.handoff_dir)
