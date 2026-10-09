"""The flight record and the rules that keep it consistent."""

from __future__ import annotations

import dataclasses
import datetime as dt
from dataclasses import dataclass

from .timeutil import MINUTES_PER_DAY

# Time columns, stored as whole minutes. "total" is the flight (block) time;
# "sim" is FSTD/simulator session time, which is never flight time.
DURATION_FIELDS = (
    "total",
    "se",
    "me",
    "multi_pilot",
    "pic",
    "picus",
    "copilot",
    "dual",
    "instructor",
    "night",
    "ifr",
    "actual_inst",
    "sim_inst",
    "xc",
    "sim",
)
# Times that are a part of the total and so can never exceed it.
SUB_DURATION_FIELDS = tuple(name for name in DURATION_FIELDS if name not in ("total", "sim"))
COUNT_FIELDS = ("ldg_day", "ldg_night", "approaches")
CLOCK_FIELDS = ("out_time", "in_time")
# Text fields that are conventionally written in capitals.
CODE_FIELDS = ("flight_no", "aircraft_type", "registration", "dep", "arr")
TEXT_FIELDS = CODE_FIELDS + ("pic_name", "remarks")

LABELS = {
    "date": "Date",
    "flight_no": "Flight no.",
    "aircraft_type": "Aircraft type",
    "registration": "Registration",
    "dep": "From",
    "arr": "To",
    "out_time": "Off block",
    "in_time": "On block",
    "total": "Total time",
    "pic_name": "PIC name",
    "se": "Single-pilot SE",
    "me": "Single-pilot ME",
    "multi_pilot": "Multi-pilot",
    "pic": "PIC",
    "picus": "PICUS",
    "copilot": "Co-pilot",
    "dual": "Dual",
    "instructor": "Instructor",
    "night": "Night",
    "ifr": "IFR",
    "actual_inst": "Actual instrument",
    "sim_inst": "Simulated instrument",
    "xc": "Cross-country",
    "sim": "Simulator (FSTD)",
    "ldg_day": "Day landings",
    "ldg_night": "Night landings",
    "approaches": "Approaches",
    "remarks": "Remarks",
    "carried_forward": "Brought forward",
}


@dataclass
class Flight:
    date: dt.date
    flight_no: str = ""
    aircraft_type: str = ""
    registration: str = ""
    dep: str = ""
    arr: str = ""
    out_time: str = ""
    in_time: str = ""
    total: int = 0
    pic_name: str = ""
    se: int = 0
    me: int = 0
    multi_pilot: int = 0
    pic: int = 0
    picus: int = 0  # pilot-in-command under supervision (P1 U/S)
    copilot: int = 0
    dual: int = 0
    instructor: int = 0
    night: int = 0
    ifr: int = 0
    actual_inst: int = 0
    sim_inst: int = 0
    xc: int = 0
    sim: int = 0
    ldg_day: int = 0
    ldg_night: int = 0
    approaches: int = 0
    remarks: str = ""
    # A summary line of totals from a previous logbook rather than a real flight.
    carried_forward: bool = False
    id: int | None = None

    @property
    def landings(self) -> int:
        return self.ldg_day + self.ldg_night

    @property
    def sort_key(self) -> tuple:
        return (self.date, self.out_time, self.id or 0)

    @property
    def role(self) -> str:
        """A short label for the pilot's function on this flight."""
        if self.instructor:
            return "INSTR"
        if self.dual:
            return "DUAL"
        if self.pic:
            return "PIC"
        if self.picus:
            return "PICUS"
        if self.copilot:
            return "SIC"
        return ""

    def search_text(self) -> str:
        parts = (
            self.date.isoformat(),
            self.flight_no,
            self.aircraft_type,
            self.registration,
            self.dep,
            self.arr,
            self.pic_name,
            self.remarks,
            self.role,
            "brought forward" if self.carried_forward else "",
        )
        return " ".join(parts).casefold()

    def copy(self, **changes) -> Flight:
        return dataclasses.replace(self, **changes)


def validate(flight: Flight, today: dt.date) -> list[tuple[str, str]]:
    """Return ``(field, message)`` pairs for every problem found."""
    errors: list[tuple[str, str]] = []
    if flight.date > today + dt.timedelta(days=1):
        errors.append(("date", "The date is in the future"))
    if flight.date.year < 1900:
        errors.append(("date", "The date is too far in the past"))
    if not flight.carried_forward and not flight.aircraft_type:
        errors.append(("aircraft_type", "Enter the aircraft type"))
    if bool(flight.out_time) != bool(flight.in_time):
        missing = "in_time" if flight.out_time else "out_time"
        errors.append((missing, "Enter both off-block and on-block times, or neither"))
    if flight.total == 0 and flight.sim == 0:
        errors.append(("total", "Enter the total flight time (or a simulator time)"))
    if not flight.carried_forward:
        for name in ("total", "sim"):
            if getattr(flight, name) > MINUTES_PER_DAY:
                errors.append(
                    (name, f"{LABELS[name]} is over 24 hours - tick 'Brought forward' for "
                     "totals carried over from a previous logbook")
                )
    limit = max(flight.total, flight.sim)
    for name in SUB_DURATION_FIELDS:
        if getattr(flight, name) > limit:
            errors.append((name, f"{LABELS[name]} cannot be more than the total time"))
    if flight.se + flight.me + flight.multi_pilot > limit:
        errors.append(
            ("se", "Single-pilot SE + ME + multi-pilot time cannot add up to more than the total")
        )
    for name in DURATION_FIELDS + COUNT_FIELDS:
        if getattr(flight, name) < 0:
            errors.append((name, f"{LABELS[name]} cannot be negative"))
    return errors
