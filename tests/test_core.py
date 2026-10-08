import datetime as dt

import pytest

from loggy.db import Logbook, LogbookError, daily_backup
from loggy.models import Flight, validate
from loggy.stats import (
    ANY_AIRCRAFT,
    RULES,
    Totals,
    approach_currency,
    currency_by_type,
    landing_currency,
    last_flight,
    period_totals,
    totals_by_type,
    totals_by_year,
)

TODAY = dt.date(2026, 10, 8)


def flight(day, **values):
    values.setdefault("aircraft_type", "C172")
    values.setdefault("total", 60)
    return Flight(date=day, **values)


# -- validation --------------------------------------------------------------------------


def test_valid_flight_has_no_errors():
    assert validate(flight(TODAY, pic=60, se=60, night=30), TODAY) == []


def test_validation_catches_inconsistent_entries():
    fields = {name for name, _ in validate(
        flight(TODAY, aircraft_type="", out_time="09:00", pic=90, se=40, multi_pilot=40), TODAY
    )}
    assert fields == {"aircraft_type", "in_time", "pic", "se"}


def test_validation_requires_some_time():
    assert [name for name, _ in validate(flight(TODAY, total=0), TODAY)] == ["total"]
    assert validate(flight(TODAY, total=0, sim=120, sim_inst=60), TODAY) == []


def test_validation_limits_single_flights_to_24_hours():
    assert [name for name, _ in validate(flight(TODAY, total=25 * 60), TODAY)] == ["total"]
    brought_forward = flight(TODAY, aircraft_type="", total=1500 * 60, pic=900 * 60,
                             ldg_day=800, carried_forward=True)
    assert validate(brought_forward, TODAY) == []


def test_validation_rejects_future_dates():
    assert validate(flight(TODAY + dt.timedelta(days=1)), TODAY) == []
    assert [name for name, _ in validate(flight(TODAY + dt.timedelta(days=2)), TODAY)] == ["date"]


# -- storage -----------------------------------------------------------------------------


def test_logbook_round_trip(tmp_path):
    book = Logbook(tmp_path / "sub" / "logbook.db")
    original = flight(TODAY, registration="G-ABCD", dep="EGLL", arr="EGKK", out_time="09:30",
                      in_time="10:45", total=75, pic=75, ldg_day=1, remarks="Ünïcode ✓",
                      carried_forward=False)
    new_id = book.add(original)
    assert original.id == new_id
    loaded = book.get(new_id)
    assert loaded == original

    loaded.remarks = "changed"
    book.update(loaded)
    assert book.get(new_id).remarks == "changed"

    book.delete(new_id)
    assert book.get(new_id) is None
    assert book.flights() == []
    book.close()


def test_logbook_orders_chronologically(tmp_path):
    book = Logbook(tmp_path / "logbook.db")
    book.add_many([
        flight(dt.date(2026, 5, 2), out_time="14:00", in_time="15:00"),
        flight(dt.date(2026, 5, 1)),
        flight(dt.date(2026, 5, 2), out_time="08:00", in_time="09:00"),
    ])
    assert [(f.date.day, f.out_time) for f in book.flights()] == [
        (1, ""), (2, "08:00"), (2, "14:00"),
    ]


def test_logbook_rejects_newer_schema(tmp_path):
    path = tmp_path / "logbook.db"
    Logbook(path).close()
    import sqlite3

    conn = sqlite3.connect(path)
    conn.execute("PRAGMA user_version = 99")
    conn.close()
    with pytest.raises(LogbookError):
        Logbook(path)


def test_logbook_rejects_files_that_are_not_databases(tmp_path):
    path = tmp_path / "logbook.db"
    path.write_text("this is not a database " * 100)
    with pytest.raises(LogbookError):
        Logbook(path)


def test_daily_backup(tmp_path):
    book = Logbook(tmp_path / "logbook.db")
    backups = tmp_path / "backups"
    assert daily_backup(book, backups, TODAY) is None  # nothing to back up yet
    book.add(flight(TODAY))
    written = daily_backup(book, backups, TODAY)
    assert written == backups / "logbook-2026-10-08.db"
    assert Logbook(written).count() == 1
    assert daily_backup(book, backups, TODAY) is None  # once per day
    for day in range(1, 6):
        daily_backup(book, backups, TODAY + dt.timedelta(days=day), keep=3)
    names = sorted(p.name for p in backups.iterdir())
    assert names == ["logbook-2026-10-11.db", "logbook-2026-10-12.db", "logbook-2026-10-13.db"]


# -- totals ------------------------------------------------------------------------------


def test_totals_count_flights_sessions_and_brought_forward():
    entries = [
        flight(TODAY, total=60, pic=60, ldg_day=2, ldg_night=1),
        flight(TODAY, total=0, sim=120),
        flight(TODAY, total=6000, pic=3000, ldg_day=500, carried_forward=True),
    ]
    totals = Totals(entries)
    assert (totals.flights, totals.sim_sessions) == (1, 1)
    assert totals["total"] == 6060
    assert totals["pic"] == 3060
    assert totals["sim"] == 120
    assert totals.landings == 503


