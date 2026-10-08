"""Totals and recency (currency) calculations."""

from __future__ import annotations

import datetime as dt
import operator
from dataclasses import dataclass
from typing import Iterable, Sequence

from .models import COUNT_FIELDS, DURATION_FIELDS, Flight
from .timeutil import add_months, end_of_month

UNSPECIFIED_TYPE = "(no type)"
BROUGHT_FORWARD = "Brought forward"
ANY_AIRCRAFT = "Any aircraft"


_SUMMED = DURATION_FIELDS + COUNT_FIELDS
_SUMMED_VALUES = operator.attrgetter(*_SUMMED)


class Totals:
    """Sums of every time and count column over a set of logbook entries."""

    def __init__(self, entries: Iterable[Flight] = ()) -> None:
        entries = list(entries)
        real = [entry for entry in entries if not entry.carried_forward]
        # Real flights; simulator sessions and brought-forward lines are counted apart.
        self.flights = sum(1 for entry in real if entry.total)
        self.sim_sessions = sum(1 for entry in real if not entry.total and entry.sim)
        columns = zip(*map(_SUMMED_VALUES, entries))
        self.values = dict(zip(_SUMMED, map(sum, columns))) or dict.fromkeys(_SUMMED, 0)

    def __getitem__(self, name: str) -> int:
        return self.values[name]

    @property
    def landings(self) -> int:
        return self.values["ldg_day"] + self.values["ldg_night"]


def logged(entries: Iterable[Flight]) -> list[Flight]:
    """Entries that are real flights or sessions, not brought-forward totals."""
    return [entry for entry in entries if not entry.carried_forward]


def period_totals(entries: Sequence[Flight], today: dt.date) -> list[tuple[str, Totals]]:
    """Rolling and calendar period totals, for flight-time limits and reviews."""
    real = logged(entries)
    periods = [
        ("Last 7 days", today - dt.timedelta(days=6), today),
        ("Last 28 days", today - dt.timedelta(days=27), today),
        ("Last 90 days", today - dt.timedelta(days=89), today),
        ("Last 365 days", today - dt.timedelta(days=364), today),
        (f"Year {today.year}", dt.date(today.year, 1, 1), today),
        (f"Year {today.year - 1}", dt.date(today.year - 1, 1, 1), dt.date(today.year - 1, 12, 31)),
    ]
    return [
        (label, Totals(e for e in real if start <= e.date <= end)) for label, start, end in periods
    ]


@dataclass
class TypeTotals:
    aircraft_type: str
    totals: Totals
    last_date: dt.date | None


def type_key(entry: Flight) -> str:
    return entry.aircraft_type.strip().upper() or UNSPECIFIED_TYPE


def totals_by_type(entries: Sequence[Flight]) -> list[TypeTotals]:
    groups: dict[str, list[Flight]] = {}
    for entry in entries:
        key = type_key(entry)
        if entry.carried_forward and key == UNSPECIFIED_TYPE:
            key = BROUGHT_FORWARD
        groups.setdefault(key, []).append(entry)
    rows = []
    for key, group in groups.items():
        dates = [entry.date for entry in group if not entry.carried_forward]
        rows.append(TypeTotals(key, Totals(group), max(dates) if dates else None))
    return sorted(rows, key=lambda row: (-row.totals["total"], row.aircraft_type))


def totals_by_year(entries: Sequence[Flight]) -> list[tuple[str, Totals]]:
    years: dict[int, list[Flight]] = {}
    for entry in logged(entries):
        years.setdefault(entry.date.year, []).append(entry)
    rows = [(str(year), Totals(years[year])) for year in sorted(years, reverse=True)]
    brought_forward = Totals(entry for entry in entries if entry.carried_forward)
    if any(brought_forward.values.values()):
        rows.append((BROUGHT_FORWARD, brought_forward))
    return rows


def last_flight(entries: Sequence[Flight]) -> Flight | None:
    real = [e for e in logged(entries) if e.total]
    return max(real, key=lambda e: e.sort_key) if real else None


# -- currency ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Rules:
    key: str
    name: str
    day_rule: str
    night_landings: int
    night_rule: str
    instrument: bool


