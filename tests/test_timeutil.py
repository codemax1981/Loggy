import datetime as dt

import pytest

from loggy.timeutil import (
    DECIMAL,
    add_months,
    block_minutes,
    end_of_month,
    format_duration,
    parse_clock,
    parse_count,
    parse_date,
    parse_duration,
)

TODAY = dt.date(2026, 10, 8)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("0930", "09:30"),
        ("930", "09:30"),
        ("9:30", "09:30"),
        ("09:30", "09:30"),
        ("0930z", "09:30"),
        ("2359Z", "23:59"),
        ("2400", "00:00"),
        ("  ", ""),
    ],
)
def test_parse_clock(text, expected):
    assert parse_clock(text) == expected


@pytest.mark.parametrize("text", ["12", "2460", "2500", "9:3", "ab:cd", "1:30pm"])
def test_parse_clock_rejects(text):
    with pytest.raises(ValueError):
        parse_clock(text)


def test_block_minutes_handles_midnight():
    assert block_minutes("09:30", "10:45") == 75
    assert block_minutes("23:10", "01:05") == 115
    assert block_minutes("12:00", "12:00") == 0


@pytest.mark.parametrize(
    "text, minutes",
    [
        ("1:30", 90),
        ("0:05", 5),
        ("1234:00", 1234 * 60),
        ("1.5", 90),
        ("1,5", 90),
        (".3", 18),
        ("1.25", 75),
        ("130", 90),
        ("0130", 90),
        ("2", 120),
        ("12", 720),
        ("", 0),
    ],
)
def test_parse_duration(text, minutes):
    assert parse_duration(text) == minutes


@pytest.mark.parametrize("text", ["1:75", "1:5", "-1", "190", "12345", "abc", "1.5h", "²"])
def test_parse_duration_rejects(text):
    with pytest.raises(ValueError):
        parse_duration(text)


def test_format_duration():
    assert format_duration(75) == "1:15"
    assert format_duration(0) == "0:00"
    assert format_duration(0, blank_zero=True) == ""
    assert format_duration(60 * 1234 + 5) == "1234:05"
    assert format_duration(75, DECIMAL) == "1.3"  # half rounds up
    assert format_duration(78, DECIMAL) == "1.3"
    assert format_duration(0, DECIMAL) == "0.0"


def test_decimal_round_trip():
    for tenths in range(0, 200):
        text = f"{tenths / 10:.1f}"
        assert format_duration(parse_duration(text), DECIMAL) == text


def test_parse_count():
    assert parse_count("") == 0
    assert parse_count(" 3 ") == 3
    for bad in ("-1", "1.5", "x", "³"):
        with pytest.raises(ValueError):
            parse_count(bad)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("2026-10-07", dt.date(2026, 10, 7)),
        ("20261007", dt.date(2026, 10, 7)),
        ("t", TODAY),
        ("Today", TODAY),
        ("y", dt.date(2026, 10, 7)),
        ("-3", dt.date(2026, 10, 5)),
    ],
)
def test_parse_date(text, expected):
    assert parse_date(text, TODAY) == expected


@pytest.mark.parametrize("text", ["2026-02-30", "07/10/2026", "", "tomorrow"])
def test_parse_date_rejects(text):
    with pytest.raises(ValueError):
        parse_date(text, TODAY)


def test_month_arithmetic():
    assert add_months(dt.date(2026, 10, 8), -6) == dt.date(2026, 4, 1)
    assert add_months(dt.date(2026, 1, 31), -1) == dt.date(2025, 12, 1)
    assert add_months(dt.date(2026, 11, 2), 3) == dt.date(2027, 2, 1)
    assert end_of_month(dt.date(2028, 2, 10)) == dt.date(2028, 2, 29)
    assert end_of_month(dt.date(2026, 12, 1)) == dt.date(2026, 12, 31)
