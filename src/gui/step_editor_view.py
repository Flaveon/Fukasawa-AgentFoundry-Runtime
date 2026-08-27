# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""The guided step editor — §16.3.

What makes it *guided* rather than a form is that the advice beside each box is
the remediation sentence of the rule that fires on that box, read live from the
registry through `services.step_field_guidance()`. Nothing here knows what
HW-003 is; it renders whatever the service says the rules currently are.

Layout is one column of fields, scrollable, with:

* the findings against **this step** at the top, so the operator sees what they
  came to fix before they start typing;
* a rule id badge on every field a rule governs, so a blocking gap is visible
  before it is a finding;
* the step's characteristics as dropdowns, because those six values decide who
  is allowed to execute the step and leaving them to YAML hides the most
  consequential decision in the file.

This view decides nothing. It reads boxes and calls
`services.write_step`, which contract-checks the result, backs the file up, and
re-validates. Everything it renders came from a service.
"""

import customtkinter as ctk

from src.gui import services

PRIMARY = "#A855F7"
MUTED = ("gray45", "gray60")
BLOCKING_BG = ("#F4E4FF", "#3A1D4D")

#: Height of a ``lines``/``records`` box, in text rows. Small enough that the
#: form still scans as a form, big enough to show three entries without
#: scrolling — which is about how many most steps have.
_BOX_HEIGHT = 78


class StepEditor(ctk.CTkFrame):
    """Per-field editing of one WorkflowStep, with its rules alongside."""

    def __init__(self, parent, on_saved=None) -> None:
        """Build an empty editor. Nothing is read until ``open_step`` runs."""
        super().__init__(parent, fg_color="transparent")
        self.on_saved = on_saved
        self.guidance = services.step_field_guidance()
        self.widgets: dict[str, object] = {}
        self.step_id = ""
        self.step_ids: list[str] = []
        self.last_result: services.StepResult | None = None
        self._build()

    # ------------------------------------------------------------- structure

    def _build(self) -> None:
        """The step picker, the findings strip, and the field column."""
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x")

        ctk.CTkLabel(header, text="Step", anchor="w").pack(side="left", padx=(0, 8))
        self.step_picker = ctk.CTkOptionMenu(
            header, values=["(no draft loaded)"], command=self.open_step, width=220
        )
        self.step_picker.pack(side="left")
        self.save_button = ctk.CTkButton(
            header, text="Save step", command=self.save, width=110
        )
        self.save_button.pack(side="right")
        ctk.CTkButton(
            header,
            text="Reload",
            command=lambda: self.open_step(self.step_id),
            width=90,
            fg_color="transparent",
            border_width=1,
        ).pack(side="right", padx=(0, 8))

        self.status = ctk.CTkLabel(self, text="", anchor="w", justify="left", wraplength=680)
        self.status.pack(fill="x", pady=(6, 0))

        self.findings_box = ctk.CTkTextbox(self, height=92, wrap="word")
        self.findings_box.pack(fill="x", pady=(6, 6))

        self.fields = ctk.CTkScrollableFrame(self, label_text="")
        self.fields.pack(fill="both", expand=True)
        self._build_fields()

    def _build_fields(self) -> None:
        """One labelled control per editable field, in guidance order."""
        for spec in self.guidance:
            block = ctk.CTkFrame(
                self.fields,
                fg_color=BLOCKING_BG if spec.blocking else "transparent",
                corner_radius=6,
            )
            block.pack(fill="x", pady=3, padx=2)

            label_row = ctk.CTkFrame(block, fg_color="transparent")
            label_row.pack(fill="x", padx=8, pady=(6, 0))
            ctk.CTkLabel(
                label_row,
                text=spec.label,
                anchor="w",
                font=ctk.CTkFont(size=13, weight="bold"),
            ).pack(side="left")
            if spec.rule_id:
                ctk.CTkLabel(
                    label_row,
                    text=f"  {spec.rule_id}"
                    + ("  blocking" if spec.blocking else "  advisory"),
                    anchor="w",
                    text_color=PRIMARY,
                    font=ctk.CTkFont(size=11),
                ).pack(side="left")

            hint = spec.hint
            if spec.kind == "records":
                hint += f"  Columns: {' | '.join(spec.columns)}"
            ctk.CTkLabel(
                block,
                text=hint,
                anchor="w",
                justify="left",
                wraplength=640,
                text_color=MUTED,
                font=ctk.CTkFont(size=11),
            ).pack(fill="x", padx=8)

            self.widgets[spec.name] = self._control(block, spec)

    def _control(self, parent, spec):
        """The right widget for a field kind."""
        if spec.kind == "choice":
            widget = ctk.CTkOptionMenu(parent, values=spec.choices)
            widget.pack(fill="x", padx=8, pady=(2, 8))
            return widget
        if spec.kind in ("lines", "records"):
            widget = ctk.CTkTextbox(parent, height=_BOX_HEIGHT, wrap="none")
            widget.pack(fill="x", padx=8, pady=(2, 8))
            return widget
        widget = ctk.CTkEntry(parent)
        widget.pack(fill="x", padx=8, pady=(2, 8))
        return widget

    # --------------------------------------------------------------- values

    def _set(self, name: str, value: str) -> None:
        """Put a value into whichever widget holds this field."""
        widget = self.widgets[name]
        if isinstance(widget, ctk.CTkOptionMenu):
            widget.set(value)
        elif isinstance(widget, ctk.CTkTextbox):
            widget.delete("1.0", "end")
            widget.insert("1.0", value)
        else:
            widget.delete(0, "end")
            widget.insert(0, value)

    def _get(self, name: str) -> str:
        """Read a field's current text."""
        widget = self.widgets[name]
        if isinstance(widget, ctk.CTkOptionMenu):
            return widget.get()
        if isinstance(widget, ctk.CTkTextbox):
            return widget.get("1.0", "end").rstrip("\n")
        return widget.get()

    def values(self) -> dict[str, str]:
        """Every field's current text, keyed by contract field name."""
        return {spec.name: self._get(spec.name) for spec in self.guidance}

    # ------------------------------------------------- synchronous operations
    #
    # As in `workflow_views`: the synchronous half is public so the whole
    # editor can be driven by a test with no display and no thread.

    def run_open(self, path: str, step_id: str, db: str) -> services.StepResult:
        """Read a step from the draft file."""
        return services.read_step(path, step_id, db)

    def run_save(self, path: str, step_id: str, db: str) -> services.StepResult:
        """Write this editor's values back to the draft file."""
        return services.write_step(path, step_id, self.values(), db)

    # --------------------------------------------------------------- context
    #
    # The editor does not own the draft path or the ledger path — the tab does.
    # They arrive through `bind_source` rather than being read from entry boxes
    # here, so there is exactly one place an operator types them.

    def bind_source(self, path_getter, db_getter) -> None:
        """Tell the editor where to read the draft and the ledger from."""
        self._path = path_getter
        self._db = db_getter

    def _paths(self) -> tuple[str, str]:
        """The current draft path and ledger path."""
        return self._path(), self._db()

    # -------------------------------------------------------------- handlers

    def open_step(self, step_id: str = "") -> services.StepResult:
        """Load a step into the form and render its findings."""
        path, db = self._paths()
        if not path:
            return self._render(
                services.StepResult(
                    ok=False,
                    summary="No draft file",
                    refusal="Choose a draft file above, then pick a step.",
                )
            )
        chosen = "" if step_id.startswith("(") else step_id
        return self._render(self.run_open(path, chosen, db))

    def save(self) -> services.StepResult:
        """Write the form back to the draft, then re-render what came back."""
        path, db = self._paths()
        if not self.step_id:
            return self._render(
                services.StepResult(
                    ok=False, summary="No step open", refusal="Pick a step first."
                )
            )
        result = self._render(self.run_save(path, self.step_id, db))
        if result.ok and self.on_saved is not None:
            self.on_saved(result)
        return result

    # -------------------------------------------------------------- rendering

    def _render(self, result: services.StepResult) -> services.StepResult:
        """Show a StepResult: status, step list, findings, and field values."""
        self.last_result = result
        self.status.configure(
            text=result.summary + (f"\nRefused: {result.refusal}" if result.refusal else "")
        )
        if result.step_ids:
            self.step_ids = list(result.step_ids)
            self.step_picker.configure(values=self.step_ids)
        if result.step is None:
            return result

        self.step_id = result.step.step_id
        self.step_picker.set(self.step_id)
        for name, value in result.step.values.items():
            if name in self.widgets:
                self._set(name, value)

        self.findings_box.delete("1.0", "end")
        if not result.step.findings:
            self.findings_box.insert("end", "No findings against this step.\n")
        for finding in result.step.findings:
            policy = (
                "accepted"
                if finding.accepted
                else ("blocking" if finding.blocking else "advisory")
            )
            self.findings_box.insert(
                "end",
                f"{finding.rule_id} [{finding.severity}/{policy}] "
                f"{finding.field_name or '—'}: {finding.message}\n"
                f"    → {finding.remediation}\n",
            )
        return result

    # ------------------------------------------------------------ test hooks

    def shown_findings(self) -> str:
        """Whatever is currently in the findings strip."""
        return self.findings_box.get("1.0", "end")

    def field_labels(self) -> list[str]:
        """Every field this editor exposes, in order."""
        return [spec.name for spec in self.guidance]
