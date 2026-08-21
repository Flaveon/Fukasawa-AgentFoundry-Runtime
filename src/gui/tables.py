# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""A grouped table, because §16.4 and §16.8 both ask for one.

CustomTkinter has no table widget, so this is a scrollable frame of gridded
labels. It is deliberately small and deliberately dumb: it renders rows it is
handed and reports which one was clicked. It sorts nothing, groups nothing, and
knows no domain vocabulary — the service decided the order and the grouping
before the rows arrived, which is what keeps the ordering rule in one place
(`_finding_views`) rather than in two.

The one piece of judgment here is that a **group header is a row too**. Findings
grouped by severity and assessments grouped by nothing share a widget because
"no groups" is one group with an empty title, not a different layout.
"""

import customtkinter as ctk

#: Brand palette, matching `workflow_views`.
PRIMARY = "#A855F7"
MUTED = ("gray45", "gray60")
HEADER_BG = ("gray85", "gray20")
GROUP_FG = ("gray20", "gray80")

#: Row backgrounds, alternating. Zebra striping rather than grid lines: a table
#: an operator scans across, looking for one step, is easier to hold a line in.
#: The unstriped row is the bare string "transparent" rather than a light/dark
#: pair — customtkinter rejects transparency inside a tuple colour.
STRIPE = (("gray95", "gray17"), "transparent")


class Row:
    """One rendered row and the object it came from.

    Holds the source object so a click can hand the caller back the finding or
    assessment itself rather than the strings it was rendered into. Parsing a
    step id back out of a label is how a table starts lying about what was
    selected.
    """

    def __init__(self, cells: list[str], source: object = None, tone: str = "") -> None:
        """Cells in column order, plus whatever the row represents."""
        self.cells = cells
        self.source = source
        #: Optional colour cue: "" normal, "alert" for a blocking/floored row.
        self.tone = tone


class Group:
    """A titled run of rows. An empty title renders no header."""

    def __init__(self, title: str, rows: list[Row]) -> None:
        """A group's heading and its rows, already in display order."""
        self.title = title
        self.rows = rows


class Table(ctk.CTkScrollableFrame):
    """A read-only grouped table with selectable rows."""

    def __init__(
        self,
        parent,
        columns: list[str],
        weights: list[int] | None = None,
        on_select=None,
        **kwargs,
    ) -> None:
        """Build an empty table.

        ``weights`` distributes horizontal space across columns; the default
        gives the last column everything left over, which is right for tables
        whose final column is prose.
        """
        super().__init__(parent, **kwargs)
        self.columns = columns
        self.on_select = on_select
        self._weights = weights or [0] * (len(columns) - 1) + [1]
        for index, weight in enumerate(self._weights):
            self.grid_columnconfigure(index, weight=weight)
        self._next_row = 0
        self.rows: list[Row] = []
        self.selected: Row | None = None
        self._row_widgets: list[tuple[Row, list[ctk.CTkLabel]]] = []
        #: Every label this table created, in creation order. Tracked rather
        #: than rediscovered: `winfo_children()` on a CTkScrollableFrame also
        #: returns the canvas and scrollbar it is built from, and destroying
        #: the canvas takes the labels' Tk objects with it — after which
        #: destroying a label raises from inside customtkinter.
        self._owned: list[ctk.CTkLabel] = []

    # ----------------------------------------------------------------- render

    def clear(self) -> None:
        """Remove every row, including headers."""
        for widget in self._owned:
            try:
                widget.destroy()
            except Exception:  # noqa: BLE001 — an already-dead widget is cleared
                pass
        self._owned = []
        self._next_row = 0
        self.rows = []
        self.selected = None
        self._row_widgets = []

    def show(self, groups: list[Group]) -> None:
        """Replace the contents with these groups, in the order given."""
        self.clear()
        self._header()
        for group in groups:
            if group.title:
                self._group_header(group.title, len(group.rows))
            for row in group.rows:
                self._row(row)

    def _header(self) -> None:
        """The column-name row."""
        for column, name in enumerate(self.columns):
            label = ctk.CTkLabel(
                self,
                text=name,
                anchor="w",
                font=ctk.CTkFont(size=12, weight="bold"),
                fg_color=HEADER_BG,
                corner_radius=0,
            )
            label.grid(row=self._next_row, column=column, sticky="ew", padx=1, pady=(0, 1))
            self._owned.append(label)
        self._next_row += 1

    def _group_header(self, title: str, count: int) -> None:
        """A band naming the group and how many rows are in it.

        The count is shown because "ERROR" alone does not tell an operator
        whether they are looking at one problem or twenty, and that is the
        first thing they want to know.
        """
        label = ctk.CTkLabel(
            self,
            text=f"  {title}  ({count})",
            anchor="w",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=PRIMARY,
        )
        label.grid(
            row=self._next_row,
            column=0,
            columnspan=len(self.columns),
            sticky="ew",
            pady=(8, 1),
        )
        self._owned.append(label)
        self._next_row += 1

    def _row(self, row: Row) -> None:
        """One data row, striped, clickable."""
        stripe = STRIPE[len(self.rows) % 2]
        labels = []
        for column, cell in enumerate(row.cells[: len(self.columns)]):
            label = ctk.CTkLabel(
                self,
                text=cell,
                anchor="w",
                justify="left",
                wraplength=460 if column == len(self.columns) - 1 else 0,
                fg_color=stripe,
                text_color=PRIMARY if row.tone == "alert" else ("gray10", "gray90"),
                corner_radius=0,
            )
            label.grid(row=self._next_row, column=column, sticky="ew", padx=1)
            label.bind("<Button-1>", lambda _e, r=row: self.select(r))
            labels.append(label)
            self._owned.append(label)
        self._row_widgets.append((row, labels))
        self.rows.append(row)
        self._next_row += 1

    # ---------------------------------------------------------------- selection

    def select(self, row: Row) -> None:
        """Mark a row selected and tell the caller.

        Public and takes a Row rather than an index so a headless test can
        select without synthesising a click event.
        """
        self.selected = row
        for candidate, labels in self._row_widgets:
            chosen = candidate is row
            for label in labels:
                label.configure(
                    fg_color=(PRIMARY if chosen else STRIPE[self.rows.index(candidate) % 2]),
                    text_color=("gray98", "gray98") if chosen else ("gray10", "gray90"),
                )
        if self.on_select is not None:
            self.on_select(row)

    def selected_source(self) -> object:
        """Whatever the selected row represents, or None."""
        return self.selected.source if self.selected else None

    def rendered(self) -> list[list[str]]:
        """Every data row's cells, for tests and for copy-out."""
        return [row.cells for row in self.rows]
