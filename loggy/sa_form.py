"""The flight form laid out like a South African (SACAA) logbook."""

from __future__ import annotations

import datetime as dt

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Label, Static

from .form import (
    CONDITION_FIELDS,
    FIELD_NAMES,
    FieldError,
    FlightForm,
    blank_values,
    flight_from_values,
    values_from_flight,
)
from .layouts import (
    ENGINES,
    GRID_LABELS,
    GRID_NAMES,
    GRID_ROLES,
    PERIODS,
    apply_grid,
    cell_name,
    engine_of,
    grid,
    grid_is_exact,
)
from .models import LABELS, Flight
from .timeutil import block_minutes, format_duration, parse_clock, parse_duration

# Times kept outside the grid; like the grid, they can follow the whole flight.
OTHER_TIMES = ("actual_inst", "sim_inst", "instructor", "sim", "xc")

ROWS = (
    ("Flight", (
        ("date", "Date (UTC)", "date", 12),
        ("aircraft_type", "Type", "code", 10),
        ("registration", "Registration", "code", 13),
        ("pic_name", "Pilot in command", "name", 21),
        ("flight_no", "Flight no.", "code", 11),
    )),
    ("Route", (
        ("dep", "From", "code", 8),
        ("out_time", "Off block", "clock", 10),
        ("arr", "To", "code", 8),
        ("in_time", "On block", "clock", 10),
    )),
)
LOWER_ROWS = (
    ("Instrument", (
        ("navaids", "Navaids", "code", 11),
        ("place", "Place", "code", 9),
        ("actual_inst", "Actual", "duration", 8),
        ("sim_inst", "FSTD", "duration", 8),
        ("approaches", "Approaches", "count", 11),
    )),
    ("Other", (
        ("instructor", "Instructor", "duration", 11),
        ("sim", "FSTD session", "duration", 13),
        ("xc", "X-country", "duration", 10),
        ("ldg_day", "Day ldg", "count", 9),
        ("ldg_night", "Night ldg", "count", 10),
    )),
)


def sacaa_values(entry: Flight, fmt: str) -> dict[str, str]:
    values = values_from_flight(entry, fmt)
    values.update((name, format_duration(minutes, fmt, blank_zero=True))
                  for name, minutes in grid(entry).items())
    return values


def sacaa_follow(entry: Flight, *, new: bool) -> set[str]:
    """Boxes that held the whole of ``entry``: grid boxes follow the block time, the others
    follow the flight time.

    For a ``new`` flight like ``entry``, the role's day box follows, as night is never
    assumed; nor are conditions such as instrument time.
    """
    if not entry.total:
        return set()
    if new:
        roles = [role for role, _ in GRID_ROLES if getattr(entry, role) == entry.total]
        engine = engine_of(entry) or "se"
        names = {cell_name(engine, "day", roles[0])} if len(roles) == 1 else set()
    else:
        names = {name for name, minutes in grid(entry).items() if minutes == entry.total}
    names.update(
        name for name in OTHER_TIMES
        if getattr(entry, name) == entry.total and not (new and name in CONDITION_FIELDS)
    )
    return names


def _blank(today: dt.date) -> dict[str, str]:
    return {**blank_values(today), **dict.fromkeys(GRID_NAMES, "")}


def next_sacaa_values(last: Flight | None, today: dt.date) -> tuple[dict[str, str], set[str]]:
    values = _blank(today)
    if last is None:
        return values, set()
    values.update(aircraft_type=last.aircraft_type, registration=last.registration,
                  pic_name=last.pic_name, dep=last.arr)
    return values, sacaa_follow(last, new=True)


def copy_sacaa_values(source: Flight, today: dt.date) -> tuple[dict[str, str], set[str]]:
    values = _blank(today)
    values.update(aircraft_type=source.aircraft_type, registration=source.registration,
                  pic_name=source.pic_name, flight_no=source.flight_no, dep=source.dep,
                  arr=source.arr)
    return values, sacaa_follow(source, new=True)


