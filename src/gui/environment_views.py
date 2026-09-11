# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""The Environment tab — which computers can run agent steps, and how we know.

**This module decides nothing.** Every question it asks is answered by
``src.gui.services``: what the four permission choices are and what they say,
how a typed address is read, whether an address is taken, what a look found,
whether a computer counts. The code here reads widgets, calls a service, and
renders what comes back (ADR-007 §1). The import-law test in
``tests/test_gui_workflow.py`` fails if this file reaches past the services.

The screens are design §3.2 (nothing recorded), §3.3 (where to look), §3.4
(findings arriving one at a time), §3.5 (a card per computer), §3.6 (what this
means when steps run) and §3.8 (typing a computer in). Every string on them is
held to §3.1.1 and §3.1.2: figures with units, no verdict on anybody's
hardware, and no assumption about who owns the work.

**Threading** is the Workflow tab's: a worker thread, a queue, and a poller on
the UI thread, so no Tk call ever happens off it. It differs in one way. A look
is a stream, so the worker puts **each finding** on the queue as it is made,
rather than one result at the end — §3.4 asks for findings to appear as they
are learned, and a person watching a scan deserves to see it happening.

**One writer at a time.** A look writes the store from the worker thread, and
editing rewrites the whole file from this one, with no lock between them
(``src/gui/services/nodes.py``). So while a look runs, every handler that
writes refuses, and the buttons that reach them are disabled. The refusal in
the handler is the guard; the disabled button is the courtesy.

