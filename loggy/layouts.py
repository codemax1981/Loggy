"""Logbook layouts: the South African (SACAA) logbook and Loggy's standard one.

The SACAA logbook records flight time in a grid of sixteen columns, (14) to (29):
single- or multi-engine, by day or night, as dual, PIC, PICUS or co-pilot. Loggy
stores a flight as its role times, its engine class and its night time; this
module converts between the two. A flight with a single role (nearly every
flight) converts exactly both ways. ``grid_is_exact`` spots the rare grid that
cannot be stored as one entry, such as dual by day and PIC at night.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from .models import Flight
from .timeutil import format_duration

SACAA = "sacaa"
STANDARD = "standard"
LAYOUTS = {SACAA: "SACAA (South Africa)", STANDARD: "Standard"}

ENGINES = (("se", "SE"), ("me", "ME"))
PERIODS = (("day", "day"), ("night", "night"))
GRID_ROLES = (("dual", "Dual"), ("pic", "PIC"), ("picus", "PICUS"), ("copilot", "Co-pilot"))
# Roles that are crew of a multi-pilot aircraft when flown in a multi-engine aircraft.
CREW_ROLES = ("picus", "copilot")


def cell_name(engine: str, period: str, role: str) -> str:
    return f"{engine}_{period}_{role}"


GRID = tuple(
    (engine, period, role)
    for engine, _ in ENGINES
    for period, _ in PERIODS
    for role, _ in GRID_ROLES
)
GRID_NAMES = tuple(cell_name(*cell) for cell in GRID)
GRID_LABELS = {
    cell_name(engine, period, role): f"{engine_label} {period} {role_label.lower()}"
    for engine, engine_label in ENGINES
    for period, _ in PERIODS
    for role, role_label in GRID_ROLES
}


def engine_of(entry: Flight) -> str:
    """ "se" or "me", or "" when the flight is not marked with either."""
    multi_engine = entry.me + entry.multi_pilot
    if entry.se and entry.se >= multi_engine:
        return "se"
    return "me" if multi_engine else ""


def grid(entry: Flight) -> dict[str, int]:
    """Minutes in each of the SACAA columns (14) to (29) for one entry.

    Simulator sessions have none: their time goes in the FSTD column.
    """
    cells = dict.fromkeys(GRID_NAMES, 0)
    if not entry.total:
        return cells
    engine = engine_of(entry) or "se"
    for role, _ in GRID_ROLES:
        minutes = getattr(entry, role)
        if minutes:
            night = min(minutes, entry.night)
            cells[cell_name(engine, "day", role)] += minutes - night
            cells[cell_name(engine, "night", role)] += night
    return cells


def apply_grid(entry: Flight, cells: dict[str, int], *, multi_pilot: bool = False) -> None:
    """Set the role, engine, night and total times of ``entry`` from the grid.

    Multi-engine PICUS and co-pilot time is multi-pilot time. So is multi-engine dual and
    PIC time in a ``multi_pilot`` aircraft (an airliner's captain, say); otherwise it is
    single-pilot ME time.
    """
    for role, _ in GRID_ROLES:
        setattr(entry, role, sum(
            cells.get(cell_name(engine, period, role), 0)
            for engine, _ in ENGINES for period, _ in PERIODS
        ))
    entry.se = sum(cells.get(name, 0) for name in GRID_NAMES if name.startswith("se_"))
    crew = single = 0
    for period, _ in PERIODS:
        for role, _ in GRID_ROLES:
            minutes = cells.get(cell_name("me", period, role), 0)
            if role in CREW_ROLES or multi_pilot:
                crew += minutes
            else:
                single += minutes
    entry.me, entry.multi_pilot = single, crew
    entry.night = sum(cells.get(name, 0) for name in GRID_NAMES if "_night_" in name)
    entry.total = sum(cells.get(name, 0) for name in GRID_NAMES)


def grid_is_exact(cells: dict[str, int]) -> bool:
    """Whether ``cells`` can be stored as one entry and read back unchanged."""
    if sum(1 for name in GRID_NAMES if cells.get(name)) == 0:
        return True
    probe = Flight(date=dt.date.min)
    apply_grid(probe, cells)
    return grid(probe) == {name: cells.get(name, 0) for name in GRID_NAMES}


_BLANK_GRID = dict.fromkeys(GRID_NAMES, "")
# The times that the grid is made from, and so can show.
GRID_FIELDS = ("total", "se", "me", "multi_pilot", "dual", "pic", "picus", "copilot", "night")
_SHORT_LABELS = {"total": "Total", "se": "SE", "me": "ME", "multi_pilot": "Multi-pilot",
                 "dual": "Dual", "pic": "PIC", "picus": "PICUS", "copilot": "Co-pilot",
                 "night": "Night"}


def fits_grid(entry: Flight) -> bool:
    """Whether the grid shows every one of ``entry``'s times exactly, so that it can be
    edited there. Brought-forward totals that mix engine classes, or flights with no role
    or engine class, do not fit.

    This is ``apply_grid(grid(entry))`` giving back the same times, worked out directly
    because the logbook table asks it of every entry.
    """
    roles = (entry.dual, entry.pic, entry.picus, entry.copilot)
    if entry.total != sum(roles):
        return False
    if not entry.total:
        return not (entry.se or entry.me or entry.multi_pilot or entry.night)
    night = entry.night
    if night and sum(min(minutes, night) for minutes in roles) != night:
        return False  # night time in more than one role, but not the whole flight
    if engine_of(entry) == "me":  # all single-pilot but the crew roles, or all multi-pilot
        crew = entry.picus + entry.copilot
        return not entry.se and (entry.me == entry.total - crew and entry.multi_pilot == crew
                                 or not entry.me and entry.multi_pilot == entry.total)
    return entry.se == entry.total and not entry.me and not entry.multi_pilot


# -- table columns ------------------------------------------------------------------------


@dataclass(frozen=True)
class LayoutColumn:
    key: str
    label: str
    group: str = ""
    right: bool = False
    always: bool = False  # shown even when every row is empty
    short: str = ""  # the heading when the column is too narrow for ``label``


SACAA_COLUMNS = (
    LayoutColumn("date", "Date", always=True),
    LayoutColumn("aircraft_type", "Type", always=True),
    LayoutColumn("registration", "Registration", always=True, short="Reg."),
    LayoutColumn("pic_name", "Pilot in command", always=True, short="PIC"),
    LayoutColumn("remarks", "Details of flight and remarks", always=True, short="Details"),
    LayoutColumn("navaids", "Navaids", "Instrument"),
    LayoutColumn("place", "Place", "Instrument"),
    LayoutColumn("actual_inst", "Actual", "Instrument", right=True),
    LayoutColumn("inst_fstd", "FSTD", "Instrument", right=True),
    LayoutColumn("instructor_se", "SE", "Instructor", right=True),
    LayoutColumn("instructor_me", "ME", "Instructor", right=True),
    LayoutColumn("instructor_fstd", "FSTD", "Instructor", right=True),
    LayoutColumn("sim", "FSTD", right=True),
    *(
        LayoutColumn(
            cell_name(engine, period, role), role_label, f"{engine_label} {period_label}",
            right=True, always=cell_name(engine, period, role) in ("se_day_dual", "se_day_pic"),
        )
        for engine, engine_label in ENGINES
        for period, period_label in PERIODS
        for role, role_label in GRID_ROLES
    ),
    LayoutColumn("ldg_day", "Day", "Landings", right=True, always=True),
    LayoutColumn("ldg_night", "Night", "Landings", right=True, always=True),
)
SACAA_FLEX = "remarks"  # the column that takes up whatever width is left


def sacaa_values(entry: Flight, fmt: str) -> dict[str, str]:
    """The SACAA logbook columns for one entry, as text."""

    def time(minutes: int) -> str:
        return format_duration(minutes, fmt, blank_zero=True)

    simulator = not entry.total and bool(entry.sim)
    engine = engine_of(entry) or "se"
    fits = fits_grid(entry)
    route = "-".join(code for code in (entry.dep, entry.arr) if code)
    details = "  ".join(part for part in (entry.flight_no, route, entry.remarks) if part)
    if entry.carried_forward:
        details = f"Brought forward{': ' + details if details else ''}"
    if not fits:  # say what the times are, as the grid cannot
        times = " · ".join(f"{_SHORT_LABELS[name]} {time(getattr(entry, name))}"
                           for name in GRID_FIELDS if getattr(entry, name))
        details = "  ".join(part for part in (details, f"[{times}]") if part)
    values = {
        "date": entry.date.isoformat(),
        "aircraft_type": entry.aircraft_type,
        "registration": entry.registration,
        "pic_name": entry.pic_name,
        "remarks": details,
        "navaids": entry.navaids,
        "place": entry.place,
        "actual_inst": time(entry.actual_inst),
        "inst_fstd": time(entry.sim_inst),  # as typed in the form's FSTD box
        "instructor_se": time(entry.instructor) if not simulator and engine == "se" else "",
        "instructor_me": time(entry.instructor) if not simulator and engine == "me" else "",
        "instructor_fstd": time(entry.instructor) if simulator else "",
        "sim": time(entry.sim),
        "ldg_day": str(entry.ldg_day) if entry.ldg_day else "",
        "ldg_night": str(entry.ldg_night) if entry.ldg_night else "",
    }
    values.update(_BLANK_GRID)
    if fits:
        for name, minutes in grid(entry).items():
            if minutes:
                values[name] = time(minutes)
    return values