RULES = {
    "easa": Rules(
        key="easa",
        name="EASA / ICAO",
        day_rule="3 take-offs and landings in the last 90 days (FCL.060)",
        night_landings=1,
        night_rule="1 take-off and landing at night in the last 90 days, "
        "if you have no instrument rating (FCL.060)",
        instrument=False,
    ),
    "faa": Rules(
        key="faa",
        name="FAA",
        day_rule="3 take-offs and landings in the last 90 days (14 CFR 61.57(a))",
        night_landings=3,
        night_rule="3 take-offs and full-stop landings at night in the last 90 days "
        "(14 CFR 61.57(b))",
        instrument=True,
    ),
}


@dataclass(frozen=True)
class Currency:
    required: int
    count: int  # how many were done inside the current window
    valid_until: dt.date | None  # last day the requirement is met; None if never met
    as_of: dt.date

    @property
    def current(self) -> bool:
        return self.valid_until is not None and self.valid_until >= self.as_of

    @property
    def days_left(self) -> int | None:
        return (self.valid_until - self.as_of).days if self.current else None

    @property
    def needed(self) -> int:
        return max(0, self.required - self.count)


def _newest_first(entries: Iterable[Flight], as_of: dt.date) -> list[Flight]:
    return sorted(
        (e for e in logged(entries) if e.date <= as_of), key=lambda e: e.sort_key, reverse=True
    )


def landing_currency(
    entries: Iterable[Flight], as_of: dt.date, required: int, *, night: bool, days: int = 90
) -> Currency:
    """Landings needed within the preceding ``days`` days.

    The requirement stays met until ``days`` days after the landing that
    completed it, counting back from the most recent landing.
    """
    return _landing_currency(_newest_first(entries, as_of), as_of, required, night, days)


def _landing_currency(
    newest: list[Flight], as_of: dt.date, required: int, night: bool, days: int = 90
) -> Currency:
    window_start = as_of - dt.timedelta(days=days)
    count = 0
    accumulated = 0
    valid_until = None
    for entry in newest:
        landings = entry.ldg_night if night else entry.landings
        if not landings:
            continue
        if entry.date >= window_start:
            count += landings
        if valid_until is None:
            accumulated += landings
            if accumulated >= required:
                valid_until = entry.date + dt.timedelta(days=days)
    return Currency(required, count, valid_until, as_of)


def approach_currency(
    entries: Iterable[Flight], as_of: dt.date, required: int = 6, months: int = 6
) -> Currency:
    """Instrument approaches within the preceding ``months`` calendar months.

    Approaches flown in a month keep you current to the end of the sixth
    calendar month after it.
    """
    window_start = add_months(as_of, -months)
    count = 0
    accumulated = 0
    valid_until = None
    for entry in _newest_first(entries, as_of):
        if not entry.approaches:
            continue
        if entry.date >= window_start:
            count += entry.approaches
        if valid_until is None:
            accumulated += entry.approaches
            if accumulated >= required:
                valid_until = end_of_month(add_months(entry.date, months))
    return Currency(required, count, valid_until, as_of)


@dataclass
class TypeCurrency:
    aircraft_type: str
    last_date: dt.date | None
    day: Currency
    night: Currency


def currency_by_type(
    entries: Sequence[Flight], as_of: dt.date, rules: Rules
) -> list[TypeCurrency]:
    """Passenger-carrying currency for any aircraft, then for each type flown."""
    newest = _newest_first(entries, as_of)  # sorted once; each group keeps the order
    groups: dict[str, list[Flight]] = {}
    for entry in newest:
        groups.setdefault(type_key(entry), []).append(entry)

    def row(name: str, group: list[Flight]) -> TypeCurrency:
        return TypeCurrency(
            aircraft_type=name,
            last_date=group[0].date if group else None,
            day=_landing_currency(group, as_of, 3, False),
            night=_landing_currency(group, as_of, rules.night_landings, True),
        )

    rows = [row(name, group) for name, group in groups.items()]
    rows.sort(key=lambda r: (r.last_date or dt.date.min, r.aircraft_type), reverse=True)
    return [row(ANY_AIRCRAFT, newest), *rows] if newest else []