class SAFlightForm(FlightForm):
    """Add or edit an entry in the columns of a South African logbook.

    The flight time is the sum of the grid of columns (14) to (29). Typing ``=``
    in a grid box copies the block time; in any other time box it copies the
    flight time.
    """

    FIELDS = FIELD_NAMES + GRID_NAMES
    HELP = "Type = for the block time (grid) or flight time (other boxes) · → accepts a suggestion"

    DEFAULT_CSS = """
    SAFlightForm .grid-head, SAFlightForm .grid-row {
        height: 1;
        width: auto;
    }
    SAFlightForm .grid-row.last {
        margin-bottom: 1;
    }
    SAFlightForm .grid-head Label, SAFlightForm .grid-row Input {
        width: 9;
        margin-right: 1;
    }
    SAFlightForm .grid-head Label {
        color: $text-muted;
    }
    SAFlightForm .grid-row .section, SAFlightForm .grid-head .section {
        width: 11;
        margin-right: 0;
        padding-top: 0;
    }
    SAFlightForm .grid-row.alternate Input {
        background-tint: $foreground 7%;  /* so that each row of boxes stands apart */
    }
    SAFlightForm #flight-time, SAFlightForm #block-time {
        width: auto;
        margin-left: 2;
        color: $text-primary;
        text-style: bold;
    }
    SAFlightForm #block-time {
        padding-top: 1;
    }
    """

    def __init__(self, *, base: Flight | None = None, **options) -> None:
        super().__init__(**options)
        self._base = base  # the entry being edited, for times this layout does not show

    def _label(self, name: str) -> str:
        return GRID_LABELS.get(name) or LABELS.get(name, name)

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="form", can_focus=False) as form:
            form.border_title = self._title
            form.border_subtitle = "Ctrl+S save · Esc cancel"
            for section, fields in ROWS:
                with Horizontal(classes="row"):
                    yield Label(section, classes="section")
                    for name, label, kind, width in fields:
                        yield from self._field(name, label, kind, width)
                    if section == "Route":
                        yield Static("", id="block-time")
            with Horizontal(classes="row"):
                yield Label("Details", classes="section")
                yield from self._field("remarks", "Details of flight and remarks", "text", 78)
            with Horizontal(classes="grid-head"):
                yield Label("", classes="section")
                for _, label in GRID_ROLES:
                    yield Label(label)
                yield Static("", id="flight-time")
            rows = [(engine, period, f"{engine_label} {period_label}")
                    for engine, engine_label in ENGINES for period, period_label in PERIODS]
            for index, (engine, period, title) in enumerate(rows):
                classes = "grid-row alternate" if index % 2 else "grid-row"
                if index == len(rows) - 1:
                    classes += " last"
                with Horizontal(classes=classes):
                    yield Label(title, classes="section")
                    for role, _ in GRID_ROLES:
                        yield self._make_input(cell_name(engine, period, role), "duration")
            for section, fields in LOWER_ROWS:
                with Horizontal(classes="row"):
                    yield Label(section, classes="section")
                    for name, label, kind, width in fields:
                        yield from self._field(name, label, kind, width)
            yield from self._bottom()

    def on_mount(self) -> None:
        super().on_mount()
        self._show_times()

    # -- live behaviour ------------------------------------------------------------------

    def _block(self) -> int | None:
        try:
            out_time = parse_clock(self._inputs["out_time"].value)
            in_time = parse_clock(self._inputs["in_time"].value)
        except ValueError:
            return None
        return block_minutes(out_time, in_time) if out_time and in_time else None

    def _flight_time(self) -> int:
        total = 0
        for name in GRID_NAMES:
            try:
                total += parse_duration(self._inputs[name].value.replace("=", ""))
            except ValueError:
                pass
        return total

    def _show_times(self) -> None:
        block = self._block()
        self.query_one("#block-time", Static).update(
            f"Block time {format_duration(block, self._fmt)}" if block else "")
        total = self._flight_time()
        self.query_one("#flight-time", Static).update(
            f"Flight time {format_duration(total, self._fmt)}" if total else "")

    def _times_changed(self) -> None:
        block = self._block()
        if block is not None:
            text = format_duration(block, self._fmt, blank_zero=True)
            for name in self._follow.intersection(GRID_NAMES):
                self._set(name, text)
        self._grid_changed()

    def _duration_changed(self, name: str, value: str) -> None:
        target = self._block() if name in GRID_NAMES else self._flight_time()
        if "=" in value:
            self._set(name, format_duration(target or 0, self._fmt, blank_zero=True))
            self._follow.add(name)
        else:
            try:
                minutes = parse_duration(value)
            except ValueError:
                minutes = None
            if minutes and minutes == target:
                self._follow.add(name)
            else:
                self._follow.discard(name)
        if name in GRID_NAMES:
            self._grid_changed()
        else:
            self._show_times()

    def _grid_changed(self) -> None:
        text = format_duration(self._flight_time(), self._fmt, blank_zero=True)
        for name in self._follow.difference(GRID_NAMES):
            self._set(name, text)
        self._show_times()

    # -- saving --------------------------------------------------------------------------

    def _build_entry(self, values: dict[str, str]) -> Flight:
        entry = flight_from_values(values, self._today)
        cells = {}
        for name in GRID_NAMES:
            try:
                cells[name] = parse_duration(values.get(name, ""))
            except ValueError as error:
                raise FieldError(name, f"{self._label(name)}: {error}") from None
        if not grid_is_exact(cells):
            used = [name for name in GRID_NAMES if cells[name]]
            if {name[:2] for name in used} == {"se", "me"}:
                message = "Single-engine and multi-engine time need separate entries"
            else:
                message = ("These roles by day and by night can't share one entry: log the "
                           "night part as a separate entry")
            raise FieldError(used[-1], message)
        apply_grid(entry, cells, multi_pilot=self._multi_pilot(entry))
        if self._base is not None:
            entry.ifr = self._base.ifr  # not part of this layout, so keep what was there
        return entry

    def _multi_pilot(self, entry: Flight) -> bool:
        """Whether multi-engine dual or PIC time is multi-pilot time, which the grid does not
        say: as before for an entry that had multi-engine time, else as for the type."""
        base = self._base
        if base is not None and (base.me or base.multi_pilot):
            return not base.me
        return entry.aircraft_type in self._suggestions.multi_pilot_types

    def _problem(self, field_name: str, message: str) -> tuple[str, str]:
        if field_name in self._inputs:
            return field_name, message
        used = [name for name in GRID_NAMES if self._inputs[name].value.strip()]
        if field_name == "total" and message.startswith("Enter"):
            message = "Enter the time in the column for your role, or an FSTD session time"
        return (used[0] if used else "se_day_dual"), message
