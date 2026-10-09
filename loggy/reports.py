"""Rich renderables for the Totals and Currency tabs."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Sequence

from rich import box
from rich.color import Color, ColorParseError
from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from .models import Flight
from .stats import (
    ANY_AIRCRAFT,
    ROLES,
    RULES,
    Currency,
    RequirementStatus,
    Totals,
    currency_status,
    experience,
    last_flight,
    period_totals,
    totals_by_type,
    totals_by_year,
    window_start,
)
from .timeutil import format_duration

WARN_DAYS = 14  # flag currency that runs out within this many days


@dataclass(frozen=True)
class Palette:
    ok: str = "green"
    warn: str = "yellow"
    bad: str = "red"
    accent: str = "cyan"

    @classmethod
    def from_theme(cls, variables: dict[str, str]) -> Palette:
        """Pick readable status colours from the app's theme variables."""

        def colour(name: str, fallback: str) -> str:
            value = variables.get(name, "")
            try:
                Color.parse(value)
            except ColorParseError:
                return fallback
            return value

        return cls(
            ok=colour("text-success", "green"),
            warn=colour("text-warning", "yellow"),
            bad=colour("text-error", "red"),
            accent=colour("text-primary", "cyan"),
        )


def _heading(text: str, palette: Palette, note: str = "") -> Text:
    heading = Text.assemble((text, f"bold {palette.accent}"))
    if note:
        heading.append(f"   {note}", style="dim")
    return heading


def _plural(count: int, noun: str, plural: str = "") -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {plural or noun + 's'}"


def _days(count: int) -> str:
    return "1 day" if count == 1 else f"{count} days"


def _ago(day: dt.date, today: dt.date) -> str:
    delta = (today - day).days
    if delta == 0:
        return "today"
    if delta == 1:
        return "yesterday"
    if delta < 0:
        return f"in {_days(-delta)}"
    return f"{_days(delta)} ago"


# -- totals ---------------------------------------------------------------------------------

_BREAKDOWN_COLUMNS = (
    ("pic", "PIC"),
    ("picus", "PICUS"),
    ("copilot", "Co-pilot"),
    ("dual", "Dual"),
    ("instructor", "Instr."),
    ("night", "Night"),
    ("ifr", "IFR"),
    ("actual_inst", "Actual"),
    ("sim_inst", "Hood"),
    ("xc", "XC"),
    ("sim", "Sim"),
)


_TYPE_COLUMNS = ("pic", "picus", "copilot", "dual", "instructor", "night", "ifr", "sim")


def _breakdown(
    first_header: str,
    rows: Sequence[tuple[str, Totals, str]],
    fmt: str,
    last_header: str = "",
    columns: Sequence[str] = (),
) -> Table:
    """A table of totals with a column for every kind of time actually logged."""
    shown = [(name, header) for name, header in _BREAKDOWN_COLUMNS
             if (not columns or name in columns) and any(totals[name] for _, totals, _ in rows)]
    table = Table(box=box.SIMPLE_HEAD, pad_edge=False, show_edge=False, header_style="bold")
    table.add_column(first_header, no_wrap=True)
    table.add_column("Flights", justify="right", no_wrap=True)
    table.add_column("Total", justify="right", no_wrap=True, style="bold")
    for _, header in shown:
        table.add_column(header, justify="right", no_wrap=True)
    table.add_column("Landings", justify="right", no_wrap=True)
    if last_header:
        table.add_column(last_header, no_wrap=True)
    for label, totals, last in rows:
        cells = [
            label,
            str(totals.flights) if totals.flights else "",
            format_duration(totals["total"], fmt),
            *(format_duration(totals[name], fmt, blank_zero=True) for name, _ in shown),
            str(totals.landings) if totals.landings else "",
        ]
        if last_header:
            cells.append(last)
        table.add_row(*cells)
    return table


