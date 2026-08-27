# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""The two dialogs that take a reason — §16.6 and §16.9.

Accepting a risk and overriding an executor are the only places in the desktop
where a person overrules the runtime, and both contracts make the rationale
mandatory (`RiskAcceptance.rationale`, `ExecutorOverride.rationale`, both
``min_length=1``). Phase 7 shipped neither, on the reasoning that a dialog
which let someone skip the reason would be worse than no dialog. That reasoning
is preserved here as the design: **the confirm button stays disabled until the
reason has content**, so the mandatory field is mandatory on the screen and not
only in the service that would have refused afterwards.

The service refusal is still the authority. Nothing here validates anything —
the button state is a courtesy that saves a round trip, and both dialogs hand
their values to a service that will refuse an empty reason regardless. That is
the same rule the rest of the desktop follows: the view decides nothing, it
just declines to submit something it can see is incomplete.

Both are modal (``grab_set``): these are decisions, and a decision half-made in
a window someone clicked away from is the thing an audit trail cannot explain.
"""

import customtkinter as ctk

PRIMARY = "#A855F7"
MUTED = ("gray45", "gray60")

#: Minimum characters a rationale must have before Confirm enables. One
#: non-space character is the contract's bar; this does not raise it, because a
#: view inventing a stricter rule than the contract is a second validator.
_MIN_REASON = 1


class ReasonDialog(ctk.CTkToplevel):
    """A modal that collects an actor, a reason, and one choice.

    Shared by both §16.6 and §16.9 because they are the same shape: here is
    what you are about to overrule, who are you, why, and — for the override —
    to what. Two near-identical dialogs would be two places to forget to
    disable the button.
    """

    def __init__(
        self,
        parent,
        *,
        title: str,
        subject: str,
        detail: str = "",
        actor: str = "",
        choices: list[str] | None = None,
        choice_label: str = "",
        confirm_text: str = "Confirm",
        warning: str = "",
    ) -> None:
        """Build and show the dialog. Does not block; use ``wait()``."""
        super().__init__(parent)
        self.title(title)
        self.geometry("560x460")
        self.result: dict | None = None

        ctk.CTkLabel(
            self,
            text=title,
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=PRIMARY,
            anchor="w",
        ).pack(fill="x", padx=16, pady=(14, 2))
        ctk.CTkLabel(self, text=subject, anchor="w", justify="left", wraplength=520).pack(
            fill="x", padx=16
        )
        if detail:
            ctk.CTkLabel(
                self,
                text=detail,
                anchor="w",
                justify="left",
                wraplength=520,
                text_color=MUTED,
            ).pack(fill="x", padx=16, pady=(4, 0))
        if warning:
            ctk.CTkLabel(
                self,
                text=warning,
                anchor="w",
                justify="left",
                wraplength=520,
                text_color=PRIMARY,
            ).pack(fill="x", padx=16, pady=(8, 0))

        self.choice_box = None
        if choices:
            ctk.CTkLabel(self, text=choice_label, anchor="w").pack(
                fill="x", padx=16, pady=(12, 0)
            )
            self.choice_box = ctk.CTkOptionMenu(self, values=choices)
            self.choice_box.pack(fill="x", padx=16)

        ctk.CTkLabel(self, text="Your name", anchor="w").pack(
            fill="x", padx=16, pady=(12, 0)
        )
        self.actor_entry = ctk.CTkEntry(self, placeholder_text="who is deciding this")
        self.actor_entry.pack(fill="x", padx=16)
        if actor:
            self.actor_entry.insert(0, actor)

        ctk.CTkLabel(
            self,
            text="Reason — required",
            anchor="w",
        ).pack(fill="x", padx=16, pady=(12, 0))
        self.reason_box = ctk.CTkTextbox(self, height=110, wrap="word")
        self.reason_box.pack(fill="x", padx=16)
        self.reason_box.bind("<KeyRelease>", lambda _e: self.refresh())

        self.hint = ctk.CTkLabel(
            self,
            text="A decision without a reason is indistinguishable from a mis-click.",
            anchor="w",
            text_color=MUTED,
            wraplength=520,
            justify="left",
        )
        self.hint.pack(fill="x", padx=16, pady=(4, 0))

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=16, pady=14)
        self.confirm_button = ctk.CTkButton(
            buttons, text=confirm_text, command=self.confirm, state="disabled"
        )
        self.confirm_button.pack(side="right")
        ctk.CTkButton(
            buttons,
            text="Cancel",
            command=self.cancel,
            fg_color="transparent",
            border_width=1,
        ).pack(side="right", padx=(0, 8))

        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.refresh()
        try:
            self.grab_set()
        except Exception:  # noqa: BLE001 — a headless test has nothing to grab
            pass

    # -------------------------------------------------------------- behaviour

    def reason(self) -> str:
        """Whatever is in the reason box."""
        return self.reason_box.get("1.0", "end").strip()

    def actor(self) -> str:
        """Whatever is in the name box."""
        return self.actor_entry.get().strip()

    def choice(self) -> str:
        """The selected option, or "" when the dialog has no choice."""
        return self.choice_box.get() if self.choice_box is not None else ""

    def complete(self) -> bool:
        """Whether the mandatory fields have content."""
        return len(self.reason()) >= _MIN_REASON and bool(self.actor())

    def refresh(self) -> None:
        """Enable or disable Confirm to match the mandatory fields."""
        ready = self.complete()
        self.confirm_button.configure(state="normal" if ready else "disabled")
        self.hint.configure(
            text=(
                "Recorded with your name and the time."
                if ready
                else "A decision without a name and a reason is "
                "indistinguishable from a mis-click."
            )
        )

    def confirm(self) -> None:
        """Take the values and close. Refuses to close while incomplete."""
        if not self.complete():
            return
        self.result = {
            "actor": self.actor(),
            "rationale": self.reason(),
            "choice": self.choice(),
        }
        self._close()

    def cancel(self) -> None:
        """Close with no result."""
        self.result = None
        self._close()

    def _close(self) -> None:
        """Release the grab and destroy, in that order."""
        try:
            self.grab_release()
        except Exception:  # noqa: BLE001 — teardown must not raise
            pass
        self.destroy()

    def wait(self) -> dict | None:
        """Block until the dialog closes, then return its values or None."""
        self.wait_window()
        return self.result
