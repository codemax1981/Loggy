"""The Loggy terminal application."""

from __future__ import annotations

import dataclasses
import datetime as dt
import operator
import sqlite3
from pathlib import Path
from typing import Callable, Sequence

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.css.query import NoMatches
from textual.timer import Timer
from textual.widgets import Footer, Header, Input, Label, Static, TabbedContent, TabPane

from .config import Settings, documents_dir
from .csvio import export_csv, import_csv, split_duplicates
from .db import Logbook
from .dialogs import (
    DIALOG_CSS,
    ConfirmDialog,
    EndorsementDialog,
    HelpScreen,
    ImportPreview,
    PathDialog,
    SettingsDialog,
)
from .form import (
    FlightForm,
    FormContext,
    copy_flight_values,
    follow_fields,
    next_flight_values,
    values_from_flight,
)
from .layouts import SACAA, SACAA_COLUMNS, SACAA_FLEX, fits_grid, sacaa_values
from .models import Endorsement, Flight
from .reports import Palette, currency_report, totals_report
from .sa_form import SAFlightForm, copy_sacaa_values, next_sacaa_values, sacaa_follow
from .sa_form import sacaa_values as sacaa_form_values
from .stats import Totals, last_flight, period_totals
from .table import PADDING, Column, LogTable, column_widths
from .timeutil import format_duration, utc_today

COLUMNS = (
    Column("Date"),
    Column("Type"),
    Column("Reg"),
    Column("From"),
    Column("Out"),
    Column("To"),
    Column("In"),
    Column("Total", right=True),
    Column("Role"),
    Column("Night", right=True),
    Column("IFR", right=True),
    Column("Ldg", right=True),
    Column("Remarks"),
)
MIN_FLEX_WIDTH = 16  # the narrowest the remarks column gets before the table scrolls
ENDORSEMENT_COLUMNS = (
    Column("Date"),
    Column("Instructor"),
    Column("Licence"),
    Column("Designation"),
    Column("ATO"),
    Column("Endorsement"),
)


def endorsement_cells(endorsement: Endorsement) -> tuple[str, ...]:
    ato = " ".join(part for part in (endorsement.ato, endorsement.ato_number) if part)
    return (endorsement.date.isoformat(), endorsement.instructor, endorsement.licence,
            endorsement.designation, ato, endorsement.text)


def row_cells(entry: Flight, fmt: str) -> tuple[str, ...]:
    """The logbook table cells for one entry."""
    if entry.carried_forward:
        role = "B/F"
    elif not entry.total and entry.sim:
        role = "SIM"  # a simulator session shows its session time as the total
    else:
        role = entry.role
    total = entry.total if entry.total or not entry.sim else entry.sim
    return (
        entry.date.isoformat(),
        entry.aircraft_type,
        entry.registration,
        entry.dep,
        entry.out_time,
        entry.arr,
        entry.in_time,
        format_duration(total, fmt, blank_zero=True),
        role,
        format_duration(entry.night, fmt, blank_zero=True),
        format_duration(entry.ifr, fmt, blank_zero=True),
        f"{entry.ldg_day}/{entry.ldg_night}" if entry.landings else "",
        entry.remarks,
    )


def describe(entry: Flight) -> str:
    route = "-".join(code for code in (entry.dep, entry.arr) if code)
    parts = (entry.date.isoformat(), entry.aircraft_type, entry.registration, route)
    return "  ".join(part for part in parts if part)


def describe_endorsement(endorsement: Endorsement) -> str:
    text = endorsement.text if len(endorsement.text) <= 60 else endorsement.text[:59] + "…"
    parts = (endorsement.date.isoformat(), endorsement.instructor, text)
    return "  ".join(part for part in parts if part)


