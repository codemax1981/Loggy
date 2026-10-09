import datetime as dt

import pytest

from loggy.config import Settings
from loggy.db import SCHEMA_VERSION, Logbook, LogbookError, daily_backup
from loggy.models import Endorsement, Flight, validate
from loggy.stats import (
    ANY_AIRCRAFT,
    Totals,
    approach_currency,
    currency_status,
    experience,
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


def test_currency_status_per_type():
    entries = [
        flight(dt.date(2026, 10, 1), aircraft_type="C172", ldg_day=2),
        flight(dt.date(2026, 9, 1), aircraft_type="PA28", ldg_day=1, ldg_night=1),
    ]
    day, night = currency_status(entries, TODAY, ["easa"])
    assert (day.requirement.title, night.requirement.title) == ("Day", "Night")
    assert [row.aircraft_type for row in day.rows] == [ANY_AIRCRAFT, "C172", "PA28"]
    any_row, c172, pa28 = day.rows
    assert any_row.currency.current and any_row.last_date == dt.date(2026, 10, 1)
    assert not c172.currency.current and c172.currency.needed == 1
    assert night.rows[2].currency.current  # EASA asks for one night landing
    faa_night = currency_status(entries, TODAY, ["faa"])[1]
    assert not faa_night.rows[2].currency.current and faa_night.rows[2].currency.needed == 2
    assert currency_status([], TODAY, ["faa"]) == []


def test_sacaa_and_dgca_share_the_day_requirement():
    entries = [flight(dt.date(2026, 10, 1), ldg_day=3, ldg_night=3, approaches=2)]
    day, night, instrument = currency_status(entries, TODAY, ["sacaa", "dgca"])
    assert [authority for authority, _ in day.sources] == ["SACAA (South Africa)", "DGCA (India)"]
    assert "91.02.4(1)" in day.sources[0][1] and "Section 8 Series F Part I" in day.sources[1][1]
    assert night.requirement.required == 3 and len(night.sources) == 1
    assert instrument.requirement.title == "Instrument"
    assert [row.aircraft_type for row in instrument.rows] == [ANY_AIRCRAFT]  # not per type
    assert all(status.rows[0].currency.current for status in (day, night, instrument))


def test_different_requirements_are_kept_apart():
    statuses = currency_status([flight(TODAY, ldg_day=1)], TODAY, ["easa", "faa"])
    assert [(s.requirement.title, s.requirement.required) for s in statuses] == [
        ("Day", 3), ("Night", 1), ("Night", 3), ("Instrument", 6),
    ]


def test_sacaa_approaches_count_over_90_days():
    entries = [flight(dt.date(2026, 8, 1), approaches=1), flight(dt.date(2026, 7, 1), approaches=1)]
    instrument = currency_status(entries, TODAY, ["sacaa"])[2]
    currency = instrument.rows[0].currency
    assert not currency.current and currency.count == 1 and currency.needed == 1
    assert currency.valid_until == dt.date(2026, 9, 29)  # 90 days after the second one
    entries.append(flight(dt.date(2026, 10, 2), approaches=1))
    currency = currency_status(entries, TODAY, ["sacaa"])[2].rows[0].currency
    assert currency.current and currency.valid_until == dt.date(2026, 10, 30)


def test_settings_load_and_upgrade(tmp_path):
    path = tmp_path / "settings.json"
    defaults = Settings.load(path)
    assert (defaults.rules, defaults.time_format, defaults.layout) == (
        ["sacaa", "dgca"], "decimal", "sacaa")
    path.write_text('{"rules": "faa", "time_format": "hm", "theme": "nord"}')
    settings = Settings.load(path)  # from 1.0: a single rule set, and H:MM was the default
    assert (settings.rules, settings.time_format, settings.theme) == (["faa"], "decimal", "nord")
    assert settings.layout == "sacaa"
    path.write_text('{"time_format": "hm", "layout": "standard"}')
    settings = Settings.load(path)
    assert (settings.time_format, settings.layout) == ("hm", "standard")
    path.write_text('{"rules": ["dgca", "bogus", "sacaa"], "time_format": "weird", '
                    '"layout": "weird"}')
    settings = Settings.load(path)
    assert (settings.rules, settings.time_format, settings.layout) == (
        ["sacaa", "dgca"], "decimal", "sacaa")
    path.write_text('{"rules": []}')
    assert Settings.load(path).rules == ["sacaa", "dgca"]
    settings.rules = ["easa"]
    settings.save(path)
    assert Settings.load(path).rules == ["easa"]


V1_SCHEMA = """
CREATE TABLE flights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    flight_no TEXT NOT NULL DEFAULT '',
    aircraft_type TEXT NOT NULL DEFAULT '',
    registration TEXT NOT NULL DEFAULT '',
    dep TEXT NOT NULL DEFAULT '',
    arr TEXT NOT NULL DEFAULT '',
    pic_name TEXT NOT NULL DEFAULT '',
    remarks TEXT NOT NULL DEFAULT '',
    out_time TEXT NOT NULL DEFAULT '',
    in_time TEXT NOT NULL DEFAULT '',
    total INTEGER NOT NULL DEFAULT 0,
    se INTEGER NOT NULL DEFAULT 0,
    me INTEGER NOT NULL DEFAULT 0,
    multi_pilot INTEGER NOT NULL DEFAULT 0,
    pic INTEGER NOT NULL DEFAULT 0,
    copilot INTEGER NOT NULL DEFAULT 0,
    dual INTEGER NOT NULL DEFAULT 0,
    instructor INTEGER NOT NULL DEFAULT 0,
    night INTEGER NOT NULL DEFAULT 0,
    ifr INTEGER NOT NULL DEFAULT 0,
    actual_inst INTEGER NOT NULL DEFAULT 0,
    sim_inst INTEGER NOT NULL DEFAULT 0,
    xc INTEGER NOT NULL DEFAULT 0,
    sim INTEGER NOT NULL DEFAULT 0,
    ldg_day INTEGER NOT NULL DEFAULT 0,
    ldg_night INTEGER NOT NULL DEFAULT 0,
    approaches INTEGER NOT NULL DEFAULT 0,
    carried_forward INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX flights_by_date ON flights (date, out_time);
PRAGMA user_version = 1;
"""


def test_version_1_logbook_is_upgraded_in_place(tmp_path):
    import sqlite3

    path = tmp_path / "logbook.db"
    conn = sqlite3.connect(path)
    conn.executescript(V1_SCHEMA)
    conn.execute(
        "INSERT INTO flights (date, aircraft_type, registration, total, pic, ldg_day, remarks,"
        " created_at, updated_at) VALUES ('2026-09-01', 'C172', 'ZS-ABC', 90, 90, 3, 'old',"
        " 'x', 'x')"
    )
    conn.commit()
    conn.close()

    book = Logbook(path)
    [entry] = book.flights()
    assert (entry.aircraft_type, entry.registration, entry.total, entry.pic, entry.picus) == (
        "C172", "ZS-ABC", 90, 90, 0)
    entry.picus = 30
    book.update(entry)
    assert book.get(entry.id).picus == 30
    book.close()
    assert sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    book = Logbook(path)  # opening again is harmless
    assert book.get(entry.id).picus == 30 and book.endorsements() == []
    book.close()


def test_picus_is_a_role():
    assert flight(TODAY, picus=60).role == "PICUS"
    assert flight(TODAY, picus=60, pic=60).role == "PIC"
    assert [name for name, _ in validate(flight(TODAY, picus=90), TODAY)] == ["picus"]


def test_day_and_night_by_role():
    entries = [
        flight(TODAY, total=60, se=60, dual=60, night=20),
        flight(TODAY, total=90, multi_pilot=90, copilot=90, night=90, xc=90),
        flight(TODAY, total=30, me=30, pic=30, xc=30),
        flight(TODAY, total=45, pic=45),  # not marked SE or ME
        flight(TODAY, total=0, sim=120, dual=120),  # simulator: not flight time
        flight(TODAY, total=6000, pic=6000, night=600, carried_forward=True),
    ]
    summary = experience(entries)
    assert (summary[("dual", "se", "day")], summary[("dual", "se", "night")]) == (40, 20)
    assert (summary[("copilot", "me", "day")], summary[("copilot", "me", "night")]) == (0, 90)
    assert summary[("pic", "me", "day")] == 30
    assert summary[("pic", "all", "day")] == 75
    assert summary[("dual", "all", "day")] == 40  # the simulator's dual time is left out
    assert (summary[("total", "all", "day")], summary[("total", "all", "night")]) == (115, 110)
    assert summary.unclassified == 45 and summary.xc_pic == 30
    assert (summary.brought_forward, summary.sim_sessions) == (1, 1)
    assert summary.has_engines()
    assert not experience([flight(TODAY, pic=60)]).has_engines()


def test_last_six_months():
    entries = [flight(dt.date(2026, 4, 9), total=60), flight(dt.date(2026, 4, 8), total=30)]
    assert dict(period_totals(entries, TODAY))["Last 6 months"]["total"] == 60


def test_endorsements(tmp_path):
    book = Logbook(tmp_path / "logbook.db")
    first = Endorsement(dt.date(2026, 2, 20), "J. VAN WYK", "0000000001", "Gr II", "SAMPLE ATO",
                        "CAA/0000", "Authorised to fly solo in circuits")
    earlier = Endorsement(dt.date(2025, 11, 8), "M. NAIDOO", text="Spin avoidance completed")
    book.add_endorsement(first)
    book.add_endorsement(earlier)
    assert [e.text for e in book.endorsements()] == [earlier.text, first.text]  # by date
    first.text = "Solo circuits"
    book.update_endorsement(first)
    assert book.endorsements()[1] == first
    book.delete_endorsement(earlier.id)
    assert book.endorsements() == [first]
    # A logbook with only endorsements is still backed up.
    assert daily_backup(book, tmp_path / "backups", TODAY) is not None


def test_navaids_and_place_round_trip(tmp_path):
    book = Logbook(tmp_path / "logbook.db")
    entry = flight(TODAY, approaches=2, navaids="ILS VOR", place="FALA")
    book.add(entry)
    assert book.get(entry.id) == entry
