"""The flight entry form."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional, Sequence

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.suggester import SuggestFromList
from textual.validation import ValidationResult, Validator
from textual.widgets import Button, Checkbox, Input, Label, Static

from .models import (
    CLOCK_FIELDS,
    CODE_FIELDS,
    COUNT_FIELDS,
    DURATION_FIELDS,
    LABELS,
    SUB_DURATION_FIELDS,
    TEXT_FIELDS,
    Flight,
    validate,
)
from .timeutil import (
    DECIMAL,
    block_minutes,
    format_duration,
    parse_clock,
    parse_count,
    parse_date,
    parse_duration,
)

# Times that vary from flight to flight, so a new flight never copies them.
CONDITION_FIELDS = ("night", "actual_inst", "sim_inst")

# Section, then (field, label, kind, width) for each input on that row.
LAYOUT = (
    ("Flight", (
        ("date", "Date (UTC)", "date", 12),
        ("aircraft_type", "Aircraft type", "code", 14),
        ("registration", "Registration", "code", 13),
        ("pic_name", "PIC name", "name", 21),
        ("flight_no", "Flight no.", "code", 11),
    )),
    ("Route", (
        ("dep", "From", "code", 8),
        ("out_time", "Off block", "clock", 10),
        ("arr", "To", "code", 8),
        ("in_time", "On block", "clock", 10),
        ("total", "Total time", "duration", 11),
    )),
    ("Time", (
        ("se", "SP SE", "duration", 8),
        ("me", "SP ME", "duration", 8),
        ("multi_pilot", "Multi-pilot", "duration", 12),
        ("pic", "PIC", "duration", 8),
        ("copilot", "Co-pilot", "duration", 9),
        ("dual", "Dual", "duration", 8),
        ("instructor", "Instructor", "duration", 11),
    )),
    ("Conditions", (
        ("night", "Night", "duration", 8),
        ("ifr", "IFR", "duration", 8),
        ("actual_inst", "Actual inst.", "duration", 13),
        ("sim_inst", "Sim. inst.", "duration", 11),
        ("xc", "X-country", "duration", 10),
        ("sim", "Simulator", "duration", 10),
    )),
    ("Landings", (
        ("ldg_day", "Day", "count", 7),
        ("ldg_night", "Night", "count", 7),
        ("approaches", "Approaches", "count", 11),
    )),
)
FIELD_NAMES = ("date", *TEXT_FIELDS, *CLOCK_FIELDS, *DURATION_FIELDS, *COUNT_FIELDS)
HELP = "Type = in a time box to copy the total · → accepts a suggestion · Enter moves on"


@dataclass
class FormContext:
    """What the form knows about earlier flights, for suggestions."""

    airports: list[str] = field(default_factory=list)
    types: list[str] = field(default_factory=list)
    registrations: list[str] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    type_for_registration: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_entries(cls, entries: Sequence[Flight]) -> FormContext:
        newest = sorted(entries, key=lambda e: e.sort_key, reverse=True)

        def unique(values: Iterable[str]) -> list[str]:
            return list(dict.fromkeys(value for value in values if value))

        context = cls(
            airports=unique(code for e in newest for code in (e.arr, e.dep)),
            types=unique(e.aircraft_type for e in newest),
            registrations=unique(e.registration for e in newest),
            names=unique(e.pic_name for e in newest),
        )
        for entry in newest:
            if entry.registration and entry.aircraft_type:
                context.type_for_registration.setdefault(entry.registration, entry.aircraft_type)
        return context


class FieldError(ValueError):
    def __init__(self, field_name: str, message: str) -> None:
        super().__init__(message)
        self.field = field_name


# -- turning flights into form values and back --------------------------------------------


def blank_values(today: dt.date) -> dict[str, str]:
    values = dict.fromkeys(FIELD_NAMES, "")
    values["date"] = today.isoformat()
    return values


def values_from_flight(entry: Flight, fmt: str) -> dict[str, str]:
    values = {"date": entry.date.isoformat()}
    for name in TEXT_FIELDS + CLOCK_FIELDS:
        values[name] = getattr(entry, name)
    for name in DURATION_FIELDS:
        values[name] = format_duration(getattr(entry, name), fmt, blank_zero=True)
    for name in COUNT_FIELDS:
        count = getattr(entry, name)
        values[name] = str(count) if count else ""
    return values


def follow_fields(entry: Flight, *, include_conditions: bool) -> set[str]:
    """The time fields that were equal to the whole flight time."""
    if not entry.total:
        return set()
    return {
        name
        for name in SUB_DURATION_FIELDS
        if getattr(entry, name) == entry.total
        and (include_conditions or name not in CONDITION_FIELDS)
    }


def next_flight_values(last: Flight | None, today: dt.date) -> tuple[dict[str, str], set[str]]:
    """Values for a new flight that carries on from the last one."""
    values = blank_values(today)
    if last is None:
        return values, set()
    values.update(
        aircraft_type=last.aircraft_type,
        registration=last.registration,
        pic_name=last.pic_name,
        dep=last.arr,
    )
    return values, follow_fields(last, include_conditions=False)


def copy_flight_values(source: Flight, today: dt.date) -> tuple[dict[str, str], set[str]]:
    """Values for a new flight like ``source`` (same aircraft and route), dated today."""
    values = blank_values(today)
    values.update(
        aircraft_type=source.aircraft_type,
        registration=source.registration,
        pic_name=source.pic_name,
        flight_no=source.flight_no,
        dep=source.dep,
        arr=source.arr,
    )
    return values, follow_fields(source, include_conditions=False)


def flight_from_values(values: dict[str, str], today: dt.date) -> Flight:
    def parse(name: str, parser: Callable[[str], object]):
        try:
            return parser(values.get(name, ""))
        except ValueError as error:
            raise FieldError(name, f"{LABELS[name]}: {error}") from None

    entry = Flight(date=parse("date", lambda value: parse_date(value, today)))
    for name in TEXT_FIELDS:
        text = " ".join(values.get(name, "").split())
        setattr(entry, name, text.upper() if name in CODE_FIELDS else text)
    for name in CLOCK_FIELDS:
        setattr(entry, name, parse(name, parse_clock))
    for name in DURATION_FIELDS:
        setattr(entry, name, parse(name, parse_duration))
    for name in COUNT_FIELDS:
        setattr(entry, name, parse(name, parse_count))
    return entry


# -- widgets -------------------------------------------------------------------------------


class _Parses(Validator):
    """Valid when ``parse`` accepts the value."""

    def __init__(self, parse: Callable[[str], object]) -> None:
        super().__init__()
        self._parse = parse

    def validate(self, value: str) -> ValidationResult:
        try:
            self._parse(value)
        except ValueError as error:
            return self.failure(str(error))
        return self.success()


class FlightForm(ModalScreen[Optional[Flight]]):
    """Add or edit one logbook entry.

    Off-block and on-block times fill in the total. Typing ``=`` in a time
    box copies the total into it, and any box equal to the total keeps
    following it when the total changes.
    """

    DEFAULT_CSS = """
    FlightForm {
        align: center middle;
    }
    FlightForm #form {
        width: 96;
        max-width: 100%;
        height: auto;
        max-height: 100%;
        background: $panel;
        border: round $primary;
        border-title-style: bold;
        border-subtitle-color: $text-muted;
        padding: 1 1 0 2;
        overflow-x: auto;  /* narrow terminals scroll sideways to the focused box */
        scrollbar-size-vertical: 1;
    }
    FlightForm .row {
        width: auto;
        height: auto;
        margin-bottom: 1;
    }
    FlightForm .section {
        width: 11;
        padding-top: 1;
        color: $text-primary;
        text-style: bold;
    }
    FlightForm .field {
        height: 2;
        margin-right: 1;
    }
    FlightForm .field.gap {
        margin: 0 1 0 2;
    }
    FlightForm .field > Label {
        color: $text-muted;
    }
    FlightForm #remarks-field {
        width: 78;
        margin-right: 1;
    }
    FlightForm Input {
        background: $surface;
    }
    FlightForm Input:focus {
        background: $primary 35%;
    }
    FlightForm #carried-forward {
        background: transparent;
    }
    FlightForm #message {
        height: 1;
        color: $text-error;
        text-style: bold;
    }
    FlightForm #message.-info {
        color: $text-muted;
        text-style: none;
    }
    FlightForm #buttons {
        height: auto;
        align-horizontal: right;
        margin: 1 0;
    }
    FlightForm #buttons Button {
        margin-left: 2;
        min-width: 12;
    }
    """

    BINDINGS = [
        Binding("ctrl+s", "save", "Save", priority=True),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        *,
        title: str,
        values: dict[str, str],
        follow: Iterable[str] = (),
        flight_id: int | None = None,
        carried_forward: bool = False,
        context: FormContext | None = None,
        fmt: str,
        today: dt.date,
        on_save: Callable[[Flight], None],
    ) -> None:
        super().__init__()
        self._title = title
        self._values = {**dict.fromkeys(FIELD_NAMES, ""), **values}
        self._follow = set(follow)
        self._flight_id = flight_id
        self._carried_forward = carried_forward
        self._suggestions = context or FormContext()
        self._fmt = fmt
        self._today = today
        self._on_save = on_save
        self._inputs: dict[str, Input] = {}
        self._type_touched = False
        self._initial: dict[str, object] = {}
        self._message_field: str | None = None

    # -- building ------------------------------------------------------------------------

    def _make_input(self, name: str, kind: str) -> Input:
        options: dict = {}
        if kind == "date":
            options.update(placeholder="YYYY-MM-DD",
                           validators=[_Parses(lambda v: parse_date(v, self._today))])
        elif kind == "clock":
            options.update(placeholder="HHMM", restrict=r"[0-9:zZ]*", max_length=6,
                           validators=[_Parses(parse_clock)])
        elif kind == "duration":
            options.update(restrict=r"[0-9:.,=]*", max_length=8,
                           validators=[_Parses(lambda v: parse_duration(v.replace("=", "")))])
            if name == "total":
                options["placeholder"] = "0.0" if self._fmt == DECIMAL else "H:MM"
        elif kind == "count":
            options.update(restrict=r"[0-9]*", max_length=6, validators=[_Parses(parse_count)])
        suggestions = {
            "dep": self._suggestions.airports,
            "arr": self._suggestions.airports,
            "aircraft_type": self._suggestions.types,
            "registration": self._suggestions.registrations,
            "pic_name": self._suggestions.names,
        }.get(name)
        if suggestions:
            options["suggester"] = SuggestFromList(suggestions, case_sensitive=False)
        widget = Input(
            name=name,
            id=f"f-{name}",
            compact=True,
            validate_on=["blur"],
            **options,
        )
        self._inputs[name] = widget
        return widget

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="form", can_focus=False) as form:
            form.border_title = self._title
            form.border_subtitle = "Ctrl+S save · Esc cancel"
            for section, fields in LAYOUT:
                with Horizontal(classes="row"):
                    yield Label(section, classes="section")
                    for name, label, kind, width in fields:
                        with Vertical(classes="field gap" if name == "pic" else "field") as box:
                            box.styles.width = width
                            yield Label(label)
                            yield self._make_input(name, kind)
            with Horizontal(classes="row"):
                yield Label("Remarks", classes="section")
                with Vertical(classes="field", id="remarks-field"):
                    yield Label("Remarks and endorsements")
                    yield self._make_input("remarks", "text")
            with Horizontal(classes="row"):
                yield Label("", classes="section")
                yield Checkbox(
                    "Brought forward: totals carried over from a previous logbook",
                    value=self._carried_forward,
                    id="carried-forward",
                    compact=True,
                )
            yield Static(HELP, id="message", classes="-info")
            with Horizontal(id="buttons"):
                yield Button("Save", variant="primary", id="save", compact=True)
                yield Button("Cancel", id="cancel", compact=True)

    def on_mount(self) -> None:
        # Fill the boxes here, quietly: only the user's own typing should trigger the
        # automatic behaviour (an edited flight must keep a total that differs from its
        # block time, for example).
        with self.prevent(Input.Changed):
            for name, widget in self._inputs.items():
                widget.value = self._values[name]
        self._initial = self._snapshot()
        self.call_after_refresh(self._focus_date)

    def _focus_date(self) -> None:
        # Select the date so that typing replaces it, as for every other box.
        date = self._inputs["date"]
        date.focus()
        date.select_all()

    def _snapshot(self) -> dict[str, object]:
        snapshot: dict[str, object] = {name: widget.value for name, widget in self._inputs.items()}
        snapshot["carried_forward"] = self.query_one("#carried-forward", Checkbox).value
        return snapshot

    # -- live behaviour ------------------------------------------------------------------

    def _set(self, name: str, value: str) -> None:
        """Change a box without it counting as the user's edit."""
        widget = self._inputs[name]
        if widget.value == value:
            return
        with self.prevent(Input.Changed):
            widget.value = value
        if widget.has_focus:
            widget.cursor_position = len(value)
        if widget.has_class("-invalid"):
            widget.validate(value)

    def _total(self) -> int | None:
        try:
            return parse_duration(self._inputs["total"].value)
        except ValueError:
            return None

    def _show(self, message: str, *, field_name: str | None = None) -> None:
        """Show an error under the form (or the help line when ``message`` is blank)."""
        widget = self.query_one("#message", Static)
        widget.update(message or HELP)
        widget.set_class(not message, "-info")
        self._message_field = field_name if message else None

    @on(Input.Changed)
    def _changed(self, event: Input.Changed) -> None:
        widget = event.input
        name = widget.name
        if name not in self._inputs:
            return
        value = widget.value  # the event's copy may be stale if typing is fast
        if name in CODE_FIELDS and value != value.upper():
            position = widget.cursor_position
            with self.prevent(Input.Changed):
                widget.value = value.upper()
            widget.cursor_position = position
            value = widget.value
        if widget.has_class("-invalid"):
            result = widget.validate(value)
            if (result is None or result.is_valid) and self._message_field == name:
                self._show("")

        if name in CLOCK_FIELDS:
            self._total_from_times()
        elif name == "total":
            self._apply_total()
        elif name in SUB_DURATION_FIELDS:
            self._track_follow(name, value)
        elif name == "registration":
            self._fill_type(value)
        elif name == "aircraft_type":
            self._type_touched = True

    def _total_from_times(self) -> None:
        try:
            out_time = parse_clock(self._inputs["out_time"].value)
            in_time = parse_clock(self._inputs["in_time"].value)
        except ValueError:
            return
        if out_time and in_time:
            self._set("total", format_duration(block_minutes(out_time, in_time), self._fmt))
            self._apply_total()

    def _apply_total(self) -> None:
        total = self._total()
        if total is None:
            return
        text = format_duration(total, self._fmt, blank_zero=True)
        for name in self._follow:
            self._set(name, text)

    def _track_follow(self, name: str, value: str) -> None:
        total = self._total() or 0
        if "=" in value:
            self._set(name, format_duration(total, self._fmt, blank_zero=True))
            self._follow.add(name)
            return
        try:
            minutes = parse_duration(value)
        except ValueError:
            minutes = None
        if minutes and minutes == total:
            self._follow.add(name)
        else:
            self._follow.discard(name)

    def _fill_type(self, registration: str) -> None:
        if self._type_touched:
            return
        known = self._suggestions.type_for_registration.get(registration.strip())
        if known:
            self._set("aircraft_type", known)

    @on(Input.Blurred)
    def _blurred(self, event: Input.Blurred) -> None:
        """Tidy what was typed (``930`` becomes ``09:30``) or say what is wrong."""
        widget = event.input
        name = widget.name
        if name not in self._inputs:
            return
        value = widget.value
        try:
            if name == "date":
                normal = parse_date(value, self._today).isoformat() if value.strip() else ""
            elif name in CLOCK_FIELDS:
                normal = parse_clock(value)
            elif name in DURATION_FIELDS:
                normal = format_duration(parse_duration(value), self._fmt, blank_zero=True)
            elif name in COUNT_FIELDS:
                count = parse_count(value)
                normal = str(count) if count else ""
            else:
                normal = value.strip()
        except ValueError as error:
            self._show(f"{LABELS[name]}: {error}", field_name=name)
            return
        if self._message_field == name:
            self._show("")
        self._set(name, normal)

    @on(Input.Submitted)
    def _submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.focus_next()

    # -- saving --------------------------------------------------------------------------

    def _fail(self, field_name: str, message: str) -> None:
        self._show(message, field_name=field_name)
        widget = self._inputs.get(field_name)
        if widget is not None:
            widget.add_class("-invalid")
            widget.focus()

    def action_save(self) -> None:
        values = {name: widget.value for name, widget in self._inputs.items()}
        try:
            entry = flight_from_values(values, self._today)
        except FieldError as error:
            self._fail(error.field, str(error))
            return
        entry.id = self._flight_id
        entry.carried_forward = self.query_one("#carried-forward", Checkbox).value
        problems = validate(entry, self._today)
        if problems:
            self._fail(*problems[0])
            return
        try:
            self._on_save(entry)
        except Exception as error:  # a failed write must not lose what was typed
            self._show(f"Could not save: {error}")
            return
        self.dismiss(entry)

    def action_cancel(self) -> None:
        if self._snapshot() == self._initial:
            self.dismiss(None)
            return
        from .dialogs import ConfirmDialog

        def answer(discard: bool | None) -> None:
            if discard:
                self.dismiss(None)

        self.app.push_screen(
            ConfirmDialog("Discard the changes to this flight?", confirm="Discard",
                          cancel="Keep editing", danger=True),
            answer,
        )

    @on(Button.Pressed, "#save")
    def _save_pressed(self) -> None:
        self.action_save()

    @on(Button.Pressed, "#cancel")
    def _cancel_pressed(self) -> None:
        self.action_cancel()
