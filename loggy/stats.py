"""Totals and recency (currency) calculations."""

from __future__ import annotations

import datetime as dt
import operator
from dataclasses import dataclass
from typing import Iterable, Sequence

from .models import COUNT_FIELDS, DURATION_FIELDS, Flight
from .timeutil import add_months, end_of_month, months_before

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
        ("Last 6 months", months_before(today, 6) + dt.timedelta(days=1), today),
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


ROLES = (
    ("dual", "Dual"),
    ("pic", "PIC"),
    ("picus", "PICUS"),
    ("copilot", "Co-pilot"),
    ("instructor", "Instructor"),
)
ENGINES = ("se", "me", "all")


@dataclass
class Experience:
    """Day and night time by role and engine class, as South African and Indian logbooks
    add it up.

    Single-engine time is "SP SE"; multi-engine is "SP ME" plus multi-pilot time.
    Night time is counted against each role up to that role's time, which is exact
    whenever a flight has one role (nearly always).
    """

    time: dict[tuple[str, str, str], int]  # (role or "total", engine, "day"/"night")
    unclassified: int = 0  # flight time marked neither SE, ME nor multi-pilot
    xc_pic: int = 0  # cross-country time as PIC
    brought_forward: int = 0  # brought-forward lines, which cannot be split like this
    sim_sessions: int = 0  # simulator sessions, which are not flight time

    def __getitem__(self, key: tuple[str, str, str]) -> int:
        return self.time.get(key, 0)

    def has_engines(self) -> bool:
        return any(self[("total", engine, part)] for engine in ("se", "me")
                   for part in ("day", "night"))


_ROLE_TIMES = ("total",) + tuple(role for role, _ in ROLES)
_ROLE_VALUES = operator.attrgetter(*_ROLE_TIMES)


def experience(entries: Sequence[Flight]) -> Experience:
    result = Experience(time={})
    # sums[role][engine] is [day, night], with engines in ENGINES order: se, me, all.
    sums = [[[0, 0] for _ in ENGINES] for _ in _ROLE_TIMES]
    for entry in entries:
        if entry.carried_forward:
            result.brought_forward += 1
            continue
        if not entry.total:
            result.sim_sessions += bool(entry.sim)
            continue
        multi_engine = entry.me + entry.multi_pilot
        if entry.se and entry.se >= multi_engine:
            engine = 0
        elif multi_engine:
            engine = 1
        else:
            engine = -1
            result.unclassified += entry.total
        night_time = entry.night
        for role_sums, minutes in zip(sums, _ROLE_VALUES(entry)):
            if not minutes:
                continue
            night = min(minutes, night_time)
            role_sums[2][0] += minutes - night
            role_sums[2][1] += night
            if engine >= 0:
                role_sums[engine][0] += minutes - night
                role_sums[engine][1] += night
        result.xc_pic += min(entry.xc, entry.pic)
    for role, role_sums in zip(_ROLE_TIMES, sums):
        for engine, (day, night) in zip(ENGINES, role_sums):
            if day or night:
                result.time[(role, engine, "day")] = day
                result.time[(role, engine, "night")] = night
    return result


def last_flight(entries: Sequence[Flight]) -> Flight | None:
    real = [e for e in logged(entries) if e.total]
    return max(real, key=lambda e: e.sort_key) if real else None


# -- currency ---------------------------------------------------------------------------

_MEASURES = {
    "landings": lambda entry: entry.landings,
    "night_landings": lambda entry: entry.ldg_night,
    "approaches": lambda entry: entry.approaches,
}


@dataclass(frozen=True)
class Requirement:
    """Something that must have been done recently, such as 3 landings in 90 days."""

    title: str  # "Day", "Night" or "Instrument"
    text: str  # what is needed, in words
    measure: str  # what is counted: a key of _MEASURES
    required: int
    days: int = 0  # counted over a rolling window of this many days,
    months: int = 0  # or of this many calendar months
    per_type: bool = True  # checked separately for each aircraft type


DAY_3_IN_90 = Requirement(
    "Day", "3 take-offs and landings in the last 90 days, by day or night", "landings", 3, days=90
)
NIGHT_1_IN_90 = Requirement(
    "Night", "1 take-off and landing at night in the last 90 days", "night_landings", 1, days=90
)
NIGHT_3_IN_90 = Requirement(
    "Night", "3 take-offs and landings at night in the last 90 days", "night_landings", 3,
    days=90,
)
APPROACHES_2_IN_90 = Requirement(
    "Instrument", "2 instrument approaches in the last 90 days, in an aircraft or an approved "
    "simulator", "approaches", 2, days=90, per_type=False,
)
APPROACHES_6_IN_6_MONTHS = Requirement(
    "Instrument", "6 instrument approaches in the last 6 calendar months", "approaches", 6,
    months=6, per_type=False,
)


@dataclass(frozen=True)
class Rules:
    key: str
    name: str
    requirements: tuple[tuple[Requirement, str], ...]  # each with the regulation it comes from


