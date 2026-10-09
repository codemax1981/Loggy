import datetime as dt
import itertools

from loggy.layouts import (
    GRID_FIELDS,
    GRID_NAMES,
    SACAA_COLUMNS,
    apply_grid,
    engine_of,
    fits_grid,
    grid,
    grid_is_exact,
    sacaa_values,
)
from loggy.models import Flight

TODAY = dt.date(2026, 10, 9)


def cells(**minutes):
    return {name: minutes.get(name, 0) for name in GRID_NAMES}


def test_grid_from_a_flight():
    solo = Flight(date=TODAY, total=84, se=84, pic=84)
    assert grid(solo) == cells(se_day_pic=84)
    night_dual = Flight(date=TODAY, total=60, me=60, dual=60, night=20)
    assert grid(night_dual) == cells(me_day_dual=40, me_night_dual=20)
    line = Flight(date=TODAY, total=90, multi_pilot=90, copilot=90, night=90)
    assert grid(line) == cells(me_night_copilot=90)
    unmarked = Flight(date=TODAY, total=30, pic=30)
    assert engine_of(unmarked) == "" and grid(unmarked) == cells(se_day_pic=30)
    simulator = Flight(date=TODAY, sim=120, dual=120)
    assert grid(simulator) == cells()


def test_apply_grid_sets_every_derived_time():
    entry = Flight(date=TODAY)
    apply_grid(entry, cells(me_day_copilot=60, me_night_copilot=30))
    assert (entry.total, entry.night, entry.copilot) == (90, 30, 90)
    assert (entry.se, entry.me, entry.multi_pilot) == (0, 0, 90)
    apply_grid(entry, cells(se_day_dual=54))
    assert (entry.total, entry.dual, entry.copilot, entry.se, entry.multi_pilot, entry.night) == (
        54, 54, 0, 54, 0, 0)
    apply_grid(entry, cells(me_day_pic=30))
    assert (entry.me, entry.multi_pilot) == (30, 0)  # single-pilot multi-engine
    apply_grid(entry, cells(me_day_pic=30, me_day_copilot=20), multi_pilot=True)
    assert (entry.me, entry.multi_pilot) == (0, 50)  # an airliner's captain


def test_round_trip_is_exact_for_one_role():
    for name in GRID_NAMES:
        assert grid_is_exact(cells(**{name: 42}))
    assert grid_is_exact(cells(se_day_dual=30, se_night_dual=12))
    assert grid_is_exact(cells(se_day_dual=30, se_day_pic=30))  # two roles by day
    assert grid_is_exact(cells())


def test_round_trip_spots_what_one_entry_cannot_hold():
    assert not grid_is_exact(cells(se_day_dual=30, se_night_pic=30))
    assert not grid_is_exact(cells(se_day_pic=30, me_day_pic=30))  # two engine classes


def test_sacaa_values():
    entry = Flight(date=TODAY, aircraft_type="PA28", registration="ZS-SPK", pic_name="SELF",
                   remarks="Ex 18", total=96, se=96, pic=96, xc=96, ldg_day=1, instructor=0)
    values = sacaa_values(entry, "decimal")
    assert values["se_day_pic"] == "1.6" and values["se_day_dual"] == ""
    assert (values["ldg_day"], values["ldg_night"]) == ("1", "")
    assert set(values) == {column.key for column in SACAA_COLUMNS}
    simulator = sacaa_values(Flight(date=TODAY, sim=120, sim_inst=60, instructor=120), "hm")
    assert (simulator["sim"], simulator["inst_fstd"], simulator["instructor_fstd"]) == (
        "2:00", "1:00", "2:00")
    assert simulator["instructor_se"] == ""
    hood = sacaa_values(Flight(date=TODAY, total=60, se=60, dual=60, sim_inst=30), "decimal")
    assert hood["inst_fstd"] == "0.5"  # never hidden, wherever it was flown
    brought = sacaa_values(Flight(date=TODAY, total=600, se=600, pic=600, carried_forward=True,
                                  remarks="Old logbook"), "hm")
    assert brought["remarks"] == "Brought forward: Old logbook"
    assert brought["se_day_pic"] == "10:00"
    route = sacaa_values(Flight(date=TODAY, flight_no="6E7101", dep="VOBL", arr="VOMM",
                                remarks="PF", total=60, multi_pilot=60, copilot=60), "decimal")
    assert route["remarks"] == "6E7101  VOBL-VOMM  PF"


def test_entries_the_grid_cannot_show():
    assert fits_grid(Flight(date=TODAY, total=60, se=60, dual=30, pic=30))
    assert fits_grid(Flight(date=TODAY, total=60, me=60, pic=60, night=60, instructor=60))
    assert fits_grid(Flight(date=TODAY, sim=120, sim_inst=60))
    assert fits_grid(Flight(date=TODAY, total=60, multi_pilot=60, pic=60))  # captain
    assert not fits_grid(Flight(date=TODAY, total=60, me=30, multi_pilot=30, pic=60))
    mixed = Flight(date=TODAY, total=600, se=500, me=100, dual=300, pic=300,
                   carried_forward=True)
    no_role = Flight(date=TODAY, total=60, se=60)
    no_engine = Flight(date=TODAY, total=60, pic=60)
    both = Flight(date=TODAY, total=60, se=60, pic=60, dual=60)  # dual received as PIC
    for entry in (mixed, no_role, no_engine, both):
        assert not fits_grid(entry)
    values = sacaa_values(mixed, "decimal")
    assert all(values[name] == "" for name in GRID_NAMES)  # rather than show it wrongly
    assert values["remarks"] == (
        "Brought forward  [Total 10.0 · SE 8.3 · ME 1.7 · Dual 5.0 · PIC 5.0]")


def test_fits_grid_is_the_round_trip():
    def round_trip(entry):  # with multi-engine dual and PIC as single- or multi-pilot time
        for multi_pilot in (False, True):
            probe = Flight(date=entry.date)
            apply_grid(probe, grid(entry), multi_pilot=multi_pilot)
            if all(getattr(probe, name) == getattr(entry, name) for name in GRID_FIELDS):
                return True
        return False

    times = (0, 30, 60)
    checked = 0
    for total, se, me, mp, dual, pic, picus, copilot, night in itertools.product(
            (0, 60), times, times, (0, 60), times, times, (0, 30), (0, 60), times):
        entry = Flight(date=TODAY, total=total, se=se, me=me, multi_pilot=mp, dual=dual,
                       pic=pic, picus=picus, copilot=copilot, night=night)
        assert fits_grid(entry) == round_trip(entry), entry
        checked += fits_grid(entry)
    assert checked > 20  # some of them fit