class LoggyApp(App[None]):
    TITLE = "Loggy"
    SUB_TITLE = "Pilot logbook"

    CSS = DIALOG_CSS + """
    Screen {
        background: $background;
    }
    TabbedContent {
        height: 1fr;
    }
    TabPane {
        padding: 0;
    }
    #search-bar {
        height: 1;
        margin: 1 1 0 1;
    }
    #search-bar Label {
        color: $text-muted;
        width: auto;
        margin-right: 1;
    }
    #search {
        width: 1fr;
        background: $surface;
    }
    #search:focus {
        background: $primary 30%;
    }
    #flights {
        height: 1fr;
        margin-top: 1;
        scrollbar-size-vertical: 1;
    }
    #endorsement-table {
        height: 1fr;
        scrollbar-size-vertical: 1;
    }
    #endorsement-text {
        height: auto;
        max-height: 6;
        padding: 0 1;
        border-top: solid $panel-lighten-2;
    }
    .empty {
        display: none;
        padding: 2 4;
        color: $text-muted;
    }
    .empty.-shown {
        display: block;
    }
    .report {
        padding: 1 2;
    }
    TabPane VerticalScroll {
        scrollbar-size-vertical: 1;
    }
    #status-bar {
        height: 1;
        background: $panel;
        color: $text-muted;
        padding: 0 1;
    }
    #status {
        width: 1fr;
    }
    #clock {
        width: auto;
        padding-left: 2;
        color: $text;
        text-style: bold;
    }
    """

    BINDINGS = [
        Binding("a", "add", "Add"),
        Binding("e", "edit", "Edit"),
        Binding("c", "copy", "Copy"),
        Binding("d,delete", "delete", "Delete"),
        Binding("slash", "search", "Search"),
        Binding("x", "export", "Export"),
        Binding("i", "import_csv", "Import"),
        Binding("s", "settings", "Settings"),
        Binding("question_mark,f1", "help", "Help"),
        Binding("q", "quit", "Quit"),
        Binding("escape", "clear_search", "Clear search", show=False),
        Binding("1", "show_tab('logbook')", "Logbook", show=False),
        Binding("2", "show_tab('totals')", "Totals", show=False),
        Binding("3", "show_tab('currency')", "Currency", show=False),
        Binding("4", "show_tab('endorsements')", "Endorsements", show=False),
    ]

    def __init__(
        self,
        logbook: Logbook,
        settings: Settings | None = None,
        settings_path: Path | None = None,
        *,
        today: Callable[[], dt.date] = utc_today,
        backup_dir: Path | None = None,
    ) -> None:
        super().__init__()
        self.logbook = logbook
        self.settings = settings or Settings()
        self.settings_path = settings_path
        self.backup_dir = backup_dir
        self._today = today
        self.entries: list[Flight] = []
        self.endorsements: list[Endorsement] = []
        self._shown: list[Flight] = []
        self._shown_endorsements: list[Endorsement] = []
        # The logbook table's columns for the layout, each entry's cells (by id of the
        # entry) and the index of the column that takes up the width that is left.
        self._columns: tuple[Column, ...] = COLUMNS
        self._cells: dict[int, tuple[str, ...]] = {}
        self._flex = len(COLUMNS) - 1
        self._terms: list[str] = []
        self._search_texts: dict[int, str] | None = None
        self._form_context = FormContext()
        self._search_timer: Timer | None = None
        self._resize_timer: Timer | None = None
        self._table_widths: dict[str, int] = {}  # the width each table was laid out for
        self._clock_text = ""
        self._report_day: dt.date | None = None

    @property
    def today(self) -> dt.date:
        return self._today()

    @property
    def fmt(self) -> str:
        return self.settings.time_format

    @property
    def sacaa(self) -> bool:
        """Whether the logbook is laid out like a South African one."""
        return self.settings.layout == SACAA

    # -- layout --------------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="logbook"):
            with TabPane("Logbook", id="logbook"):
                with Horizontal(id="search-bar"):
                    yield Label("Search")
                    yield Input(
                        placeholder="press / then type an airport, registration, type, "
                        "name or remark",
                        id="search",
                        compact=True,
                    )
                yield LogTable(COLUMNS, fixed=3, id="flights")  # date, type and registration
                yield Static(id="empty", classes="empty")
            with TabPane("Totals", id="totals"):
                with VerticalScroll(id="totals-scroll"):
                    yield Static(id="totals-report", classes="report")
            with TabPane("Currency", id="currency"):
                with VerticalScroll(id="currency-scroll"):
                    yield Static(id="currency-report", classes="report")
            with TabPane("Endorsements", id="endorsements"):
                yield LogTable(ENDORSEMENT_COLUMNS, id="endorsement-table")
                yield Static(id="endorsement-text")
                yield Static(id="no-endorsements", classes="empty")
        with Horizontal(id="status-bar"):
            yield Static(id="status")
            yield Static(id="clock")
        yield Footer()

    def on_mount(self) -> None:
        if self.settings.theme in self.available_themes:
            self.theme = self.settings.theme
        self.theme_changed_signal.subscribe(self, self._theme_changed)
        self.reload()
        self._focus_table()
        self.call_after_refresh(self._relayout_tables)  # once the real table width is known
        self._tick()
        self.set_interval(1, self._tick)

    # -- data ----------------------------------------------------------------------------

    def reload(self, select: int | None = None) -> None:
        """Re-read the logbook and refresh every view."""
        self.entries = self.logbook.flights()
        self._search_texts = None
        self._build_rows()
        self._form_context = FormContext.from_entries(self.entries)
        self._refresh_table(select)
        self._refresh_reports()
        self.reload_endorsements()

    def _build_rows(self) -> None:
        """Work out the logbook table's columns, and every entry's cells, for the layout."""
        if not self.sacaa:
            self._columns, self._flex = COLUMNS, len(COLUMNS) - 1
            self._cells = {id(entry): row_cells(entry, self.fmt) for entry in self.entries}
            return
        values = [sacaa_values(entry, self.fmt) for entry in self.entries]
        # Like the paper logbook, but without the columns this logbook never uses.
        shown = [column for column in SACAA_COLUMNS
                 if column.always or any(map(operator.itemgetter(column.key), values))]
        keys = [column.key for column in shown]
        self._columns = tuple(Column(column.label, column.right, column.group, column.short)
                              for column in shown)
        self._flex = keys.index(SACAA_FLEX)
        cells = operator.itemgetter(*keys)
        self._cells = {id(entry): cells(row) for entry, row in zip(self.entries, values)}

    def _matches(self, entry: Flight) -> bool:
        if not self._terms:
            return True
        if self._search_texts is None:
            self._search_texts = {id(e): e.search_text() for e in self.entries}
        text = self._search_texts[id(entry)]
        return all(term in text for term in self._terms)

    def _refresh_table(self, select: int | None = None) -> None:
        table = self.query_one("#flights", LogTable)
        if select is None:
            current = self._selected()
            select = current.id if current else None
        previous_row = table.cursor_row
        self._shown = [entry for entry in reversed(self.entries) if self._matches(entry)]
        rows = [self._cells[id(entry)] for entry in self._shown]
        ids = [entry.id for entry in self._shown]
        cursor = ids.index(select) if select in ids else min(previous_row, len(ids) - 1)
        table.set_rows(
            rows,
            self._column_widths(table, self._columns, rows, self._flex),
            muted=[entry.carried_forward for entry in self._shown],
            cursor=max(cursor, 0),
            columns=self._columns,
        )

        empty = self.query_one("#empty", Static)
        if not self.entries:
            empty.update(
                "Your logbook is empty.\n\n"
                "Press [b]a[/b] to add your first flight, or [b]i[/b] to import a CSV file "
                "from a spreadsheet or another logbook app.\n"
                "Carrying on from a paper logbook? Add one entry with your totals so far and "
                "tick 'Brought forward'.\n\n"
                "Press [b]?[/b] for help."
            )
        else:
            empty.update("No entries match your search. Press Esc to clear it.")
        empty.set_class(not self._shown, "-shown")
        table.display = bool(self._shown)
        self._refresh_status()
        self.refresh_bindings()

    def _column_widths(self, table: LogTable, columns: Sequence[Column],
                       rows: Sequence[Sequence[str]], flex: int) -> list[int]:
        """Size every column to its contents and give the ``flex`` column (the remarks)
        whatever width is left."""
        widths = column_widths(columns, rows)
        available = (table.size.width or self.size.width) - table.styles.scrollbar_size_vertical
        used = sum(width + 2 * PADDING for index, width in enumerate(widths) if index != flex)
        widths[flex] = min(widths[flex], max(MIN_FLEX_WIDTH, available - used - 2 * PADDING))
        self._table_widths[table.id or ""] = available
        return widths

    def on_resize(self) -> None:
        if self._resize_timer is not None:
            self._resize_timer.stop()
        self._resize_timer = self.set_timer(0.2, self._relayout_tables)

    def _relayout_tables(self) -> None:
        for table_id, refresh in (("flights", self._refresh_table),
                                  ("endorsement-table", self._refresh_endorsements)):
            try:
                table = self.query_one(f"#{table_id}", LogTable)
            except NoMatches:  # the app is closing
                return
            width = table.size.width - table.styles.scrollbar_size_vertical
            if width > 0 and width != self._table_widths.get(table_id):
                refresh()

    # -- endorsements --------------------------------------------------------------------

    def reload_endorsements(self, select: int | None = None) -> None:
        self.endorsements = self.logbook.endorsements()
        self._refresh_endorsements(select)

    def _refresh_endorsements(self, select: int | None = None) -> None:
        table = self.query_one("#endorsement-table", LogTable)
        if select is None:
            current = self._selected_endorsement()
            select = current.id if current else None
        previous_row = table.cursor_row
        self._shown_endorsements = list(reversed(self.endorsements))  # newest first
        rows = [endorsement_cells(endorsement) for endorsement in self._shown_endorsements]
        ids = [endorsement.id for endorsement in self._shown_endorsements]
        cursor = ids.index(select) if select in ids else min(previous_row, len(ids) - 1)
        widths = self._column_widths(table, ENDORSEMENT_COLUMNS, rows,
                                     len(ENDORSEMENT_COLUMNS) - 1)
        table.set_rows(rows, widths, cursor=max(cursor, 0))
        empty = self.query_one("#no-endorsements", Static)
        empty.update(
            "No endorsements yet.\n\n"
            "Press [b]a[/b] on this tab to copy one in from your logbook: solo, "
            "navigation and dual-check endorsements, skills tests and ratings, with the "
            "instructor's name, licence number and grade."
        )
        empty.set_class(not rows, "-shown")
        table.display = bool(rows)
        self._show_endorsement()
        self.refresh_bindings()

    def _show_endorsement(self) -> None:
        """The whole wording of the highlighted endorsement, which the table may cut short."""
        endorsement = self._selected_endorsement()
        detail = self.query_one("#endorsement-text", Static)
        detail.display = endorsement is not None
        if endorsement is not None:
            detail.update(Text(endorsement.text))

    def _refresh_reports(self) -> None:
        today = self.today
        self._report_day = today
        palette = Palette.from_theme(self.get_css_variables())
        self.query_one("#totals-report", Static).update(
            totals_report(self.entries, today, self.fmt, palette)
        )
        self.query_one("#currency-report", Static).update(
            currency_report(self.entries, today, self.settings.rules, palette)
        )

    def _refresh_status(self) -> None:
        status = self.query_one("#status", Static)
        if not self.entries:
            status.update("No flights yet")
            return
        if self._terms:
            shown = Totals(self._shown)
            status.update(
                f"{len(self._shown)} of {len(self.entries)} entries match · "
                f"{format_duration(shown['total'], self.fmt)} flight time"
            )
            return
        totals = Totals(self.entries)
        periods = dict(period_totals(self.entries, self.today))
        status.update(
            f"{totals.flights} flights · {format_duration(totals['total'], self.fmt)} total · "
            f"last 28 days {format_duration(periods['Last 28 days']['total'], self.fmt)} · "
            f"last 365 days {format_duration(periods['Last 365 days']['total'], self.fmt)}"
        )

    def _tick(self) -> None:
        now = dt.datetime.now(dt.timezone.utc)
        text = now.strftime("%H:%M UTC  %d %b %Y")
        if text != self._clock_text:
            self._clock_text = text
            self.query_one("#clock", Static).update(text)
        if self._report_day is not None and self.today != self._report_day:
            self._refresh_reports()  # currency moves on at midnight UTC
            self._refresh_status()

    def _theme_changed(self, theme) -> None:
        if self.settings.theme != theme.name:
            self.settings.theme = theme.name
            self._save_settings()
        self._refresh_reports()

    def _save_settings(self) -> None:
        if self.settings_path is None:
            return
        try:
            self.settings.save(self.settings_path)
        except OSError as error:
            self.notify(f"Could not save settings: {error}", severity="error")

    # -- selection -----------------------------------------------------------------------

    def _active_tab(self) -> str:
        try:
            return self.query_one(TabbedContent).active
        except NoMatches:  # not composed yet
            return ""

    def _selected(self) -> Flight | None:
        try:
            table = self.query_one("#flights", LogTable)
        except NoMatches:
            return None
        row = table.cursor_row
        return self._shown[row] if 0 <= row < len(self._shown) else None

    def _selected_endorsement(self) -> Endorsement | None:
        try:
            table = self.query_one("#endorsement-table", LogTable)
        except NoMatches:
            return None
        row = table.cursor_row
        shown = self._shown_endorsements
        return shown[row] if 0 <= row < len(shown) else None

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in ("edit", "copy", "delete"):
            tab = self._active_tab()
            if tab == "logbook":
                return True if self._selected() else None
            if tab == "endorsements":
                return True if self._selected_endorsement() else None
            return False
        if action in ("search", "clear_search"):
            return self._active_tab() == "logbook"
        return True

    @on(TabbedContent.TabActivated)
    def _tab_changed(self) -> None:
        self.refresh_bindings()
        tab = self._active_tab()
        if tab == "logbook":
            self._focus_table()
        elif tab == "endorsements":
            table = self.query_one("#endorsement-table", LogTable)
            if table.display:
                table.focus()
        else:  # so the arrow and page keys scroll the report straight away
            self.query_one(f"#{tab}-scroll", VerticalScroll).focus()

    @on(LogTable.Highlighted)
    def _row_highlighted(self, event: LogTable.Highlighted) -> None:
        if event.table.id == "endorsement-table":
            self._show_endorsement()
        self.refresh_bindings()

    @on(LogTable.Selected)
    def _row_selected(self) -> None:
        self.action_edit()  # of a flight or an endorsement, whichever tab is showing

    # -- search --------------------------------------------------------------------------

    def action_search(self) -> None:
        self.query_one("#search", Input).focus()

    @on(Input.Changed, "#search")
    def _search_changed(self) -> None:
        if self._search_timer is not None:
            self._search_timer.stop()
        self._search_timer = self.set_timer(0.15, self._apply_search)

    def _apply_search(self) -> None:
        text = self.query_one("#search", Input).value
        terms = text.casefold().split()
        if terms != self._terms:
            self._terms = terms
            self._refresh_table()

    @on(Input.Submitted, "#search")
    def _search_submitted(self) -> None:
        self._apply_search()
        self._focus_table()

    def action_clear_search(self) -> None:
        search = self.query_one("#search", Input)
        search.value = ""
        self._apply_search()
        self._focus_table()

    def _focus_table(self) -> None:
        table = self.query_one("#flights", LogTable)
        if table.display:
            table.focus()

    def action_show_tab(self, tab: str) -> None:
        self.query_one(TabbedContent).active = tab

    # -- adding and editing --------------------------------------------------------------

    def _open_form(self, title: str, values: dict[str, str], follow: set[str], *,
                   base: Flight | None = None, sacaa: bool = False) -> None:
        """Open the flight form; ``base`` is the entry being edited, if any."""
        flight_id = base.id if base is not None else None

        def closed(saved: Flight | None) -> None:
            if saved is not None:
                self.reload(select=saved.id)
                self._focus_table()
                self.notify("Flight updated" if flight_id else "Flight added", timeout=3)

        options = dict(
            title=title,
            values=values,
            follow=follow,
            flight_id=flight_id,
            carried_forward=base.carried_forward if base is not None else False,
            context=self._form_context,
            fmt=self.fmt,
            today=self.today,
            on_save=self._save_entry,
        )
        form = SAFlightForm(base=base, **options) if sacaa else FlightForm(**options)
        self.push_screen(form, closed)

    def _save_entry(self, entry: Flight) -> None:
        if entry.id is None:
            self.logbook.add(entry)
        else:
            self.logbook.update(entry)

    def action_add(self) -> None:
        if self._active_tab() == "endorsements":
            self._open_endorsement("New endorsement", Endorsement(self.today))
            return
        last = last_flight(self.entries)
        if self.sacaa:
            values, follow = next_sacaa_values(last, self.today)
        else:
            values, follow = next_flight_values(last, self.today)
        self._open_form("New flight", values, follow, sacaa=self.sacaa)

    def action_copy(self) -> None:
        if self._active_tab() == "endorsements":
            source = self._selected_endorsement()
            if source is not None:  # the same instructor, for a new endorsement
                copy = dataclasses.replace(source, date=self.today, text="", id=None)
                by = f" by {source.instructor}" if source.instructor else ""
                self._open_endorsement(f"New endorsement{by}", copy)
            return
        entry = self._selected()
        if entry is not None:
            make = copy_sacaa_values if self.sacaa else copy_flight_values
            values, follow = make(entry, self.today)
            self._open_form(f"New flight like {describe(entry)}", values, follow,
                            sacaa=self.sacaa)

    def action_edit(self) -> None:
        if self._active_tab() == "endorsements":
            endorsement = self._selected_endorsement()
            if endorsement is not None:
                self._open_endorsement(f"Edit {describe_endorsement(endorsement)}", endorsement)
            return
        entry = self._selected()
        if entry is None:
            return
        # An entry the SACAA columns cannot show exactly, such as brought-forward totals
        # that mix engine classes, is edited field by field so that nothing is lost.
        if self.sacaa and fits_grid(entry):
            values, follow = sacaa_form_values(entry, self.fmt), sacaa_follow(entry, new=False)
            sacaa = True
        else:
            values = values_from_flight(entry, self.fmt)
            follow, sacaa = follow_fields(entry, include_conditions=True), False
        self._open_form(f"Edit {describe(entry)}", values, follow, base=entry, sacaa=sacaa)

    def action_delete(self) -> None:
        if self._active_tab() == "endorsements":
            self._delete_endorsement()
            return
        entry = self._selected()
        if entry is None or entry.id is None:
            return
        flight_id = entry.id

        def answer(confirmed: bool | None) -> None:
            if not confirmed:
                return
            try:
                self.logbook.delete(flight_id)
            except sqlite3.Error as error:
                self.notify(f"Could not delete: {error}", severity="error")
                return
            self.reload()
            self.notify("Entry deleted", timeout=3)

        self.push_screen(
            ConfirmDialog(f"Delete this entry?\n\n  {describe(entry)}", confirm="Delete",
                          danger=True),
            answer,
        )

    def _open_endorsement(self, title: str, endorsement: Endorsement) -> None:
        def save(changed: Endorsement) -> None:
            if changed.id is None:
                self.logbook.add_endorsement(changed)
            else:
                self.logbook.update_endorsement(changed)

        def closed(saved: Endorsement | None) -> None:
            if saved is not None:
                self.reload_endorsements(select=saved.id)
                self.query_one("#endorsement-table", LogTable).focus()
                self.notify("Endorsement updated" if endorsement.id else "Endorsement added",
                            timeout=3)

        self.push_screen(EndorsementDialog(title, endorsement, self.today, save), closed)

    def _delete_endorsement(self) -> None:
        endorsement = self._selected_endorsement()
        if endorsement is None or endorsement.id is None:
            return
        endorsement_id = endorsement.id

        def answer(confirmed: bool | None) -> None:
            if not confirmed:
                return
            try:
                self.logbook.delete_endorsement(endorsement_id)
            except sqlite3.Error as error:
                self.notify(f"Could not delete: {error}", severity="error")
                return
            self.reload_endorsements()
            self.notify("Endorsement deleted", timeout=3)

        self.push_screen(
            ConfirmDialog(f"Delete this endorsement?\n\n  {describe_endorsement(endorsement)}",
                          confirm="Delete", danger=True),
            answer,
        )

    # -- import, export and settings -----------------------------------------------------

    def action_export(self) -> None:
        default = documents_dir() / f"logbook-{self.today.isoformat()}.csv"

        def chosen(path: Path | None) -> None:
            if path is None:
                return
            try:
                count = export_csv(self.entries, path, self.fmt)
            except OSError as error:
                self.notify(f"Could not export: {error}", severity="error", timeout=10)
                return
            self.notify(f"Exported {count} entries to {path}", timeout=8)

        self.push_screen(
            PathDialog(
                title="Export to CSV",
                prompt="Save the whole logbook as a CSV file, which Excel and other "
                "logbook apps can open.",
                default=default,
                action="Export",
                must_exist=False,
            ),
            chosen,
        )

    def action_import_csv(self) -> None:
        def chosen(path: Path | None) -> None:
            if path is None:
                return
            try:
                result = import_csv(path, self.today)
            except OSError as error:
                self.notify(f"Could not read {path}: {error}", severity="error", timeout=10)
                return
            fresh, duplicates = split_duplicates(result.flights, self.entries)

            def confirmed(go: bool | None) -> None:
                if not go:
                    return
                try:
                    self.logbook.add_many(fresh)
                except sqlite3.Error as error:
                    self.notify(f"Import failed, nothing was added: {error}", severity="error")
                    return
                self.reload()
                self._focus_table()
                self.notify(f"Imported {len(fresh)} entries", timeout=5)

            self.push_screen(ImportPreview(path, result, fresh, duplicates), confirmed)

        self.push_screen(
            PathDialog(
                title="Import from CSV",
                prompt="Enter the CSV file to import. Loggy recognises most column names "
                "and shows you what it found before adding anything.",
                default=documents_dir() / "logbook.csv",
                action="Preview",
                must_exist=True,
            ),
            chosen,
        )

    def action_settings(self) -> None:
        files = [("Logbook", self.logbook.path)]
        if self.backup_dir is not None:
            files.append(("Daily backups", self.backup_dir))
        if self.settings_path is not None:
            files.append(("Settings", self.settings_path))

        def closed(settings: Settings | None) -> None:
            if settings is None:
                return
            self.settings = settings
            self._save_settings()
            self.reload()

        self.push_screen(SettingsDialog(self.settings, files), closed)

    def action_help(self) -> None:
        self.push_screen(HelpScreen())


def run(logbook: Logbook, settings: Settings, settings_path: Path, backup_dir: Path) -> None:
    LoggyApp(logbook, settings, settings_path, backup_dir=backup_dir).run()