def _grand_totals(totals: Totals, fmt: str) -> Table:
    groups = (
        (("Total time", "total"), ("Single-pilot SE", "se"), ("Single-pilot ME", "me"),
         ("Multi-pilot", "multi_pilot"), ("Simulator", "sim")),
        (("PIC", "pic"), ("PICUS", "picus"), ("Co-pilot", "copilot"),
         ("Dual received", "dual"), ("Instructor", "instructor")),
        (("Night", "night"), ("IFR", "ifr"), ("Actual instrument", "actual_inst"),
         ("Simulated instrument", "sim_inst"), ("Cross-country", "xc")),
    )
    table = Table(box=None, show_header=False, pad_edge=False, padding=(0, 1))
    for _ in groups:
        table.add_column(no_wrap=True)
        table.add_column(justify="right", no_wrap=True, min_width=8)
        table.add_column(width=2)
    for index in range(max(len(group) for group in groups)):
        cells: list[RenderableType] = []
        for group in groups:
            if index < len(group):
                label, name = group[index]
                value = totals[name]
                style = "bold" if name == "total" else ("dim" if not value else "")
                cells += [Text(label, style="dim" if not value else ""),
                          Text(format_duration(value, fmt), style=style), ""]
            else:
                cells += ["", "", ""]
        table.add_row(*cells)
    return table


def _by_role(entries: Sequence[Flight], fmt: str) -> RenderableType:
    """Day and night time by role, single- and multi-engine, as SA and Indian logbooks add up."""
    summary = experience(entries)
    engines = summary.has_engines()
    table = Table(box=box.SIMPLE_HEAD, pad_edge=False, show_edge=False, header_style="bold")
    table.add_column("Role", no_wrap=True)
    headers = (("SE day", "SE night", "ME day", "ME night") if engines else ()) + (
        "Day", "Night", "Total")
    for header in headers:
        table.add_column(header, justify="right", no_wrap=True)

    def cells(role: str) -> list[str]:
        values = []
        if engines:
            for engine in ("se", "me"):
                values += [summary[(role, engine, "day")], summary[(role, engine, "night")]]
        day, night = summary[(role, "all", "day")], summary[(role, "all", "night")]
        values += [day, night, day + night]
        return [format_duration(value, fmt, blank_zero=True) for value in values]

    for role, label in ROLES:
        if summary[(role, "all", "day")] or summary[(role, "all", "night")]:
            table.add_row(label, *cells(role))
    table.add_row(*(Text(cell, style="bold") for cell in ["Flight time", *cells("total")]))

    notes = []
    if summary.xc_pic:
        notes.append(f"Cross-country as PIC: {format_duration(summary.xc_pic, fmt)}.")
    if not engines:
        notes.append("Fill in SP SE, SP ME or Multi-pilot on your flights to split this into "
                     "single- and multi-engine time.")
    elif summary.unclassified:
        notes.append(f"{format_duration(summary.unclassified, fmt)} of flight time is not marked "
                     "SP SE, SP ME or Multi-pilot, so it is only in the Day, Night and Total "
                     "columns.")
    if summary.brought_forward:
        notes.append("Brought-forward totals are left out: they have no day and night split by "
                     "role.")
    if summary.sim_sessions:
        notes.append("Simulator sessions are left out: they are not flight time.")
    parts: list[RenderableType] = [table]
    if notes:
        parts.append(Padding(Text("\n".join(notes), style="dim"), (1, 0, 0, 0)))
    return Group(*parts)


def totals_report(entries: Sequence[Flight], today: dt.date, fmt: str, palette: Palette
                  ) -> RenderableType:
    if not entries:
        return Text("No flights logged yet. Totals will appear here.", style="dim")
    grand = Totals(entries)
    counts = [_plural(grand.flights, "flight")]
    if grand.sim_sessions:
        counts.append(_plural(grand.sim_sessions, "simulator session"))
    counts.append(f"{grand['ldg_day']} day + {_plural(grand['ldg_night'], 'night landing')}")
    if grand["approaches"]:
        counts.append(_plural(grand["approaches"], "approach", "approaches"))
    brought_forward = Totals(e for e in entries if e.carried_forward)
    note = ""
    if brought_forward["total"] or brought_forward["sim"]:
        note = f"includes {format_duration(brought_forward['total'], fmt)} brought forward"

    periods = period_totals(entries, today)
    types = totals_by_type(entries)
    years = totals_by_year(entries)
    return Group(
        _heading("Grand totals", palette, note),
        Padding(_grand_totals(grand, fmt), (1, 0, 0, 2)),
        Padding(Text(" · ".join(counts), style="dim"), (1, 0, 1, 2)),
        _heading("Day and night by role", palette, "SE = SP SE; ME = SP ME + multi-pilot"),
        Padding(_by_role(entries, fmt), (1, 0, 1, 2)),
        _heading("Recent", palette, "rolling periods for flight-time limits"),
        Padding(_breakdown("Period", [(label, t, "") for label, t in periods], fmt), (1, 0, 1, 2)),
        _heading("By aircraft type", palette),
        Padding(
            _breakdown(
                "Type",
                [(t.aircraft_type, t.totals, t.last_date.isoformat() if t.last_date else "")
                 for t in types],
                fmt,
                last_header="Last flown",
                columns=_TYPE_COLUMNS,
            ),
            (1, 0, 1, 2),
        ),
        _heading("By year", palette),
        Padding(_breakdown("Year", [(label, t, "") for label, t in years], fmt), (1, 0, 0, 2)),
    )


