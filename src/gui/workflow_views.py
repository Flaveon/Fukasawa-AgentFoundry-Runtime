# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""The Workflow tab — capture to export, one stage at a time.

**This module decides nothing.** Every question it can ask is answered by
`src.gui.services`; the code here reads entry boxes, calls a service, and
renders what comes back. That is not stylistic — a rule implemented twice is a
rule that will be enforced differently in two places, and the desktop is the
easy place for that to happen unnoticed (risk R3). The import-law test in
`tests/test_gui_workflow.py` fails if this file ever imports the runtime.

Layout follows the lifecycle rather than the widget toolkit: a stage column on
the left showing how far the work has come, and a detail pane on the right with
the actions available at the selected stage. It is the same shape as
`fukasawa workflow status`, so an operator who learns one has learned the other.

**Long work runs off the UI thread** (ADR-007 §3). Each handler splits in two:

* ``run_*`` — synchronous, calls the service, returns the result. Tests call
  these directly, and they are what the worker thread executes.
* ``on_*`` — starts the worker and returns immediately, so the window never
  freezes. Results marshal back through ``after()``.

Keeping the synchronous half public is what lets the whole tab be tested without
a display, and without pretending a thread is not there.
"""

import queue
import threading
from tkinter import filedialog

import customtkinter as ctk

from src.gui import services
from src.gui.dialogs import ReasonDialog
from src.gui.step_editor_view import StepEditor
from src.gui.tables import Group, Row, Table

#: How often the UI thread checks for finished worker results, in milliseconds.
#: Short enough to feel immediate, long enough not to spin.
_POLL_MS = 40

PRIMARY = "#A855F7"
SECONDARY = "#FF6EC7"
MUTED = ("gray45", "gray60")

#: Plain-language label and one-line purpose for each lifecycle stage.
STAGE_LABELS = {
    "draft": ("1. Draft", "What actually happens, gaps included."),
    "accountable": ("2. Accountable", "Promoted once the blocking gaps are closed."),
    "assessed": ("3. Assessed", "Who should perform each step."),
    "cooperative": ("4. Assigned", "Executors chosen, and approved by a person."),
    "exported": ("5. Exported", "A brief the runtime can execute."),
    "runs": ("6. Runs", "What happened when it ran."),
}


class WorkflowTab(ctk.CTkFrame):
    """The lifecycle view: stage column, detail pane, results log."""

    def __init__(self, parent) -> None:
        """Build the tab. Does not touch the ledger until an action is run."""
        super().__init__(parent, fg_color="transparent")
        self.pack(fill="both", expand=True)
        self.selected_stage = "draft"
        self._busy = False
        #: Worker results waiting to be delivered on the UI thread.
        self._results: queue.Queue = queue.Queue()
        self._poll_id = None
        #: The worker currently running, if any. Held so teardown can wait for
        #: it: a daemon thread still inside SQLite when the interpreter starts
        #: shutting down is a way to lose a write, or worse.
        self._worker: threading.Thread | None = None
        self._build()
        self._schedule_poll()

    # ------------------------------------------------------------- structure

    def _build(self) -> None:
        """Lay out the stage column, the action pane, and the results log."""
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(10, 0))

        self.workflow_entry = self._labelled(top, "Workflow id", "substack-publication")
        self.draft_entry = self._file_row(top, "Draft file")
        self.db_entry = self._labelled(top, "Ledger database", "fukasawa.db")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=10, pady=10)

        self.stage_column = ctk.CTkFrame(body, width=210)
        self.stage_column.pack(side="left", fill="y", padx=(0, 10))
        ctk.CTkLabel(
            self.stage_column,
            text="Lifecycle",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=PRIMARY,
        ).pack(pady=(10, 6), padx=10)
        self.stage_buttons: dict[str, ctk.CTkButton] = {}
        self.stage_marks: dict[str, ctk.CTkLabel] = {}
        for stage in services.STAGES:
            self._stage_row(stage)

        right = ctk.CTkFrame(body, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True)

        self.actions = ctk.CTkFrame(right, fg_color="transparent")
        self.actions.pack(fill="x")

        # The summary lives outside the swappable region, because it is the
        # sentence that says what just happened and it has to stay readable
        # whichever pane is forward.
        self.summary_label = ctk.CTkLabel(
            right, text="", anchor="w", justify="left", wraplength=680
        )
        self.summary_label.pack(fill="x", pady=(8, 0))

        # One region, four possible occupants. A findings table, an assessment
        # table and the step editor are all "what you look at after an action",
        # and giving each its own permanent strip would leave three of them
        # empty at any moment.
        self.pane = ctk.CTkFrame(right, fg_color="transparent")
        self.pane.pack(fill="both", expand=True, pady=(10, 0))

        self.results = ctk.CTkTextbox(self.pane, wrap="word", font=ctk.CTkFont(size=13))
        self.findings_table = Table(
            self.pane,
            columns=["Rule", "Where", "Field", "What is wrong / what to do"],
            weights=[0, 0, 0, 1],
        )
        self.assessment_table = Table(
            self.pane,
            columns=["Step", "Executor", "Supervision", "Readiness", "Floor", "Why"],
            weights=[0, 0, 0, 0, 0, 1],
        )
        self.editor = StepEditor(self.pane, on_saved=lambda _r: self.refresh_stages())
        self.editor.bind_source(self._draft, self._db)
        self._panes = {
            "results": self.results,
            "findings": self.findings_table,
            "assessments": self.assessment_table,
            "editor": self.editor,
        }
        self.shown_pane = ""
        self._show_pane("results")

        # §16.13 and §16.14: the maturity the ledger records, and the rule and
        # schema versions the decisions were made under. Always on screen —
        # "which rules produced this?" is not a question worth a menu.
        self.version_bar = ctk.CTkLabel(
            right, text="", anchor="w", text_color=MUTED, font=ctk.CTkFont(size=11)
        )
        self.version_bar.pack(fill="x", pady=(6, 0))
        self._set_versions(services.LifecycleResult(ok=True, summary=""))

        self._render_actions()

    def _show_pane(self, name: str) -> None:
        """Bring one occupant of the detail region forward."""
        if name == self.shown_pane:
            return
        for key, widget in self._panes.items():
            if key == name:
                widget.pack(fill="both", expand=True)
            else:
                widget.pack_forget()
        self.shown_pane = name

    def _set_versions(self, result) -> None:
        """Render the maturity and version line."""
        maturity = getattr(result, "maturity", "") or "—"
        self.version_bar.configure(
            text=(
                f"maturity {maturity}   ·   rule set v"
                f"{getattr(result, 'rule_set_version', '?')}"
                f"   ·   schema v{getattr(result, 'schema_version', '?')}"
            )
        )

    def _labelled(self, parent, label: str, placeholder: str) -> ctk.CTkEntry:
        """A labelled single-line entry."""
        ctk.CTkLabel(parent, text=label, anchor="w").pack(fill="x", pady=(6, 0))
        entry = ctk.CTkEntry(parent, placeholder_text=placeholder)
        entry.pack(fill="x")
        return entry

    def _file_row(self, parent, label: str) -> ctk.CTkEntry:
        """A labelled entry with a Browse button."""
        ctk.CTkLabel(parent, text=label, anchor="w").pack(fill="x", pady=(6, 0))
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x")
        entry = ctk.CTkEntry(row, placeholder_text="path to a workflow draft YAML")
        entry.pack(side="left", fill="x", expand=True)

        def browse() -> None:
            chosen = filedialog.askopenfilename(filetypes=[("YAML", "*.yaml *.yml")])
            if chosen:
                entry.delete(0, "end")
                entry.insert(0, chosen)

        ctk.CTkButton(row, text="Browse", width=80, command=browse).pack(
            side="left", padx=(8, 0)
        )
        return entry

    def _stage_row(self, stage: str) -> None:
        """One selectable stage in the left column, with a reached/not marker."""
        row = ctk.CTkFrame(self.stage_column, fg_color="transparent")
        row.pack(fill="x", padx=8, pady=2)
        mark = ctk.CTkLabel(row, text="·", width=16, text_color=MUTED)
        mark.pack(side="left")
        label, _purpose = STAGE_LABELS[stage]
        button = ctk.CTkButton(
            row,
            text=label,
            anchor="w",
            fg_color="transparent",
            text_color=("gray10", "gray90"),
            hover_color=("gray80", "gray25"),
            command=lambda s=stage: self.select_stage(s),
        )
        button.pack(side="left", fill="x", expand=True)
        self.stage_buttons[stage] = button
        self.stage_marks[stage] = mark

    # ------------------------------------------------------------- rendering

    def _write(self, text: str, *, clear: bool = True) -> None:
        """Put text in the results box."""
        if clear:
            self.results.delete("1.0", "end")
        self.results.insert("end", text if text.endswith("\n") else text + "\n")

    def _show(self, result) -> None:
        """Render any service Outcome uniformly.

        A refusal is shown as a refusal, not an error: the runtime understood
        the request and declined, and the operator needs to read why.
        """
        lines = [result.summary]
        if getattr(result, "refusal", ""):
            lines.append("")
            lines.append(f"Refused: {result.refusal}")
        text = "\n".join(lines)
        self.summary_label.configure(text=text)
        self._write(text)
        self._show_pane("results")
        self._render_details(result)
        # Versions come from the lifecycle read that refresh_stages does
        # anyway, because that is the one result carrying the *recorded*
        # maturity. Setting them from `result` first would flash a "—" for
        # every result type that has no maturity to report.
        self.refresh_stages()

    #: Order the severity groups appear in. The service already sorts findings
    #: this way; this is here so a group with no findings is simply absent
    #: rather than the view inventing an order of its own.
    _SEVERITIES = ("ERROR", "WARNING", "INFO")

    def show_findings(self, findings) -> None:
        """Render findings as a table grouped by severity, then location.

        §16.4. The grouping keys come off the FindingView; the view does not
        re-derive them from the rendered text.
        """
        groups = []
        for severity in self._SEVERITIES:
            in_severity = [f for f in findings if f.severity == severity]
            if not in_severity:
                continue
            rows = [
                Row(
                    [
                        f.rule_id,
                        f.location or "(workflow)",
                        f.field_name or "—",
                        f"{f.message}\n→ {f.remediation}"
                        + ("\n(accepted as residual risk)" if f.accepted else ""),
                    ],
                    source=f,
                    tone="alert" if f.blocking and not f.accepted else "",
                )
                for f in in_severity
            ]
            blocking = sum(1 for f in in_severity if f.blocking and not f.accepted)
            title = severity + (f" — {blocking} blocking promotion" if blocking else "")
            groups.append(Group(title, rows))
        self.findings_table.show(groups)
        self._show_pane("findings")

    def show_assessments(self, assessments) -> None:
        """Render cooperation assessments as a table. §16.8.

        Grouped by whether a safety floor applies, because that is the division
        that governs what may be overridden — and an operator scanning for
        "what can I still change?" is scanning for exactly that line.
        """
        floored = [a for a in assessments if a.floored]
        free = [a for a in assessments if not a.floored]

        def rows(items):
            return [
                Row(
                    [
                        a.step_id,
                        a.effective_executor + ("  (overridden)" if a.overridden else ""),
                        a.supervision_mode,
                        a.automation_readiness,
                        a.safety_floor,
                        a.rationale,
                    ],
                    source=a,
                    tone="alert" if a.floored else "",
                )
                for a in items
            ]

        groups = []
        if free:
            groups.append(Group("No safety floor — may be overridden freely", rows(free)))
        if floored:
            groups.append(
                Group(
                    "Safety floor applies — may only move toward human control",
                    rows(floored),
                )
            )
        self.assessment_table.show(groups)
        self._show_pane("assessments")

    def _render_details(self, result) -> None:
        """Append whatever detail the specific result type carries."""
        findings = getattr(result, "findings", None) or getattr(result, "blocking", None)
        if findings:
            self.show_findings(findings)
        assessments = getattr(result, "assessments", None)
        if assessments:
            self.show_assessments(assessments)
        for view in getattr(result, "assignments", []) or []:
            self._write(
                f"  {view.step_id:22} {view.executor_class:32} "
                f"owner={view.human_owner}",
                clear=False,
            )
        for agent in getattr(result, "agents", []) or []:
            self._write(
                f"  agent {agent.agent_name} (level {agent.depth_level}) "
                f"escalates to {agent.escalation_target}",
                clear=False,
            )
        for listing in getattr(result, "workflows", []) or []:
            self._write(
                f"  {listing.workflow_id:28} v{listing.version}  {listing.maturity}",
                clear=False,
            )
        kept = getattr(result, "steps_kept_human", None)
        if kept is not None:
            self._write("", clear=False)
            # Always stated, including when it is zero. An operator who reads
            # only "2 packages built" has learned nothing about the six steps
            # still on their desk.
            self._write(
                f"  {len(kept)} step(s) stay with a person"
                + (f": {', '.join(kept)}" if kept else ""),
                clear=False,
            )

    def refresh_stages(self) -> services.LifecycleResult:
        """Re-read the lifecycle and update the stage markers."""
        result = self.run_status()
        reached = {s.stage: s.present for s in result.stages}
        for stage, mark in self.stage_marks.items():
            present = reached.get(stage, False)
            mark.configure(
                text="●" if present else "·",
                text_color=PRIMARY if present else MUTED,
            )
        self._set_versions(result)
        return result

    def select_stage(self, stage: str) -> None:
        """Switch the detail pane to a stage.

        Re-selecting the current stage does nothing. Rebuilding the action row
        destroys and recreates every button, and doing that for a no-op leaves
        events queued against widgets that no longer exist.
        """
        if stage == self.selected_stage and self.actions.winfo_children():
            return
        self.selected_stage = stage
        self._render_actions()

    def _render_actions(self) -> None:
        """Rebuild the action pane for the selected stage."""
        for child in self.actions.winfo_children():
            child.destroy()
        label, purpose = STAGE_LABELS[self.selected_stage]
        ctk.CTkLabel(
            self.actions,
            text=label,
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=PRIMARY,
            anchor="w",
        ).pack(fill="x")
        ctk.CTkLabel(self.actions, text=purpose, text_color=MUTED, anchor="w").pack(
            fill="x", pady=(0, 8)
        )
        row = ctk.CTkFrame(self.actions, fg_color="transparent")
        row.pack(fill="x")
        for text, handler in self._actions_for(self.selected_stage):
            ctk.CTkButton(row, text=text, command=handler, width=150).pack(
                side="left", padx=(0, 8), pady=2
            )

    def _actions_for(self, stage: str) -> list[tuple[str, object]]:
        """Which buttons belong to a stage."""
        return {
            "draft": [
                ("New draft", self.on_create),
                ("Edit steps", self.on_edit_steps),
                ("Save to ledger", self.on_import),
                ("Reload", self.on_reload),
                ("List all", self.on_list),
            ],
            "accountable": [
                ("Validate", self.on_validate),
                ("Accept risk…", self.on_accept_risk),
                ("Promote", self.on_promote),
            ],
            "assessed": [
                ("Assess cooperation", self.on_assess),
                ("Override executor…", self.on_override),
            ],
            "cooperative": [
                ("Build assignments", self.on_build),
                ("Build + approve", self.on_build_approved),
            ],
            "exported": [("Export brief", self.on_export)],
            "runs": [("Refresh", self.on_status)],
        }[stage]

    # ------------------------------------------------------------- threading

    def _in_worker(self, work, done) -> None:
        """Run ``work`` off the UI thread, so the window never freezes.

        The result travels back through a queue and is delivered by ``_poll``
        on the UI thread. **The worker never touches Tk** — not even
        ``after()``. Tkinter is not thread-safe, and calling ``after()`` from a
        worker silently does nothing here: no exception, no callback, the
        result simply lost. A queue plus a main-thread poller keeps every Tk
        call on the thread that owns the widgets, which is what ADR-007 §3 is
        actually asking for.

        The broad ``except`` is deliberate and swallows nothing: an exception
        raised on a worker thread otherwise dies with the thread, leaving a
        window that looks like it did nothing. Surfacing it as a refused
        Outcome is the only way the operator learns it happened.
        """
        if self._busy:
            self._write("Still working — wait for the current action to finish.")
            return
        self._busy = True

        def runner() -> None:
            try:
                result = work()
            except Exception as exc:  # noqa: BLE001 — see docstring
                result = services.Outcome(
                    ok=False, summary="Unexpected error", refusal=repr(exc)
                )
            self._results.put((result, done))

        self._worker = threading.Thread(target=runner, daemon=True)
        self._worker.start()

    def _schedule_poll(self) -> None:
        """Arm the next queue check. Called only from the UI thread."""
        self._poll_id = self.after(_POLL_MS, self._poll)

    def _poll(self) -> None:
        """Deliver finished work, then re-arm.

        Stops rather than re-arming once the widget is gone. A pending
        ``after`` outliving its widget is how a GUI turns a torn-down window
        into a crash instead of a no-op.
        """
        if not self._alive():
            self._poll_id = None
            return
        self.drain()
        self._schedule_poll()

    def _alive(self) -> bool:
        """Whether this widget still exists."""
        try:
            return bool(self.winfo_exists())
        except Exception:  # noqa: BLE001 — a dead interpreter is not alive
            return False

    def drain(self) -> None:
        """Deliver every finished worker result. UI thread only.

        Public because a test driving the window headlessly needs to flush
        pending work without waiting on the poller's interval.
        """
        while True:
            try:
                result, done = self._results.get_nowait()
            except queue.Empty:
                return
            self._busy = False
            done(result)

    def destroy(self) -> None:
        """Cancel the poller and let any worker finish before widgets go away.

        Two separate hazards. A pending ``after`` outliving its widget produces
        Tk's "invalid command name" noise at best. And a daemon worker still
        inside SQLite when the interpreter begins shutting down can take the
        process down with it — so this waits briefly for it rather than
        assuming daemon means harmless.
        """
        if self._poll_id is not None:
            try:
                self.after_cancel(self._poll_id)
            except Exception:  # noqa: BLE001 — teardown must not raise
                pass
            self._poll_id = None
        worker, self._worker = self._worker, None
        if worker is not None and worker.is_alive():
            worker.join(timeout=5.0)
        super().destroy()

    # ------------------------------------------------ synchronous operations
    #
    # Each returns a service result and touches no widget, so a test can call
    # it directly with no display and no thread.

    def _db(self) -> str:
        """The ledger path the operator typed, or the default."""
        return self.db_entry.get().strip() or "fukasawa.db"

    def _workflow_id(self) -> str:
        """The workflow id the operator typed."""
        return self.workflow_entry.get().strip()

    def _draft(self) -> str:
        """The draft path the operator typed."""
        return self.draft_entry.get().strip()

    def run_create(self) -> services.Outcome:
        """Write a draft skeleton at the draft path."""
        if not self._draft():
            return services.Outcome(
                ok=False, summary="No draft path", refusal="Choose where to write the draft."
            )
        return services.create_draft(self._workflow_id(), self._draft())

    def run_import(self) -> services.Outcome:
        """Save the draft file into the ledger."""
        return services.import_draft(self._draft(), self._db())

    def run_reload(self) -> services.Outcome:
        """Read the stored draft back."""
        return services.reload_draft(self._workflow_id(), self._db())

    def run_list(self) -> services.ListResult:
        """List every stored workflow."""
        return services.list_workflows(self._db())

    def run_validate(self) -> services.ValidationResult:
        """Validate the draft and store the report."""
        return services.validate_draft(self._draft(), self._db(), save=True)

    def run_promote(self) -> services.PromotionResult:
        """Advance the draft one maturity step."""
        return services.promote_draft(self._draft(), self._actor(), self._db())

    def run_assess(self) -> services.AssessmentResult:
        """Assess cooperation for every step."""
        return services.assess_cooperation(self._workflow_id(), self._db())

    def run_build(self, approved: bool = False) -> services.CooperativeResult:
        """Build the assignments, optionally approving them."""
        return services.build_cooperative(
            self._workflow_id(), self._actor() if approved else "", self._db()
        )

    def run_export(self) -> services.ExportResult:
        """Export the approved workflow to a brief."""
        return services.export_brief(self._workflow_id(), db=self._db())

    def run_status(self) -> services.LifecycleResult:
        """Read the lifecycle stages."""
        return services.lifecycle_status(self._workflow_id(), self._db())

    def run_accept(self, finding_id: str, actor: str, rationale: str) -> services.Outcome:
        """Record a conscious acceptance of one advisory finding."""
        return services.accept_finding(
            self._draft(), finding_id, actor, rationale, self._db()
        )

    def run_override(
        self, step_id: str, executor_class: str, actor: str, rationale: str
    ) -> services.AssessmentResult:
        """Replace one step's recommended executor with a human's judgment."""
        return services.override_executor(
            self._workflow_id(), step_id, executor_class, actor, rationale, self._db()
        )

    def _actor(self) -> str:
        """Who is acting. Self-attested — this runtime has no authentication."""
        return "desktop-operator"

    # --------------------------------------------------------- UI handlers
    #
    # Thin: start a worker, render whatever comes back.

    def on_create(self) -> None:
        """Write a new draft skeleton."""
        self._in_worker(self.run_create, self._show)

    def on_import(self) -> None:
        """Save the draft to the ledger."""
        self._in_worker(self.run_import, self._show)

    def on_reload(self) -> None:
        """Reload the stored draft."""
        self._in_worker(self.run_reload, self._show)

    def on_list(self) -> None:
        """List stored workflows."""
        self._in_worker(self.run_list, self._show)

    def on_validate(self) -> None:
        """Validate the draft."""
        self._in_worker(self.run_validate, self._show)

    def on_promote(self) -> None:
        """Promote the draft one step."""
        self._in_worker(self.run_promote, self._show)

    def on_assess(self) -> None:
        """Assess cooperation."""
        self._in_worker(self.run_assess, self._show)

    def on_build(self) -> None:
        """Build assignments without approving them."""
        self._in_worker(lambda: self.run_build(False), self._show)

    def on_build_approved(self) -> None:
        """Build assignments and approve them."""
        self._in_worker(lambda: self.run_build(True), self._show)

    def on_export(self) -> None:
        """Export the brief."""
        self._in_worker(self.run_export, self._show)

    def on_status(self) -> None:
        """Refresh the lifecycle view."""
        self._in_worker(self.run_status, self._show)

    def on_edit_steps(self) -> None:
        """Open the guided step editor on the current draft. §16.3.

        Runs on the UI thread rather than in a worker: reading one step of one
        YAML file is not long work, and the editor's first act is to build
        widgets, which only the UI thread may do.
        """
        self._show_pane("editor")
        result = self.editor.open_step("")
        self.summary_label.configure(
            text=result.summary + (f"\nRefused: {result.refusal}" if result.refusal else "")
        )

    # ------------------------------------------------- the two reason dialogs
    #
    # Both open a modal, wait for it, then run the service in a worker. The
    # dialog is UI-thread work by necessity; the service call that follows is
    # not, and the split keeps the window responsive while the ledger is
    # written.

    def on_accept_risk(self) -> None:
        """Accept the selected advisory finding, with a reason. §16.6."""
        finding = self.findings_table.selected_source()
        if finding is None:
            self._write(
                "Validate first, then click the finding you want to accept.\n"
                "Only advisory findings may be accepted — a blocking finding is "
                "fixed or the workflow does not advance."
            )
            self._show_pane("results")
            return
        if finding.blocking:
            self._write(
                f"{finding.rule_id} is blocking. Blocking findings cannot be "
                f"accepted; they are fixed. {finding.remediation}"
            )
            self._show_pane("results")
            return

        values = ReasonDialog(
            self,
            title="Accept a residual risk",
            subject=f"{finding.rule_id} — {finding.where}",
            detail=finding.message,
            actor=self._actor(),
            confirm_text="Accept risk",
            warning=(
                "Accepting records your reason. It does not change whether this "
                "workflow may be promoted — advisory findings never blocked it."
            ),
        ).wait()
        if values is None:
            return
        self._in_worker(
            lambda: self.run_accept(
                finding.finding_id, values["actor"], values["rationale"]
            ),
            self._after_accept,
        )

    def _after_accept(self, result) -> None:
        """Show the acceptance, then re-validate so the table reflects it."""
        self._show(result)
        if result.ok:
            self._show(self.run_validate())

    def on_override(self) -> None:
        """Override the selected step's executor, with a reason. §16.9."""
        assessment = self.assessment_table.selected_source()
        if assessment is None:
            self._write("Assess cooperation first, then click the step to override.")
            self._show_pane("results")
            return

        warning = ""
        if assessment.floored:
            warning = (
                f"A {assessment.safety_floor} safety floor applies to this step. "
                f"You may move it toward human control; a move toward greater "
                f"autonomy will be refused, and the refusal will say so."
            )
        values = ReasonDialog(
            self,
            title="Override the recommended executor",
            subject=f"{assessment.step_id} — currently {assessment.effective_executor}",
            detail=assessment.rationale,
            actor=self._actor(),
            choices=list(services.EXECUTOR_CLASSES),
            choice_label="Executor class",
            confirm_text="Override",
            warning=warning,
        ).wait()
        if values is None:
            return
        self._in_worker(
            lambda: self.run_override(
                assessment.step_id,
                values["choice"],
                values["actor"],
                values["rationale"],
            ),
            self._show,
        )

    # ------------------------------------------------------------ test hooks

    def set_fields(self, **values: str) -> None:
        """Populate entry boxes by attribute name, for headless tests."""
        for name, value in values.items():
            entry = getattr(self, name)
            entry.delete(0, "end")
            entry.insert(0, value)

    def shown(self) -> str:
        """Whatever is currently in the results box."""
        return self.results.get("1.0", "end")
