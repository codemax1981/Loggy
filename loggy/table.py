"""A fast, read-only table for the logbook.

Textual's DataTable does a lot of work for every row it is given, which makes
a long career logbook slow to refresh. This table keeps each row as plain
strings and draws only the lines that are on screen, so it stays quick with
tens of thousands of entries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from rich.cells import cell_len, set_cell_size
from rich.segment import Segment
from rich.style import Style
from textual import events
from textual.binding import Binding
from textual.geometry import Size
from textual.message import Message
from textual.scroll_view import ScrollView
from textual.strip import Strip

PADDING = 1  # spaces either side of every cell


@dataclass(frozen=True)
class Column:
    label: str
    right: bool = False  # right-align, for numbers


def fit(text: str, width: int, right: bool = False) -> str:
    """Pad or shorten ``text`` to exactly ``width`` cells."""
    length = cell_len(text)
    if length > width:
        return set_cell_size(text, max(width - 1, 0)) + "…" if width else ""
    padding = " " * (width - length)
    return padding + text if right else text + padding


def column_widths(columns: Sequence[Column], rows: Sequence[Sequence[str]]) -> list[int]:
    widths = [cell_len(column.label) for column in columns]
    for index, values in enumerate(zip(*rows)):
        widths[index] = max(widths[index], max(map(cell_len, values)))
    return widths


class LogTable(ScrollView, can_focus=True):
    """Rows of plain-text cells with a row cursor and a fixed header."""

    COMPONENT_CLASSES = {
        "log-table--header",
        "log-table--cursor",
        "log-table--even-row",
        "log-table--muted",
    }

    DEFAULT_CSS = """
    LogTable {
        background: $surface;
        color: $foreground;
        &:focus {
            background-tint: $foreground 5%;
            & > .log-table--cursor {
                background: $block-cursor-background;
                color: $block-cursor-foreground;
                text-style: $block-cursor-text-style;
            }
            & > .log-table--header {
                background-tint: $foreground 5%;
            }
        }
        & > .log-table--header {
            text-style: bold;
            background: $panel;
            color: $foreground;
        }
        & > .log-table--even-row {
            background: $surface-lighten-1 50%;
        }
        &:dark > .log-table--even-row {
            background: $surface-darken-1 40%;
        }
        & > .log-table--cursor {
            background: $block-cursor-blurred-background;
            color: $block-cursor-blurred-foreground;
            text-style: $block-cursor-blurred-text-style;
        }
        & > .log-table--muted {
            text-style: italic;
        }
    }
    """

    BINDINGS = [
        Binding("up", "move(-1)", "Up", show=False),
        Binding("down", "move(1)", "Down", show=False),
        Binding("pageup", "page(-1)", "Page up", show=False),
        Binding("pagedown", "page(1)", "Page down", show=False),
        Binding("home", "first", "First", show=False),
        Binding("end", "last", "Last", show=False),
        Binding("enter", "select", "Select", show=False),
    ]

    class Highlighted(Message):
        """The cursor moved to another row."""

        def __init__(self, table: LogTable, row: int) -> None:
            super().__init__()
            self.table = table
            self.row = row

        @property
        def control(self) -> LogTable:
            return self.table

    class Selected(Message):
        """Enter was pressed on a row, or the cursor row was clicked."""

        def __init__(self, table: LogTable, row: int) -> None:
            super().__init__()
            self.table = table
            self.row = row

        @property
        def control(self) -> LogTable:
            return self.table

    def __init__(self, columns: Sequence[Column], *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.columns = tuple(columns)
        self._rows: list[Sequence[str]] = []
        self._muted: list[bool] = []
        self.widths = [cell_len(column.label) for column in self.columns]
        self._cursor = 0

    # -- data ----------------------------------------------------------------------------

    @property
    def row_count(self) -> int:
        return len(self._rows)

    @property
    def cursor_row(self) -> int:
        return self._cursor

    def cell(self, row: int, column: int) -> str:
        return self._rows[row][column]

    def set_rows(
        self,
        rows: Sequence[Sequence[str]],
        widths: Sequence[int],
        *,
        muted: Sequence[bool] = (),
        cursor: int = 0,
    ) -> None:
        """Replace every row; ``widths`` gives each column's width in cells."""
        self._rows = list(rows)
        self._muted = list(muted) or [False] * len(self._rows)
        self.widths = list(widths)
        line_width = sum(width + 2 * PADDING for width in self.widths)
        self.virtual_size = Size(line_width, len(self._rows) + 1)
        self.move_cursor(cursor)
        self.refresh()

    # -- cursor --------------------------------------------------------------------------

    def move_cursor(self, row: int) -> None:
        row = max(0, min(row, len(self._rows) - 1))
        self._cursor = row
        visible = max(1, self.scrollable_content_region.height - 1)  # rows below the header
        top = round(self.scroll_target_y)
        if row < top:
            self.scroll_to(y=row, animate=False)
        elif row >= top + visible:
            self.scroll_to(y=row - visible + 1, animate=False)
        self.refresh()
        if self._rows:
            self.post_message(self.Highlighted(self, row))

    def action_move(self, delta: int) -> None:
        self.move_cursor(self._cursor + delta)

    def action_page(self, direction: int) -> None:
        page = max(1, self.scrollable_content_region.height - 2)
        self.move_cursor(self._cursor + direction * page)

    def action_first(self) -> None:
        self.move_cursor(0)

    def action_last(self) -> None:
        self.move_cursor(len(self._rows) - 1)

    def action_select(self) -> None:
        if self._rows:
            self.post_message(self.Selected(self, self._cursor))

    def on_click(self, event: events.Click) -> None:
        if event.y < 1:  # the header
            return
        row = int(self.scroll_offset.y) + event.y - 1
        if 0 <= row < len(self._rows):
            if row == self._cursor:
                self.post_message(self.Selected(self, row))
            else:
                self.move_cursor(row)

    # -- drawing -------------------------------------------------------------------------

    def _line(self, cells: Sequence[str]) -> str:
        pad = " " * PADDING
        return "".join(
            pad + fit(cell, width, column.right) + pad
            for cell, width, column in zip(cells, self.widths, self.columns)
        )

    def render_line(self, y: int) -> Strip:
        scroll_x, scroll_y = self.scroll_offset
        width = self.scrollable_content_region.width
        if y == 0:
            style = self.get_component_rich_style("log-table--header")
            text = self._line([column.label for column in self.columns])
        else:
            index = scroll_y + y - 1
            if index >= len(self._rows):
                return Strip.blank(width, self.rich_style)
            style = self._row_style(index)
            text = self._line(self._rows[index])
        return Strip([Segment(text, style)], cell_len(text)).crop_extend(
            scroll_x, scroll_x + width, style
        )

    def _row_style(self, index: int) -> Style:
        if index == self._cursor:
            style = self.get_component_rich_style("log-table--cursor")
        elif index % 2:
            style = self.get_component_rich_style("log-table--even-row")
        else:
            style = self.rich_style
        if self._muted[index]:
            style += self.get_component_rich_style("log-table--muted", partial=True)
        return style
