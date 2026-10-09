"""CSV export and import.

Exports open cleanly in Excel. Imports accept Loggy's own exports and most
spreadsheets or other logbook apps: column names are matched loosely, the
delimiter and date order are detected, and Excel's habit of rewriting times
as ``H:MM:SS`` is tolerated.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from .models import (
    CLOCK_FIELDS,
    CODE_FIELDS,
    COUNT_FIELDS,
    DURATION_FIELDS,
    TEXT_FIELDS,
    Flight,
    validate,
)
from .timeutil import block_minutes, format_duration, parse_clock, parse_count, parse_duration

EXPORT_COLUMNS = (
    ("date", "Date"),
    ("flight_no", "Flight No"),
    ("aircraft_type", "Aircraft Type"),
    ("registration", "Registration"),
    ("dep", "From"),
    ("out_time", "Out (UTC)"),
    ("arr", "To"),
    ("in_time", "In (UTC)"),
    ("total", "Total"),
    ("pic_name", "PIC Name"),
    ("se", "SP SE"),
    ("me", "SP ME"),
    ("multi_pilot", "Multi-Pilot"),
    ("pic", "PIC"),
    ("picus", "PICUS"),
    ("copilot", "Co-Pilot"),
    ("dual", "Dual"),
    ("instructor", "Instructor"),
    ("night", "Night"),
    ("ifr", "IFR"),
    ("actual_inst", "Actual Instrument"),
    ("sim_inst", "Simulated Instrument"),
    ("xc", "Cross-Country"),
    ("sim", "Simulator"),
    ("ldg_day", "Day Landings"),
    ("ldg_night", "Night Landings"),
    ("approaches", "Approaches"),
    ("remarks", "Remarks"),
    ("carried_forward", "Brought Forward"),
)

# Other names for each column, written in normalised form (lower case letters and digits).
_ALIASES = {
    "date": ("flightdate", "dateutc", "day"),
    "flight_no": ("flightnumber", "flight", "fltno", "callsign"),
    "aircraft_type": ("type", "actype", "model", "makemodel", "aircraftmodel",
                      "aircraftmakemodel", "makeandmodel", "aircraft"),
    "registration": ("reg", "aircraftregistration", "tail", "tailnumber", "ident",
                     "aircraftident", "aircraftid", "identification"),
    "dep": ("dep", "departure", "departureplace", "origin", "routefrom", "fromicao"),
    "arr": ("arr", "arrival", "arrivalplace", "destination", "dest", "routeto", "toicao"),
    "out_time": ("out", "offblock", "offblocks", "blockoff", "departuretime", "deptime",
                 "timeout", "outtime"),
    "in_time": ("in", "onblock", "onblocks", "blockon", "arrivaltime", "arrtime", "timein",
                "intime"),
    "total": ("totaltime", "totalflighttime", "totaltimeofflight", "blocktime", "block",
              "duration", "totalduration", "totaldurationofflight", "flighttime"),
    "pic_name": ("nameofpic", "namepic", "namesofpic", "pic name", "captain", "commander"),
    "se": ("singlepilotse", "singleengine", "se", "sel", "asel", "singlepilotsingleengine"),
    "me": ("singlepilotme", "multiengine", "me", "mel", "amel", "singlepilotmultiengine"),
    "multi_pilot": ("mp", "multipilottime"),
    "pic": ("pictime", "pilotincommand", "p1"),
    "picus": ("p1us", "picundersupervision", "p1undersupervision",
              "pilotincommandundersupervision"),
    "copilot": ("sic", "secondincommand", "copilottime", "sictime", "p2"),
    "dual": ("dualreceived", "dualtime"),
    "instructor": ("fi", "cfi", "asflightinstructor", "instructortime", "dualgiven"),
    "night": ("nighttime",),
    "ifr": ("ifrtime",),
    "actual_inst": ("actual", "actualinst", "imc", "actualimc"),
    "sim_inst": ("simulated", "siminst", "hood", "simulatedinst"),
    "xc": ("xc", "xctime", "crosscountrytime"),
    "sim": ("sim", "fstd", "simulatortime", "fstdtime", "flightsimulator", "ffs"),
    "ldg_day": ("landingsday", "ldgday", "dayldg", "daylanding", "dayldgs", "landings", "ldg"),
    "ldg_night": ("landingsnight", "ldgnight", "nightldg", "nightlanding", "nightldgs"),
    "approaches": ("approach", "app", "apps", "instrumentapproaches", "numberofapproaches"),
    "remarks": ("remark", "notes", "note", "comments", "comment", "remarksandendorsements"),
    "carried_forward": ("carriedforward", "bf"),
}


def _normalise(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", header.lower())


HEADER_MAP: dict[str, str] = {}
for _name, _header in EXPORT_COLUMNS:
    HEADER_MAP[_normalise(_header)] = _name
    HEADER_MAP.setdefault(_normalise(_name), _name)
for _name, _aliases in _ALIASES.items():
    for _alias in _aliases:
        HEADER_MAP.setdefault(_normalise(_alias), _name)


# -- export -----------------------------------------------------------------------------


def export_csv(entries: Iterable[Flight], path: Path, time_format: str) -> int:
    """Write ``entries`` to ``path``; returns the number of rows written."""
    count = 0
    # utf-8-sig adds the byte-order mark Excel needs to read UTF-8 correctly.
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow([header for _, header in EXPORT_COLUMNS])
        for entry in entries:
            writer.writerow([_export_cell(entry, name, time_format) for name, _ in EXPORT_COLUMNS])
            count += 1
    return count


def _export_cell(entry: Flight, name: str, time_format: str) -> str:
    value = getattr(entry, name)
    if name == "date":
        return value.isoformat()
    if name in DURATION_FIELDS:
        return format_duration(value, time_format, blank_zero=True)
    if name in COUNT_FIELDS:
        return str(value) if value else ""
    if name == "carried_forward":
        return "yes" if value else ""
    return value


# -- import -----------------------------------------------------------------------------


@dataclass
class ImportResult:
    flights: list[Flight] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class _RowError(ValueError):
    pass


def read_text(path: Path) -> str:
    """Read a text file written by Loggy, Excel or another program."""
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _sniff_delimiter(text: str) -> str:
    sample = "\n".join(text.splitlines()[:10])
    return max((",", ";", "\t"), key=sample.count)


def import_csv(path: Path, today: dt.date) -> ImportResult:
    text = read_text(path)
    return parse_csv(text, today)


def parse_csv(text: str, today: dt.date) -> ImportResult:
    result = ImportResult()
    rows = list(csv.reader(io.StringIO(text), delimiter=_sniff_delimiter(text)))
    if not rows:
        result.errors.append("The file is empty")
        return result
    # Spreadsheets often have a title above the column names.
    header_row = next(
        (
            number
            for number, row in enumerate(rows[:10])
            if any(HEADER_MAP.get(_normalise(cell)) == "date" for cell in row)
        ),
        0,
    )
    first_line = header_row + 1

    columns: dict[int, str] = {}
    ignored = []
    for index, header in enumerate(rows[header_row]):
        name = HEADER_MAP.get(_normalise(header))
        if name and name not in columns.values():
            columns[index] = name
        elif header.strip():
            ignored.append(header.strip())
    if "date" not in columns.values():
        result.errors.append("No 'Date' column was found")
        return result
    if ignored:
        result.warnings.append("Ignored columns: " + ", ".join(ignored))

    date_index = next(i for i, name in columns.items() if name == "date")
    body = rows[first_line:]
    order, warning = detect_date_order(row[date_index] for row in body if len(row) > date_index)
    if warning:
        result.warnings.append(warning)

    for line_number, row in enumerate(body, start=first_line + 1):
        if not any(cell.strip() for cell in row):
            continue
        values = {name: row[index] if index < len(row) else "" for index, name in columns.items()}
        try:
            flight = _flight_from_values(values, order, today)
        except _RowError as error:
            result.errors.append(f"Row {line_number}: {error}")
            continue
        problems = validate(flight, today)
        if problems:
            result.errors.append(f"Row {line_number}: {problems[0][1]}")
            continue
        result.flights.append(flight)
    return result


def _flight_from_values(values: dict[str, str], order: str, today: dt.date) -> Flight:
    def parse(name: str, parser):
        try:
            return parser(values.get(name, ""))
        except ValueError as error:
            raise _RowError(str(error)) from None

    flight = Flight(date=parse("date", lambda v: parse_import_date(v, order, today)))
    for name in TEXT_FIELDS:
        text = " ".join(values.get(name, "").split())
        setattr(flight, name, text.upper() if name in CODE_FIELDS else text)
    for name in CLOCK_FIELDS:
        setattr(flight, name, parse(name, lambda v: parse_clock(_clock_without_seconds(v))))
    for name in DURATION_FIELDS:
        setattr(flight, name, parse(name, lambda v: parse_duration(_duration_without_seconds(v))))
    for name in COUNT_FIELDS:
        setattr(flight, name, parse(name, _parse_import_count))
    flight.carried_forward = values.get("carried_forward", "").strip().lower() in (
        "yes", "y", "true", "1", "x",
    )
    if not flight.total and flight.out_time and flight.in_time and not flight.sim:
        flight.total = block_minutes(flight.out_time, flight.in_time)
    return flight


_WITH_SECONDS_RE = re.compile(r"(\d+):(\d{2}):(\d{2})")


def _clock_without_seconds(value: str) -> str:
    match = _WITH_SECONDS_RE.fullmatch(value.strip())
    return f"{match.group(1)}:{match.group(2)}" if match else value


def _duration_without_seconds(value: str) -> str:
    """Round an ``H:MM:SS`` duration (as Excel writes them) to the nearest minute."""
    match = _WITH_SECONDS_RE.fullmatch(value.strip())
    if not match:
        return value
    hours, minutes, seconds = (int(group) for group in match.groups())
    total = hours * 60 + minutes + (1 if seconds >= 30 else 0)
    return f"{total // 60}:{total % 60:02d}"


def _parse_import_count(value: str) -> int:
    value = value.strip()
    if re.fullmatch(r"\d+\.0*", value):
        value = value.split(".")[0]
    return parse_count(value)


_ISO_RE = re.compile(r"(\d{4})([-/.])(\d{1,2})\2(\d{1,2})")
_COMPACT_ISO_RE = re.compile(r"(\d{4})(\d{2})(\d{2})")
_NUMERIC_RE = re.compile(r"(\d{1,2})([-/.])(\d{1,2})\2(\d{2}|\d{4})")
_NAMED_MONTH_FORMATS = ("%d-%b-%Y", "%d %b %Y", "%d-%b-%y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y")


def detect_date_order(values: Iterable[str]) -> tuple[str, str | None]:
    """Work out whether numeric dates are day-first ("dmy") or month-first ("mdy")."""
    day_first = month_first = seen = False
    for value in values:
        match = _NUMERIC_RE.fullmatch(_date_part(value))
        if not match:
            continue
        seen = True
        first, second = int(match.group(1)), int(match.group(3))
        day_first |= first > 12
        month_first |= second > 12
    if day_first and month_first:
        return "dmy", "Dates are a mix of day-first and month-first; read them as day/month/year"
    if month_first:
        return "mdy", None
    if seen and not day_first:
        return "dmy", "Every date could be day-first or month-first; read them as day/month/year"
    return "dmy", None


def _date_part(value: str) -> str:
    value = value.strip()
    # Drop a time of day added by a spreadsheet, as in "2026-10-07 00:00:00".
    match = re.fullmatch(r"(\S+)[ T]\d{1,2}:\d{2}(:\d{2})?", value)
    return match.group(1) if match else value


def parse_import_date(value: str, order: str = "dmy", today: dt.date | None = None) -> dt.date:
    text = _date_part(value)
    if not text:
        raise ValueError("The date is missing")
    try:
        match = _ISO_RE.fullmatch(text) or _COMPACT_ISO_RE.fullmatch(text)
        if match:
            groups = [g for g in match.groups() if g and g.isdigit()]
            return dt.date(int(groups[0]), int(groups[1]), int(groups[2]))
        match = _NUMERIC_RE.fullmatch(text)
        if match:
            first, second, year = int(match.group(1)), int(match.group(3)), match.group(4)
            day, month = (first, second) if order == "dmy" else (second, first)
            full_year = int(year) if len(year) == 4 else 2000 + int(year)
            if len(year) == 2 and full_year > (today or dt.date.today()).year:
                full_year -= 100
            return dt.date(full_year, month, day)
    except ValueError:
        raise ValueError(f"'{text}' is not a real date") from None
    for fmt in _NAMED_MONTH_FORMATS:
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"'{text}' is not a date Loggy understands")


# -- duplicates -----------------------------------------------------------------------


def entry_key(entry: Flight) -> tuple:
    return (
        entry.date,
        entry.registration,
        entry.dep,
        entry.arr,
        entry.out_time,
        entry.in_time,
        entry.total,
        entry.sim,
        entry.carried_forward,
    )


def split_duplicates(
    new: Sequence[Flight], existing: Sequence[Flight]
) -> tuple[list[Flight], list[Flight]]:
    """Separate entries already in the logbook from genuinely new ones."""
    known = {entry_key(entry) for entry in existing}
    fresh, duplicates = [], []
    for entry in new:
        (duplicates if entry_key(entry) in known else fresh).append(entry)
    return fresh, duplicates
