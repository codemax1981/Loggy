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
    group: str = ""  # a heading shared with the neighbouring columns of the same group
    short: str = ""  # the heading when the column is too narrow for ``label``

    def heading(self, width: int) -> str:
        return self.label if cell_len(self.label) <= width or not self.short else self.short


def fit(text: str, width: int, right: bool = False) -> str:
    """Pad or shorten ``text`` to exactly ``width`` cells."""
    length = cell_len(text)
    if length > width:
        return set_cell_size(text, max(width - 1, 0)) + "…" if width else ""
    padding = " " * (width - length)
    return padding + text if right else text + padding


def groups(columns: Sequence[Column]) -> list[tuple[int, int]]:
    """The ``(start, end)`` index range of each run of columns that share a group."""
    runs = []
    start = 0
    while start < len(columns):
        end = start + 1
        group = columns[start].group
        while group and end < len(columns) and columns[end].group == group:
            end += 1
        if group:
            runs.append((start, end))
        start = end
    return runs


def column_widths(columns: Sequence[Column], rows: Sequence[Sequence[str]]) -> list[int]:
    """Each column's width: its widest cell or heading, and wide enough for its group's
    heading. A column with a short heading is only as wide as that and its cells."""
    widths = [cell_len(column.short or column.label) for column in columns]
    for index, values in enumerate(zip(*rows)):
        widths[index] = max(widths[index], max(map(cell_len, values)))
    for start, end in groups(columns):
        span = sum(widths[start:end]) + 2 * PADDING * (end - start)
        short = cell_len(columns[start].group) + 2 - span  # room for " heading "
        for step in range(max(short, 0)):
            widths[start + step % (end - start)] += 1
    return widths


class LogTable(ScrollView, can_focus=True):
    """Rows of plain-text cells with a row cursor and a fixed header.

    A table wider than the screen scrolls sideways a column at a time, and its first
    ``fixed`` columns stay in view while it does, as frozen panes do in a spreadsheet.
    """

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
        Binding("left", "column(-1)", "Scroll left", show=False),
        Binding("right", "column(1)", "Scroll right", show=False),
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

    def __init__(self, columns: Sequence[Column], *, fixed: int = 0,
                 id: str | None = None) -> None:
        super().__init__(id=id)
        self.columns = tuple(columns)
        self.fixed = fixed
        self._rows: list[Sequence[str]] = []
        self._header_lines = 1
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
        columns: Sequence[Column] | None = None,
    ) -> None:
        """Replace every row; ``widths`` gives each column's width in cells."""
        if columns is not None:
            self.columns = tuple(columns)
        self._header_lines = 2 if any(column.group for column in self.columns) else 1
        self._rows = list(rows)
        self._muted = list(muted) or [False] * len(self._rows)
        self.widths = list(widths)
        line_width = sum(width + 2 * PADDING for width in self.widths)
        self.virtual_size = Size(line_width, len(self._rows) + self._header_lines)
        self.move_cursor(cursor)
        self.refresh()

    # -- cursor --------------------------------------------------------------------------

    def move_cursor(self, row: int) -> None:
        row = max(0, min(row, len(self._rows) - 1))
        self._cursor = row
        visible = max(1, self.scrollable_content_region.height - self._header_lines)
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
        page = max(1, self.scrollable_content_region.height - self._header_lines - 1)
        self.move_cursor(self._cursor + direction * page)

    def action_first(self) -> None:
        self.move_cursor(0)

    def action_last(self) -> None:
        self.move_cursor(len(self._rows) - 1)

    def _fixed_width(self) -> int:
        return sum(width + 2 * PADDING for width in self.widths[:self.fixed])

    def action_column(self, direction: int) -> None:
        """Scroll sideways to bring the next (or previous) column to the left edge."""
        starts = [0]
        for width in self.widths[self.fixed:]:
            starts.append(starts[-1] + width + 2 * PADDING)
        x = round(self.scroll_target_x)
        if direction > 0:
            target = next((start for start in starts if start > x), x)
        else:
            target = max((start for start in starts if start < x), default=0)
        self.scroll_to(x=target, animate=False)

    def action_select(self) -> None:
        if self._rows:
            self.post_message(self.Selected(self, self._cursor))

    def on_click(self, event: events.Click) -> None:
        if event.y < self._header_lines:
            return
        row = int(self.scroll_offset.y) + event.y - self._header_lines
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

    def _group_line(self) -> str:
        """Group headings, each centred over its columns, between rules if there is room."""
        parts = []
        index = 0
        for start, end in groups(self.columns):
            parts.append(" " * sum(width + 2 * PADDING for width in self.widths[index:start]))
            inner = sum(width + 2 * PADDING for width in self.widths[start:end]) - 2
            group = self.columns[start].group
            label = f" {group} " if cell_len(group) + 2 <= inner else fit(group, inner)
            fill = inner - cell_len(label)
            rule = "─" if fill >= 2 else " "
            parts.append(" " + rule * (fill // 2) + label + rule * (fill - fill // 2) + " ")
            index = end
        parts.append(" " * sum(width + 2 * PADDING for width in self.widths[index:]))
        return "".join(parts)

    def render_line(self, y: int) -> Strip:
        scroll_x, scroll_y = self.scroll_offset
        width = self.scrollable_content_region.width
        if y < self._header_lines:
            style = self.get_component_rich_style("log-table--header")
            if y < self._header_lines - 1:
                text = self._group_line()
            else:
                text = self._line([column.heading(width)
                                   for column, width in zip(self.columns, self.widths)])
        else:
            index = scroll_y + y - self._header_lines
            if index >= len(self._rows):
                return Strip.blank(width, self.rich_style)
            style = self._row_style(index)
            text = self._line(self._rows[index])
        strip = Strip([Segment(text, style)], cell_len(text))
        fixed = self._fixed_width()
        if scroll_x and 0 < fixed < width:  # keep the fixed columns, scroll the others
            start = fixed + scroll_x
            strip = Strip.join([strip.crop(0, fixed), strip.crop(start, start + width - fixed)])
            return strip.crop_extend(0, width, style)
        return strip.crop_extend(scroll_x, scroll_x + width, style)

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