# -- currency -----------------------------------------------------------------------------


def _status(currency: Currency, palette: Palette) -> Text:
    """CURRENT (amber when it runs out soon) or how many more are needed."""
    if currency.current:
        days = currency.days_left or 0
        return Text("CURRENT", style=f"bold {palette.warn if days <= WARN_DAYS else palette.ok}")
    return Text(f"NEED {currency.needed}", style=f"bold {palette.bad}")


def _until(currency: Currency) -> Text:
    if currency.current:
        days = currency.days_left or 0
        left = "last day" if days == 0 else f"{days} d"
        return Text.assemble(str(currency.valid_until), (f" ({left})", "dim"))
    if currency.valid_until:
        return Text(f"lapsed {currency.valid_until}", style="dim")
    return Text("never met", style="dim")


_COUNT_HEADERS = {"landings": "Landings", "night_landings": "Night ldg", "approaches": "Approaches"}


def _requirement(status: RequirementStatus, today: dt.date, palette: Palette) -> RenderableType:
    """One requirement: what it asks for, who asks for it, and how each aircraft stands."""
    requirement = status.requirement
    sources = Text()
    for index, (authority, reference) in enumerate(status.sources):
        if index:
            sources.append("\n")
        sources.append(f"{authority}: ", style="bold")
        sources.append(reference)
    description = Group(
        Text.assemble((f"{requirement.title}  ", f"bold {palette.accent}"), requirement.text),
        Padding(sources, (0, 0, 0, 2), style="dim"),
    )
    if not requirement.per_type:
        [row] = status.rows
        since = window_start(requirement, today)
        line = Text.assemble(
            f"{_COUNT_HEADERS[requirement.measure]} since {since}: ",
            (str(row.currency.count), "bold"), "   ", _status(row.currency, palette), "   ",
            _until(row.currency),
        )
        return Group(description, Padding(line, (1, 0, 0, 2)))

    table = Table(box=box.SIMPLE_HEAD, pad_edge=False, show_edge=False, header_style="bold")
    table.add_column("Aircraft", no_wrap=True)
    table.add_column("Last flown", no_wrap=True)
    table.add_column("Status", no_wrap=True, min_width=7)
    table.add_column(_COUNT_HEADERS[requirement.measure], justify="right", no_wrap=True)
    table.add_column("Valid until", no_wrap=True, min_width=17)
    for row in status.rows:
        name = Text(row.aircraft_type, style="bold" if row.aircraft_type == ANY_AIRCRAFT else "")
        table.add_row(
            name,
            row.last_date.isoformat() if row.last_date else "",
            _status(row.currency, palette),
            str(row.currency.count),
            _until(row.currency),
        )
    return Group(description, Padding(table, (1, 0, 0, 2)))


def currency_report(entries: Sequence[Flight], today: dt.date, rule_keys: Sequence[str],
                    palette: Palette) -> RenderableType:
    statuses = currency_status(entries, today, rule_keys)
    if not statuses:
        return Text("No flights logged yet. Your currency will appear here.", style="dim")

    authorities = " and ".join(RULES[key].name for key in rule_keys)
    parts: list[RenderableType] = [
        _heading("Currency", palette, f"{authorities}, as of {today} UTC"),
        Text(""),
    ]
    for status in statuses:
        parts += [Padding(_requirement(status, today, palette), (0, 0, 1, 2))]
    parts.append(Padding(
        Text("Take-offs are counted as equal to landings. Loggy is a record-keeping aid: check "
             "the current regulations for your licence and aircraft.", style="dim"),
        (0, 0, 1, 2),
    ))

    last = last_flight(entries)
    if last:
        route = "-".join(code for code in (last.dep, last.arr) if code)
        details = "  ".join(part for part in (last.aircraft_type, last.registration, route) if part)
        parts += [
            _heading("Last flight", palette),
            Padding(Text.assemble((f"{last.date}", "bold"), f" ({_ago(last.date, today)})   ",
                                  details), (1, 0, 0, 2)),
        ]
    return Group(*parts)