RULES = {
    "sacaa": Rules("sacaa", "SACAA (South Africa)", (
        (DAY_3_IN_90, "CAR 91.02.4(1), in the same class or type"),
        (NIGHT_3_IN_90, "CAR 91.02.4(2), in the same class or type"),
        (APPROACHES_2_IN_90, "CAR 91.02.4(4), to fly an approach in IMC (a skill test also "
                             "counts)"),
    )),
    "dgca": Rules("dgca", "DGCA (India)", (
        (DAY_3_IN_90, "CAR Section 8 Series F Part I, on the same type or an approved simulator "
                      "(multi-pilot or 5,700 kg+ aeroplanes)"),
    )),
    "easa": Rules("easa", "EASA / ICAO", (
        (DAY_3_IN_90, "FCL.060(b)(1), in the same type or class"),
        (NIGHT_1_IN_90, "FCL.060(b)(2), if you have no instrument rating"),
    )),
    "faa": Rules("faa", "FAA", (
        (DAY_3_IN_90, "14 CFR 61.57(a), in the same category and class"),
        (NIGHT_3_IN_90, "14 CFR 61.57(b), to a full stop"),
        (APPROACHES_6_IN_6_MONTHS, "14 CFR 61.57(c), plus holding and tracking"),
    )),
}
DEFAULT_RULES = ("sacaa", "dgca")


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


def window_start(requirement: Requirement, as_of: dt.date) -> dt.date:
    """The first day that counts towards ``requirement`` on ``as_of``."""
    if requirement.days:
        return as_of - dt.timedelta(days=requirement.days)
    return add_months(as_of, -requirement.months)


def _lapses(requirement: Requirement, day: dt.date) -> dt.date:
    """The last day on which something done on ``day`` still counts."""
    if requirement.days:
        return day + dt.timedelta(days=requirement.days)
    return end_of_month(add_months(day, requirement.months))


def _newest_first(entries: Iterable[Flight], as_of: dt.date) -> list[Flight]:
    return sorted(
        (e for e in logged(entries) if e.date <= as_of), key=lambda e: e.sort_key, reverse=True
    )


def check(requirement: Requirement, newest: Sequence[Flight], as_of: dt.date) -> Currency:
    """How ``requirement`` stands, given entries sorted newest first.

    It stays met until the window has passed the entry that completed it,
    counting back from the most recent.
    """
    value = _MEASURES[requirement.measure]
    start = window_start(requirement, as_of)
    count = 0
    accumulated = 0
    valid_until = None
    for entry in newest:
        amount = value(entry)
        if not amount:
            continue
        if entry.date >= start:
            count += amount
        if valid_until is None:
            accumulated += amount
            if accumulated >= requirement.required:
                valid_until = _lapses(requirement, entry.date)
    return Currency(requirement.required, count, valid_until, as_of)


def landing_currency(
    entries: Iterable[Flight], as_of: dt.date, required: int, *, night: bool, days: int = 90
) -> Currency:
    """Landings (or night landings) needed within the preceding ``days`` days."""
    requirement = Requirement("", "", "night_landings" if night else "landings", required,
                              days=days)
    return check(requirement, _newest_first(entries, as_of), as_of)


def approach_currency(
    entries: Iterable[Flight], as_of: dt.date, required: int = 6, months: int = 6
) -> Currency:
    """Instrument approaches needed within the preceding ``months`` calendar months."""
    requirement = Requirement("", "", "approaches", required, months=months, per_type=False)
    return check(requirement, _newest_first(entries, as_of), as_of)


@dataclass
class CurrencyRow:
    aircraft_type: str
    last_date: dt.date | None
    currency: Currency


@dataclass
class RequirementStatus:
    requirement: Requirement
    sources: list[tuple[str, str]]  # (authority, regulation) that ask for it
    rows: list[CurrencyRow]  # any aircraft first, then each type when checked per type


def currency_status(
    entries: Sequence[Flight], as_of: dt.date, rule_keys: Sequence[str]
) -> list[RequirementStatus]:
    """Every requirement of the chosen authorities, with identical ones merged."""
    newest = _newest_first(entries, as_of)  # sorted once; each group keeps the order
    if not newest:
        return []
    groups: dict[str, list[Flight]] = {}
    for entry in newest:
        groups.setdefault(type_key(entry), []).append(entry)
    types = sorted(groups, key=lambda name: (groups[name][0].date, name), reverse=True)

    statuses: dict[Requirement, RequirementStatus] = {}
    for key in rule_keys:
        rules = RULES[key]
        for requirement, reference in rules.requirements:
            status = statuses.get(requirement)
            if status is None:
                rows = [CurrencyRow(ANY_AIRCRAFT, newest[0].date,
                                    check(requirement, newest, as_of))]
                if requirement.per_type:
                    rows += [
                        CurrencyRow(name, groups[name][0].date,
                                    check(requirement, groups[name], as_of))
                        for name in types
                    ]
                status = statuses[requirement] = RequirementStatus(requirement, [], rows)
            status.sources.append((rules.name, reference))
    return list(statuses.values())
