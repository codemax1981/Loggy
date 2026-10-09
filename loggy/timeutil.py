"""Parsing and formatting of dates, clock times and durations.

All clock times are UTC. Durations are stored as whole minutes.
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import ROUND_HALF_UP, Decimal

HM = "hm"
DECIMAL = "decimal"
TIME_FORMATS = (HM, DECIMAL)

MINUTES_PER_DAY = 24 * 60

_CLOCK_RE = re.compile(r"(\d{1,2}):?(\d{2})", re.ASCII)
_HM_RE = re.compile(r"(\d+):(\d{2})", re.ASCII)
_DECIMAL_RE = re.compile(r"(\d*)[.,](\d+)", re.ASCII)
_DIGITS_RE = re.compile(r"\d{1,4}", re.ASCII)
_ISO_DATE_RE = re.compile(r"(\d{4})-?(\d{2})-?(\d{2})", re.ASCII)
_RELATIVE_DATE_RE = re.compile(r"[+-]\d{1,4}", re.ASCII)


def utc_today() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def parse_clock(text: str) -> str:
    """Parse a UTC clock time such as ``0930``, ``930``, ``9:30`` or ``09:30Z``.

    Returns the normalised ``HH:MM`` form, or ``""`` for blank input.
    """
    value = text.strip().upper()
    if not value:
        return ""
    if value.endswith("Z"):
        value = value[:-1].rstrip()
    match = _CLOCK_RE.fullmatch(value)
    if not match:
        raise ValueError(f"'{text.strip()}' is not a time - use HHMM or HH:MM (UTC)")
    hours, minutes = int(match.group(1)), int(match.group(2))
    if hours == 24 and minutes == 0:
        hours = 0
    if hours > 23 or minutes > 59:
        raise ValueError(f"'{text.strip()}' is not a valid time of day")
    return f"{hours:02d}:{minutes:02d}"


def clock_minutes(hhmm: str) -> int:
    """Minutes after midnight for a normalised ``HH:MM`` string."""
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def block_minutes(out_time: str, in_time: str) -> int:
    """Minutes between off-block and on-block, allowing for a flight past midnight."""
    return (clock_minutes(in_time) - clock_minutes(out_time)) % MINUTES_PER_DAY


def parse_duration(text: str) -> int:
    """Parse a duration into whole minutes.

    Accepted forms:
      ``1:30``          hours and minutes
      ``1.5`` / ``1,5`` decimal hours
      ``130`` / ``0130`` three or four digits read as HMM / HHMM
      ``2``             one or two digits read as whole hours
    Blank input is zero.
    """
    value = text.strip()
    if not value:
        return 0
    match = _HM_RE.fullmatch(value)
    if match:
        minutes = int(match.group(2))
        if minutes > 59:
            raise ValueError(f"'{value}' has more than 59 minutes")
        return int(match.group(1)) * 60 + minutes
    match = _DECIMAL_RE.fullmatch(value)
    if match:
        hours = Decimal(f"{match.group(1) or '0'}.{match.group(2)}")
        return int((hours * 60).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    if _DIGITS_RE.fullmatch(value):
        if len(value) <= 2:
            return int(value) * 60
        hours, minutes = int(value[:-2]), int(value[-2:])
        if minutes < 60:
            return hours * 60 + minutes
    raise ValueError(f"'{value}' is not a duration - use H:MM or decimal hours")


def format_duration(minutes: int, fmt: str = HM, *, blank_zero: bool = False) -> str:
    """Format minutes as ``H:MM`` or decimal hours (one decimal place)."""
    if not minutes and blank_zero:
        return ""
    if fmt == DECIMAL:
        hours = (Decimal(minutes) / 60).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        return f"{hours:.1f}"
    hours, mins = divmod(minutes, 60)
    return f"{hours}:{mins:02d}"


def parse_count(text: str) -> int:
    """Parse a non-negative whole number (landings, approaches)."""
    value = text.strip()
    if not value:
        return 0
    if not value.isascii() or not value.isdigit():
        raise ValueError(f"'{value}' is not a whole number")
    return int(value)


def parse_date(text: str, today: dt.date | None = None) -> dt.date:
    """Parse a date.

    Accepts ``YYYY-MM-DD`` or ``YYYYMMDD``, ``t``/``today``, ``y``/``yesterday``
    and relative days such as ``-2``.
    """
    value = text.strip().lower()
    if today is None:
        today = utc_today()
    if value in ("t", "today"):
        return today
    if value in ("y", "yesterday"):
        return today - dt.timedelta(days=1)
    if _RELATIVE_DATE_RE.fullmatch(value):
        return today + dt.timedelta(days=int(value))
    match = _ISO_DATE_RE.fullmatch(value)
    if match:
        try:
            return dt.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            raise ValueError(f"'{text.strip()}' is not a real date") from None
    raise ValueError(
        f"'{text.strip()}' is not a date - use YYYY-MM-DD (t = today, y = yesterday)"
    )


def add_months(day: dt.date, months: int) -> dt.date:
    """The first day of the month ``months`` after the month containing ``day``."""
    index = day.year * 12 + (day.month - 1) + months
    return dt.date(index // 12, index % 12 + 1, 1)


def end_of_month(day: dt.date) -> dt.date:
    return add_months(day, 1) - dt.timedelta(days=1)


def months_before(day: dt.date, months: int) -> dt.date:
    """The same day of the month ``months`` earlier (the 31st becomes the month's last day)."""
    first = add_months(day, -months)
    return first.replace(day=min(day.day, end_of_month(first).day))