def test_period_totals_exclude_brought_forward():
    entries = [
        flight(TODAY, total=60),
        flight(TODAY - dt.timedelta(days=6), total=30),
        flight(TODAY - dt.timedelta(days=7), total=15),
        flight(TODAY - dt.timedelta(days=27), total=10),
        flight(dt.date(2025, 11, 1), total=100),
        flight(dt.date(2025, 10, 8), total=1),  # just outside the last 365 days
        flight(TODAY, total=9999, carried_forward=True),
    ]
    periods = dict(period_totals(entries, TODAY))
    assert periods["Last 7 days"]["total"] == 90
    assert periods["Last 28 days"]["total"] == 115
    assert periods["Year 2026"]["total"] == 115
    assert periods["Year 2025"]["total"] == 101
    assert periods["Last 365 days"]["total"] == 215


def test_totals_by_type_and_year():
    entries = [
        flight(dt.date(2025, 3, 1), aircraft_type="c172", total=60),
        flight(dt.date(2026, 3, 1), aircraft_type="C172", total=30),
        flight(dt.date(2026, 4, 1), aircraft_type="PA28", total=120),
        flight(dt.date(2020, 1, 1), aircraft_type="", total=600, carried_forward=True),
    ]
    by_type = totals_by_type(entries)
    assert [(t.aircraft_type, t.totals["total"]) for t in by_type] == [
        ("Brought forward", 600), ("PA28", 120), ("C172", 90),
    ]
    assert by_type[2].last_date == dt.date(2026, 3, 1)
    assert by_type[0].last_date is None
    by_year = totals_by_year(entries)
    assert [(label, t["total"]) for label, t in by_year] == [
        ("2026", 150), ("2025", 60), ("Brought forward", 600),
    ]


def test_last_flight_ignores_sim_and_brought_forward():
    entries = [
        flight(dt.date(2026, 9, 1), registration="A"),
        flight(dt.date(2026, 9, 3), total=0, sim=60),
        flight(dt.date(2026, 9, 4), carried_forward=True),
    ]
    assert last_flight(entries).registration == "A"
    assert last_flight([]) is None


# -- currency ----------------------------------------------------------------------------


def test_landing_currency_valid_until_third_landing_expires():
    entries = [
        flight(dt.date(2026, 9, 30), ldg_day=1),
        flight(dt.date(2026, 9, 1), ldg_day=1, ldg_night=1),  # completes the 3
        flight(dt.date(2026, 6, 1), ldg_day=5),  # outside the window
    ]
    status = landing_currency(entries, TODAY, 3, night=False)
    assert status.valid_until == dt.date(2026, 11, 30)
    assert status.current and status.count == 3 and status.days_left == 53

    night = landing_currency(entries, TODAY, 3, night=True)
    assert not night.current and night.count == 1 and night.needed == 2
    assert night.valid_until is None


def test_landing_currency_expires_after_90_days():
    entries = [flight(dt.date(2026, 7, 10), ldg_day=3)]
    assert landing_currency(entries, dt.date(2026, 10, 8), 3, night=False).current
    expired = landing_currency(entries, dt.date(2026, 10, 9), 3, night=False)
    assert not expired.current
    assert expired.valid_until == dt.date(2026, 10, 8)
    assert expired.count == 0 and expired.needed == 3


def test_landing_currency_ignores_future_and_brought_forward_entries():
    entries = [
        flight(TODAY + dt.timedelta(days=1), ldg_day=3),
        flight(TODAY, ldg_day=900, carried_forward=True),
    ]
    status = landing_currency(entries, TODAY, 3, night=False)
    assert not status.current and status.count == 0


def test_approach_currency_uses_calendar_months():
    entries = [
        flight(dt.date(2026, 4, 1), approaches=4),
        flight(dt.date(2026, 3, 31), approaches=4),
        flight(dt.date(2026, 9, 15), approaches=2),
    ]
    status = approach_currency(entries, TODAY)
    # Six approaches were completed on 2026-04-01, so current to the end of October.
    assert status.count == 6
    assert status.valid_until == dt.date(2026, 10, 31)
    assert status.current
    later = approach_currency(entries, dt.date(2026, 11, 1))
    assert not later.current and later.count == 2


def test_currency_by_type():
    entries = [
        flight(dt.date(2026, 10, 1), aircraft_type="C172", ldg_day=2),
        flight(dt.date(2026, 9, 1), aircraft_type="PA28", ldg_day=1, ldg_night=1),
    ]
    rows = currency_by_type(entries, TODAY, RULES["easa"])
    assert [r.aircraft_type for r in rows] == [ANY_AIRCRAFT, "C172", "PA28"]
    any_row, c172, pa28 = rows
    assert any_row.day.current and any_row.night.current
    assert not c172.day.current and c172.day.needed == 1
    assert pa28.night.current  # EASA needs one night landing
    faa = currency_by_type(entries, TODAY, RULES["faa"])
    assert not faa[2].night.current and faa[2].night.needed == 2
    assert currency_by_type([], TODAY, RULES["faa"]) == []