**Nothing is read while the tab is built.** The window builds every tab at
start-up, and the store is somebody's own file; the app calls ``refresh()``
when this tab is opened.
"""

import queue
import threading

import customtkinter as ctk

from src.gui import services

#: Brand palette, matching `workflow_views` and `tables`.
PRIMARY = "#A855F7"
MUTED = ("gray45", "gray60")
CARD_BG = ("gray90", "gray17")

#: How often the UI thread checks for findings, in milliseconds.
_POLL_MS = 40

#: Who a permission is recorded against. Self-attested, as on the Workflow
#: tab: this runtime has no sign-in, so the desktop names itself.
ACTOR = "desktop-operator"

#: Said when something is asked for while a look is still writing.
BUSY = "Still looking. Wait for it to finish before changing anything."


class EnvironmentTab(ctk.CTkFrame):
    """Record which computers can run AI, found by looking or typed in."""

    def __init__(self, parent) -> None:
        """Build the tab. Reads nothing until ``refresh()`` or an action runs."""
        super().__init__(parent, fg_color="transparent")
        self.pack(fill="both", expand=True)

        #: Where computers are kept, and the two network verbs a look uses.
        #: ``None`` is the configured file and the real network. The view
        #: passes all three through to the services and builds none of them;
        #: tests set them so that no test reads a real home directory or
        #: opens a real socket.
        self.store = None
        self.fetch = None
        self.post = None

        self._results: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._poll_id = None
        self._busy = False
        self._last: services.NodeListResult | None = None
        self._busy_widgets: list = []
        self._edit_entries: dict[str, ctk.CTkEntry] = {}
        #: The computer whose card is open for editing, and the one whose
        #: Forget button has been pressed once. Empty when none.
        self._editing = ""
        self._forget_armed = ""
        self._added: services.AddResult | None = None
        self.shown_pane = ""

        self._build()
        self._schedule_poll()

    # ------------------------------------------------------------------ layout

    def _build(self) -> None:
        """Lay out the introduction and the three panes."""
        self._intro = ctk.CTkLabel(
            self,
            text="Fukasawa can run some workflow steps automatically, using AI\n"
                 "on a computer you point it at. Nothing here talks to the cloud.",
            justify="left", anchor="w",
        )
        self._intro.pack(fill="x", padx=12, pady=(12, 6))

        self._panes = {
            "home": ctk.CTkFrame(self, fg_color="transparent"),
            "permission": ctk.CTkFrame(self, fg_color="transparent"),
            "typed": ctk.CTkFrame(self, fg_color="transparent"),
        }
        self._notes: dict[str, ctk.CTkLabel] = {}
        self._build_home(self._panes["home"])
        self._build_permission(self._panes["permission"])
        self._build_typed(self._panes["typed"])
        self._show_pane("home")

    def _note(self, pane: str, parent) -> None:
        """A line on a pane for answers to what was just pressed."""
        label = ctk.CTkLabel(parent, text="", anchor="w", justify="left",
                             text_color=PRIMARY, wraplength=640)
        label.pack(fill="x", padx=12, pady=(2, 2))
        self._notes[pane] = label

    def _build_home(self, pane) -> None:
        """The findings log, the cards, the panel, and the actions."""
        self._note("home", pane)
        #: One line per finding while a look runs (§3.4). Hidden until then.
        self.log = ctk.CTkTextbox(pane, wrap="word", height=150)
        self._log_actions = ctk.CTkFrame(pane, fg_color="transparent")
        ctk.CTkButton(
            self._log_actions, text="Looks right", command=self.on_looks_right,
            fg_color="transparent", border_width=1, width=110,
        ).pack(side="left")
        self._scroll = ctk.CTkScrollableFrame(pane, fg_color="transparent")
        self._scroll.pack(fill="both", expand=True, padx=6, pady=(4, 8))
        #: Rebuilt on every render. A plain frame inside the scrollable one,
        #: because destroying a CTkScrollableFrame's own children takes its
        #: canvas with them (see `tables.py`).
        self.content = ctk.CTkFrame(self._scroll, fg_color="transparent")
        self.content.pack(fill="both", expand=True)

    def _build_permission(self, pane) -> None:
        """Design §3.3: where to look, asked before anything is opened."""
        self._note("permission", pane)
        ctk.CTkLabel(
            pane, text="Where should I look?",
            font=ctk.CTkFont(size=15, weight="bold"), anchor="w",
        ).pack(fill="x", padx=12, pady=(4, 8))
        self.scope_var = ctk.StringVar(value=services.ScanScope.THIS_MACHINE.value)
        for scope, title, detail in services.SCAN_CHOICES:
            ctk.CTkRadioButton(
                pane, text=title, value=scope.value, variable=self.scope_var,
            ).pack(fill="x", padx=16, pady=(6, 0))
            ctk.CTkLabel(
                pane, text=detail, anchor="w", justify="left",
                text_color=MUTED, wraplength=560,
            ).pack(fill="x", padx=46)
            if scope is services.ScanScope.NAMED_HOST:
                # Directly under the choice it belongs to. Placed after all
                # four, nothing on screen said which one it was for.
                self.address_entry = ctk.CTkEntry(
                    pane, placeholder_text="Its address, e.g. 192.168.1.20",
                    width=320,
                )
                self.address_entry.pack(anchor="w", padx=46, pady=(4, 2))
        ctk.CTkLabel(pane, text="You can change this later.", anchor="w",
                     text_color=MUTED).pack(fill="x", padx=12, pady=(8, 4))
        row = ctk.CTkFrame(pane, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=6)
        ctk.CTkButton(row, text="Cancel", command=self.on_cancel,
                      fg_color="transparent", border_width=1).pack(side="left")
        ctk.CTkButton(row, text="Look", command=self.on_permission_look,
                      fg_color=PRIMARY).pack(side="left", padx=8)

    def _build_typed(self, pane) -> None:
        """Design §3.8: name, address, program; save; then ask before contact."""
        self._note("typed", pane)
        self.typed_first = ctk.CTkLabel(pane, text="", anchor="w", justify="left")
        self.typed_first.pack(fill="x", padx=12)
        self.typed_second = ctk.CTkLabel(pane, text="", anchor="w", justify="left")
        self.typed_second.pack(fill="x", padx=12, pady=(0, 8))

        self.name_entry = self._field(pane, "What should I call it?")
        self.typed_address_entry = self._field(pane, "Address of the computer")
        ctk.CTkLabel(pane, text="Which is running on it?", anchor="w").pack(
            fill="x", padx=12, pady=(8, 0))
        self.kind_var = ctk.StringVar(value=services.KIND_CHOICES[0][0])
        kinds = ctk.CTkFrame(pane, fg_color="transparent")
        kinds.pack(fill="x", padx=16)
        for value, words in services.KIND_CHOICES:
            ctk.CTkRadioButton(kinds, text=words, value=value,
                               variable=self.kind_var).pack(side="left", padx=(0, 16))

        self._typed_buttons = ctk.CTkFrame(pane, fg_color="transparent")
        self._typed_buttons.pack(fill="x", padx=12, pady=10)
        ctk.CTkButton(self._typed_buttons, text="Cancel", command=self.on_cancel,
                      fg_color="transparent", border_width=1).pack(side="left")
        self.save_button = ctk.CTkButton(
            self._typed_buttons, text="Save", command=self.on_save_typed,
            fg_color=PRIMARY,
        )
        self.save_button.pack(side="left", padx=8)

        #: Shown after a save: what was saved, and the separate question.
        self._after_save = ctk.CTkFrame(pane, fg_color="transparent")
        self.saved_label = ctk.CTkLabel(self._after_save, text="", anchor="w",
                                        justify="left", wraplength=640)
        self.saved_label.pack(fill="x")
        ctk.CTkLabel(self._after_save, text=services.NOT_CONTACTED,
                     anchor="w").pack(fill="x")
        ctk.CTkLabel(self._after_save, text=services.MAY_I_CONTACT, anchor="w",
                     font=ctk.CTkFont(weight="bold")).pack(fill="x", pady=(8, 4))
        answers = ctk.CTkFrame(self._after_save, fg_color="transparent")
        answers.pack(fill="x")
        ctk.CTkButton(answers, text="Not now", command=self.on_not_now,
                      fg_color="transparent", border_width=1).pack(side="left")
        ctk.CTkButton(answers, text="Check it", command=self.on_check_typed,
                      fg_color=PRIMARY).pack(side="left", padx=8)

    def _field(self, parent, label: str) -> ctk.CTkEntry:
        """A labelled entry on one row."""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=3)
        ctk.CTkLabel(row, text=label, width=190, anchor="w").pack(side="left")
        entry = ctk.CTkEntry(row, width=300)
        entry.pack(side="left")
        return entry

    def _show_pane(self, name: str) -> None:
        """Bring one pane forward and clear the answer line on it."""
        for key, widget in self._panes.items():
            if key == name:
                widget.pack(fill="both", expand=True)
            else:
                widget.pack_forget()
        self.shown_pane = name
        self._say("")

    def _say(self, text: str) -> None:
        """Put an answer on the pane that is showing."""
        note = self._notes.get(self.shown_pane)
        if note is not None:
            note.configure(text=text)

    # --------------------------------------------------------------- rendering

    def refresh(self) -> None:
        """Read what is recorded and show it. Does nothing while a look runs.

        A look is writing the store from the worker thread, and the read here
        could land mid-write. The look's closing event refreshes the tab
        itself, so nothing is lost by waiting for it.
        """
        if self._busy:
            return
        self.render(self.run_list())
        if self.shown_pane != "home":
            self._show_pane("home")

    def run_list(self) -> services.NodeListResult:
        """Every recorded computer, and the panel. No widget touched."""
        return services.list_nodes(self.store)

    def render(self, result: services.NodeListResult) -> None:
        """Show the cards and the panel, or the §3.2 invitation when empty."""
        self._last = result
        self.content.destroy()
        self.content = ctk.CTkFrame(self._scroll, fg_color="transparent")
        self.content.pack(fill="both", expand=True)
        self._busy_widgets = [w for w in self._busy_widgets if _exists(w)]
        self._edit_entries = {}

        if not result.ok:
            # The stored file cannot be used. The refusal names the file and
            # a way out, and this is the one screen somebody could act on it.
            self._text(self.content, result.refusal or result.summary)
            return
        if not result.rows:
            self._empty_state(self.content)
        else:
            for row in result.rows:
                self._card(self.content, row)
            actions = ctk.CTkFrame(self.content, fg_color="transparent")
            actions.pack(fill="x", padx=6, pady=(6, 10))
            self._button(actions, "Look for more", self.on_look, primary=True)
            self._button(actions, "Add one by hand", self.on_add)
        self._panel(self.content, result)

    def _empty_state(self, parent) -> None:
        """Design §3.2."""
        self._text(parent, "Is something like Ollama or llama.cpp running?",
                   bold=True)
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=6, pady=8)
        self._button(row, "Look for it", self.on_look, primary=True)
        self._button(row, "I'll type it in", self.on_add)
        self._text(parent, 'Not sure? "Look for it" only checks this computer\n'
                           "unless you say otherwise.", muted=True)

    def _card(self, parent, row: services.NodeRowView) -> None:
        """Design §3.5: every fact with where it came from."""
        card = ctk.CTkFrame(parent, fg_color=CARD_BG, corner_radius=8)
        card.pack(fill="x", padx=6, pady=6)
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=10, pady=(8, 0))
        ctk.CTkLabel(head, text=row.label, anchor="w",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")
        ctk.CTkLabel(head, text=row.status, anchor="e",
                     text_color=MUTED).pack(side="right")

        grid = ctk.CTkFrame(card, fg_color="transparent")
        grid.pack(fill="x", padx=10, pady=4)
        grid.grid_columnconfigure(1, weight=1)
        editing = row.node_id == self._editing
        for index, item in enumerate(row.fields):
            ctk.CTkLabel(grid, text=item.label, anchor="w", width=150).grid(
                row=index, column=0, sticky="w")
            if editing and item.editable:
                entry = ctk.CTkEntry(grid, width=280)
                entry.insert(0, item.value)
                entry.grid(row=index, column=1, sticky="w", pady=1)
                self._edit_entries[item.name] = entry
            else:
                ctk.CTkLabel(grid, text=item.value, anchor="w").grid(
                    row=index, column=1, sticky="w")
            ctk.CTkLabel(grid, text=item.source, anchor="e",
                         text_color=MUTED).grid(row=index, column=2, sticky="e")

        buttons = ctk.CTkFrame(card, fg_color="transparent")
        buttons.pack(fill="x", padx=10, pady=(2, 10))
        node_id = row.node_id
        if editing:
            self._button(buttons, "Save",
                         lambda: self.on_save_change(node_id), primary=True)
            self._button(buttons, "Cancel", self.on_cancel_change)
            return
        self._button(buttons, "Change something", lambda: self.on_change(node_id))
        self._button(buttons, "Check again", lambda: self.on_check(node_id))
        forget = ("Press again to forget it" if self._forget_armed == node_id
                  else "Forget")
        self._button(buttons, forget, lambda: self.on_forget(node_id))

    def _panel(self, parent, result: services.NodeListResult) -> None:
        """Design §3.6: figures, and at most one consequence."""
        panel = ctk.CTkFrame(parent, fg_color="transparent")
        panel.pack(fill="x", padx=6, pady=(10, 4))
        ctk.CTkLabel(panel, text="What this means when steps run", anchor="w",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=PRIMARY).pack(fill="x")
        grid = ctk.CTkFrame(panel, fg_color="transparent")
        grid.pack(fill="x", pady=4)
        for index, (label, value) in enumerate(result.summary_rows):
            ctk.CTkLabel(grid, text=label, anchor="w", width=240).grid(
                row=index, column=0, sticky="w", padx=(10, 0))
            ctk.CTkLabel(grid, text=value, anchor="w", justify="left").grid(
                row=index, column=1, sticky="w")
        if result.consequence:
            self._text(panel, result.consequence)

    def _text(self, parent, text: str, *, bold: bool = False,
              muted: bool = False) -> None:
        """A paragraph."""
        ctk.CTkLabel(
            parent, text=text, anchor="w", justify="left", wraplength=640,
            font=ctk.CTkFont(weight="bold") if bold else None,
            text_color=MUTED if muted else None,
        ).pack(fill="x", padx=6, pady=2)

    def _button(self, parent, text: str, command, *, primary: bool = False):
        """A button that is disabled while a look runs."""
        button = ctk.CTkButton(
            parent, text=text, command=command,
            fg_color=PRIMARY if primary else "transparent",
            border_width=0 if primary else 1,
            state="disabled" if self._busy else "normal",
        )
        button.pack(side="left", padx=(0, 8))
        self._busy_widgets.append(button)
        return button

    def append_event(self, event: services.ScanEventView) -> None:
        """Add one finding to the log as it arrives (§3.4).

        A stop before looking — no permission, not built, no address, a file
        that cannot be used — is the answer rather than one more finding, so
        it is written as a sentence and not marked like a row.
        """
        if event.stage in services.REFUSAL_STAGES:
            line = f"{event.message}\n"
        else:
            # An attempt is not a finding, so it does not get §3.4's tick.
            if event.stage == "trying":
                mark = "…"
            else:
                mark = "✓" if event.ok else "–"
            line = f"  {mark}  {event.message}\n"
        self.log.insert("end", line)
        self.log.see("end")

    # ----------------------------------------------------------------- actions

    def on_look(self) -> None:
        """Ask where to look (§3.3). Nothing is opened by this press."""
        if self._refuse_while_busy():
            return
        self.scope_var.set(services.ScanScope.THIS_MACHINE.value)
        # Only when something was typed: clearing an entry that is showing
        # its hint deletes the hint, and it does not come back until the
        # entry is focused and left.
        if self.address_entry.get():
            self.address_entry.delete(0, "end")
        self.on_looks_right()
        self._show_pane("permission")

    def on_cancel(self) -> None:
        """Back to the cards, having looked at nothing."""
        self._show_pane("home")

    def on_permission_look(self) -> None:
        """Take the permission chosen.

        "Don't look at anything" is the §3.8 route and opens nothing. The
        other three go to the service as asked; it answers the sweep that is
        not built and the missing address itself, so nothing is decided here.
        """
        if self._refuse_while_busy():
            return
        scope = services.ScanScope(self.scope_var.get())
        if scope is services.ScanScope.NONE:
            self.on_add()
            return
        host = self.address_entry.get()
        self._show_pane("home")
        self._stream(lambda: services.scan(
            scope, host, store=self.store, actor=ACTOR,
            fetch=self.fetch, post=self.post,
        ))

    def on_add(self) -> None:
        """Design §3.8, first half: say what is recorded, then ask."""
        if self._refuse_while_busy():
            return
        current = self.run_list()
        first, second = services.typed_in_opening(
            [row.label for row in current.rows] if current.ok else []
        )
        self.typed_first.configure(text=first)
        self.typed_second.configure(text=second)
        for entry in (self.name_entry, self.typed_address_entry):
            entry.delete(0, "end")
        self.kind_var.set(services.KIND_CHOICES[0][0])
        self._added = None
        # The findings of an earlier look are about that look. Left up, they
        # sat above the cards after this route returned, describing nothing
        # the person had just done.
        self.on_looks_right()
        self._after_save.pack_forget()
        self.save_button.configure(state="normal")
        self._show_pane("typed")

    def on_save_typed(self) -> None:
        """Save what was typed, unchecked. Contacts nothing."""
        if self._refuse_while_busy():
            return
        result = services.add_node(
            self.name_entry.get(), self.kind_var.get(),
            self.typed_address_entry.get(), self.store,
        )
        if not result.ok:
            self._say(result.refusal or result.summary)
            return
        self._added = result
        self.saved_label.configure(
            text=f"Saved {self.name_entry.get()} at {result.url}."
        )
        self.save_button.configure(state="disabled")
        self._say("")
        self._after_save.pack(fill="x", padx=12, pady=(4, 8))

    def on_not_now(self) -> None:
        """Leave it unchecked. Back to the cards, where it is counted as such."""
        self.refresh()

    def on_check_typed(self) -> None:
        """The separate yes: look at the computer just saved, and nothing else."""
        if self._added is not None:
            self.on_check(self._added.node_id)

    def on_check(self, node_id: str) -> None:
        """Look at one recorded computer again (§3.5 "Check again")."""
        if self._refuse_while_busy():
            return
        self._show_pane("home")
        self._stream(lambda: services.check_node(
            node_id, self.store, actor=ACTOR, fetch=self.fetch, post=self.post,
        ))

    def on_change(self, node_id: str) -> None:
        """Open a card's editable fields."""
        if self._refuse_while_busy():
            return
        self._editing = node_id
        self._forget_armed = ""
        if self._last is not None:
            self.render(self._last)

    def on_cancel_change(self) -> None:
        """Close the card without saving."""
        self._editing = ""
        if self._last is not None:
            self.render(self._last)

    def on_save_change(self, node_id: str) -> None:
        """Save every field that was changed. Each becomes "you told me".

        The one place on this tab that rewrites a stored computer in place,
        so the one the busy guard exists most for.
        """
        if self._refuse_while_busy():
            return
        before = {}
        if self._last is not None:
            for row in self._last.rows:
                if row.node_id == node_id:
                    before = {f.name: f.value for f in row.fields}
        for name, entry in self._edit_entries.items():
            value = entry.get()
            if value == before.get(name):
                continue
            outcome = services.update_field(node_id, name, value, self.store)
            if not outcome.ok:
                self._say(outcome.refusal or outcome.summary)
                return
        self._editing = ""
        self.refresh()

    def on_forget(self, node_id: str) -> None:
        """Remove a computer, on the second press."""
        if self._refuse_while_busy():
            return
        if self._forget_armed != node_id:
            self._forget_armed = node_id
            if self._last is not None:
                self.render(self._last)
            return
        self._forget_armed = ""
        outcome = services.forget_node(node_id, self.store)
        self.refresh()
        if not outcome.ok:
            self._say(outcome.refusal or outcome.summary)

    def on_looks_right(self) -> None:
        """Put the findings log away."""
        self.log.delete("1.0", "end")
        self.log.pack_forget()
        self._log_actions.pack_forget()

    def _refuse_while_busy(self) -> bool:
        """Say so and return True when a look is still running."""
        if self._busy:
            self._say(BUSY)
            return True
        return False

    # --------------------------------------------------------------- threading

    def _stream(self, events) -> None:
        """Run a look off the UI thread, delivering each finding as it is made.

        ``events`` is called on the worker and must return an iterator of
        ``ScanEventView``. Each one is queued the moment it arrives; the
        poller renders it. **The worker never touches Tk** — see
        ``WorkflowTab._in_worker`` for why that is not optional.
        """
        self._set_busy(True)
        self.log.delete("1.0", "end")
        self._show_log(with_actions=False)

        def runner() -> None:
            try:
                for event in events():
                    self._results.put(("event", event))
            except Exception as exc:  # noqa: BLE001 — surfaced, not swallowed
                self._results.put(("event", services.ScanEventView(
                    stage="error", message=f"Something went wrong: {exc!r}",
                    ok=False, finished=True,
                )))
            self._results.put(("done", None))

        self._worker = threading.Thread(target=runner, daemon=True)
        self._worker.start()

    def _set_busy(self, busy: bool) -> None:
        """Mark a look as running, and disable or enable what writes."""
        self._busy = busy
        for widget in self._busy_widgets:
            if _exists(widget):
                widget.configure(state="disabled" if busy else "normal")

    def _schedule_poll(self) -> None:
        """Arm the next queue check. UI thread only."""
        self._poll_id = self.after(_POLL_MS, self._poll)

    def _poll(self) -> None:
        """Deliver what arrived, then re-arm. Stops once the widget is gone."""
        if not _exists(self):
            self._poll_id = None
            return
        self.drain()
        self._schedule_poll()

    def drain(self) -> None:
        """Deliver every queued finding. UI thread only; public for tests."""
        while True:
            try:
                kind, payload = self._results.get_nowait()
            except queue.Empty:
                return
            if kind == "event":
                self.append_event(payload)
                continue
            self._set_busy(False)
            self.refresh()
            self._show_log(with_actions=True)

    def _show_log(self, *, with_actions: bool) -> None:
        """Put the findings log above the cards.

        Re-packed in order rather than packed ``before=`` the cards: the
        scrollable frame is not itself packed — customtkinter packs a frame
        around it and redirects ``pack`` and ``pack_forget`` to that frame —
        so ``before=`` it raises. Going through its own methods is what those
        redirects exist for.
        """
        self._scroll.pack_forget()
        self._log_actions.pack_forget()
        self.log.pack(fill="x", padx=12, pady=(4, 4))
        if with_actions:
            self._log_actions.pack(fill="x", padx=12)
        self._scroll.pack(fill="both", expand=True, padx=6, pady=(4, 8))

    @property
    def busy(self) -> bool:
        """Whether a look is running."""
        return self._busy

    def destroy(self) -> None:
        """Cancel the poller and let a running look finish first."""
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

    # -------------------------------------------------------------- test hooks

    def shown(self) -> str:
        """Every piece of text a person can currently see on this tab.

        Walks the introduction and the pane that is showing, and skips
        anything not placed on screen — a pane put away still exists, and
        reading its words back would test text nobody can see.
        """
        parts: list[str] = []
        for root in (self._intro, self._panes[self.shown_pane]):
            _collect(root, parts)
        return "\n".join(parts)

    def cards(self) -> list[str]:
        """The name on each card, in order."""
        if self._last is None or not self._last.ok:
            return []
        return [row.label for row in self._last.rows]

    def fill_typed(self, name: str = "", address: str = "", kind: str = "") -> None:
        """Type into the §3.8 fields, as a person would."""
        for entry, value in ((self.name_entry, name),
                             (self.typed_address_entry, address)):
            entry.delete(0, "end")
            entry.insert(0, value)
        if kind:
            self.kind_var.set(kind)


def _exists(widget) -> bool:
    """Whether a widget is still alive."""
    try:
        return bool(widget.winfo_exists())
    except Exception:  # noqa: BLE001 — a dead interpreter is not alive
        return False


def _collect(widget, parts: list[str]) -> None:
    """Append the text of a widget and every placed descendant."""
    if isinstance(widget, ctk.CTkTextbox):
        parts.append(widget.get("1.0", "end").strip())
        return
    if isinstance(widget, (ctk.CTkLabel, ctk.CTkButton, ctk.CTkRadioButton)):
        text = str(widget.cget("text"))
        if text:
            parts.append(text)
    for child in widget.winfo_children():
        if child.winfo_manager():
            _collect(child, parts)
