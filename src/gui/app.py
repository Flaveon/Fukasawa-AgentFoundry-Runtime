# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Fukasawa desktop app — the non-technical front door.

Two tasks, two tabs: **Validate a Brief** and **Build a Workflow**. Both are
thin views over src/gui/services.py — every decision, gate, and message lives
there, so this file only wires widgets to functions and renders their
results. The runtime remains fully usable without ever opening this window.

The window constructs without entering the event loop, and the button
handlers are plain methods that read the entry fields — so the app can be
driven headlessly in a test (set the fields, call the handler, read the
output) without a human at a mouse.
"""

from tkinter import filedialog

import customtkinter as ctk

from src.gui.services import BriefValidation, BuildOutcome, build_workflow, validate_brief_file
from src.gui.workflow_views import WorkflowTab

#: Brand palette (BRAND.md): primary purple, secondary pink.
PRIMARY = "#A855F7"
PRIMARY_HOVER = "#9333EA"
SECONDARY = "#FF6EC7"
OK_GREEN = "#22C55E"
FAIL_RED = "#EF4444"


class FukasawaApp(ctk.CTk):
    """The main application window."""

    def __init__(self) -> None:
        """Build the window and both task tabs. Does not start the event loop."""
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title("Fukasawa AgentFoundry Runtime")
        self.geometry("820x640")
        self.minsize(720, 560)

        header = ctk.CTkLabel(
            self,
            text="Fukasawa AgentFoundry",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=PRIMARY,
        )
        header.pack(pady=(16, 0))
        ctk.CTkLabel(
            self,
            text="Capture a workflow, decide who does each step, then build it.",
            text_color=SECONDARY,
        ).pack(pady=(0, 10))

        self.tabs = ctk.CTkTabview(self, fg_color=("gray92", "gray14"))
        self.tabs.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self.tabs.add("Workflow")
        self.tabs.add("Validate Brief")
        self.tabs.add("Build Workflow")
        # The lifecycle tab comes first: a brief is what the lifecycle
        # produces, so validating and building one are the later steps.
        self.workflow_tab = WorkflowTab(self.tabs.tab("Workflow"))
        self._build_validate_tab(self.tabs.tab("Validate Brief"))
        self._build_build_tab(self.tabs.tab("Build Workflow"))

    # -------------------------------------------------------------- widgets

    def _file_row(self, parent, label: str, is_dir: bool = False):
        """A labeled entry + Browse button; returns the entry widget."""
        ctk.CTkLabel(parent, text=label, anchor="w").pack(fill="x", padx=12, pady=(10, 0))
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=12)
        entry = ctk.CTkEntry(row, placeholder_text=label)
        entry.pack(side="left", fill="x", expand=True)

        def browse() -> None:
            chosen = (
                filedialog.askdirectory()
                if is_dir
                else filedialog.askopenfilename(
                    filetypes=[("YAML", "*.yaml *.yml"), ("All", "*.*")]
                )
            )
            if chosen:
                entry.delete(0, "end")
                entry.insert(0, chosen)

        ctk.CTkButton(
            row, text="Browse", width=90, command=browse,
            fg_color=PRIMARY, hover_color=PRIMARY_HOVER,
        ).pack(side="left", padx=(8, 0))
        return entry

    def _results_box(self, parent) -> ctk.CTkTextbox:
        """A read-only, scrollable results area."""
        box = ctk.CTkTextbox(parent, wrap="word", font=ctk.CTkFont(size=13))
        box.pack(fill="both", expand=True, padx=12, pady=12)
        box.configure(state="disabled")
        return box

    def _write(self, box: ctk.CTkTextbox, text: str, color: str | None = None) -> None:
        """Replace a results box's content."""
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("1.0", text)
        if color:
            box.configure(text_color=color)
        box.configure(state="disabled")

    # ------------------------------------------------------- validate tab

    def _build_validate_tab(self, tab) -> None:
        """Compose the Validate Brief tab."""
        self.validate_entry = self._file_row(tab, "Workflow brief (.yaml)")
        ctk.CTkButton(
            tab, text="Validate Brief", command=self.on_validate,
            fg_color=PRIMARY, hover_color=PRIMARY_HOVER, height=40,
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(pady=12)
        self.validate_results = self._results_box(tab)

    def on_validate(self) -> BriefValidation:
        """Validate the entered brief and render the result. Returns it too."""
        result = validate_brief_file(self.validate_entry.get().strip())
        if result.ok:
            lines = [
                f"✓ {result.summary}",
                "",
                f"id:           {result.brief_id}",
                f"owner:        {result.owner}",
                f"status:       {result.status}"
                + ("  (approved — buildable)" if result.approved else "  (not approved)"),
                f"states:       {result.state_count}",
                f"transitions:  {result.transition_count}",
                f"agents:       {result.agent_count}",
                f"review gates: {result.review_gates}",
            ]
            self._write(self.validate_results, "\n".join(lines), OK_GREEN)
        else:
            body = "\n".join(f"  • {p}" for p in result.problems)
            self._write(
                self.validate_results,
                f"✗ {result.summary}\n\n{body}".rstrip(),
                FAIL_RED,
            )
        return result

    # ---------------------------------------------------------- build tab

    def _build_build_tab(self, tab) -> None:
        """Compose the Build Workflow tab."""
        self.build_brief_entry = self._file_row(tab, "Approved brief (.yaml)")
        self.build_out_entry = self._file_row(tab, "Output folder", is_dir=True)
        self.build_ws_entry = self._file_row(
            tab, "Workspace root (optional, enables C-Pax paths)", is_dir=True
        )
        ctk.CTkButton(
            tab, text="Build Workflow", command=self.on_build,
            fg_color=SECONDARY, hover_color=PRIMARY, height=40,
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(pady=12)
        self.build_results = self._results_box(tab)

    def on_build(self) -> BuildOutcome:
        """Build the workflow's packages and render the checklist. Returns it too."""
        brief = self.build_brief_entry.get().strip()
        out = self.build_out_entry.get().strip()
        workspace = self.build_ws_entry.get().strip() or None
        if not brief or not out:
            outcome = BuildOutcome(
                ok=False, summary="Choose a brief and an output folder first.",
                refusal="Both a brief file and an output folder are required.",
            )
        else:
            outcome = build_workflow(brief, out, workspace_root=workspace)

        if outcome.refusal:
            self._write(
                self.build_results,
                f"✗ {outcome.summary}\n\n{outcome.refusal}",
                FAIL_RED,
            )
            return outcome
        lines = [f"{'✓' if outcome.ok else '✗'} {outcome.summary}", ""]
        for pkg in outcome.packages:
            mark = "✓" if pkg.ok else "✗"
            lines.append(f"{mark} {pkg.name}")
            lines.append(f"    {pkg.path}")
            for finding in pkg.findings:
                lines.append(f"    • {finding}")
        if outcome.report_path:
            lines += ["", f"Build report: {outcome.report_path}"]
        self._write(
            self.build_results, "\n".join(lines), OK_GREEN if outcome.ok else FAIL_RED
        )
        return outcome

    # -------------------------------------------------------------- helpers

    def set_fields(self, **values: str) -> None:
        """Set entry fields by attribute name (for scripting and tests)."""
        for name, value in values.items():
            entry = getattr(self, name)
            entry.delete(0, "end")
            entry.insert(0, value)


def main() -> None:
    """Console entry point: launch the desktop app."""
    app = FukasawaApp()
    app.mainloop()


if __name__ == "__main__":
    main()
