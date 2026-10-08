"""Drive the real app headlessly and check what ends up in the logbook."""

import asyncio
import datetime as dt
import io

import pytest
from rich.console import Console
from textual.widgets import Input, Static

from loggy.app import LoggyApp
from loggy.config import Settings
from loggy.db import Logbook
from loggy.dialogs import ConfirmDialog, ImportPreview, PathDialog, SettingsDialog
from loggy.form import FlightForm
from loggy.models import Flight
from loggy.table import LogTable

TODAY = dt.date(2026, 10, 8)


@pytest.fixture
def logbook(tmp_path):
    book = Logbook(tmp_path / "logbook.db")
    yield book
    book.close()


def run(app, test, size=(120, 34)):
    """Run ``test(pilot)`` against ``app`` headlessly."""

    async def main():
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            await test(pilot)

    asyncio.run(main())


def make_app(logbook, tmp_path, **settings):
    return LoggyApp(logbook, Settings(**settings), tmp_path / "settings.json",
                    today=lambda: TODAY, backup_dir=tmp_path / "backups")


async def type_into(pilot, field, text):
    widget = pilot.app.screen.query_one(f"#f-{field}", Input)
    widget.focus()
    await pilot.pause()
    widget.value = ""
    await pilot.press(*text)
    await pilot.pause()


def form_value(pilot, field):
    return pilot.app.screen.query_one(f"#f-{field}", Input).value


def plain(widget: Static) -> str:
    """The text a Static is showing."""
    console = Console(width=160, file=io.StringIO(), color_system=None)
    with console.capture() as capture:
        console.print(widget.content)
    return capture.get()


def test_empty_logbook_explains_what_to_do(logbook, tmp_path):
    async def test(pilot):
        assert "Your logbook is empty" in plain(pilot.app.query_one("#empty", Static))
        assert not pilot.app.query_one("#flights", LogTable).display

    run(make_app(logbook, tmp_path), test)


def test_add_flight_with_block_times_and_follow(logbook, tmp_path):
    async def test(pilot):
        await pilot.press("a")
        await pilot.pause()
        assert isinstance(pilot.app.screen, FlightForm)
        await type_into(pilot, "aircraft_type", "c172")
        await type_into(pilot, "registration", "g-abcd")
        await type_into(pilot, "dep", "egkb")
        await type_into(pilot, "arr", "egtk")
        await type_into(pilot, "pic", "=")  # follow the total, which is not known yet
        assert form_value(pilot, "pic") == ""
        await type_into(pilot, "out_time", "2330")
        await type_into(pilot, "in_time", "0045")  # past midnight
        assert form_value(pilot, "total") == "1:15"
        assert form_value(pilot, "pic") == "1:15"
        await type_into(pilot, "se", "=")
        assert form_value(pilot, "se") == "1:15"
        await type_into(pilot, "night", "0:40")
        await type_into(pilot, "ldg_night", "1")
        await type_into(pilot, "in_time", "0050")  # later on-block: followers move with it
        assert form_value(pilot, "total") == "1:20"
        assert form_value(pilot, "pic") == "1:20"
        assert form_value(pilot, "night") == "0:40"
        assert form_value(pilot, "aircraft_type") == "C172"
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert not isinstance(pilot.app.screen, FlightForm)

    run(make_app(logbook, tmp_path), test)
    [saved] = logbook.flights()
    assert (saved.date, saved.aircraft_type, saved.registration) == (TODAY, "C172", "G-ABCD")
    assert (saved.dep, saved.arr) == ("EGKB", "EGTK")
    assert (saved.out_time, saved.in_time) == ("23:30", "00:50")
    assert (saved.total, saved.pic, saved.se, saved.night, saved.ldg_night) == (80, 80, 80, 40, 1)


def test_invalid_flight_is_not_saved(logbook, tmp_path):
    async def test(pilot):
        await pilot.press("a")
        await pilot.pause()
        await type_into(pilot, "aircraft_type", "C172")
        await type_into(pilot, "total", "1:00")
        await type_into(pilot, "pic", "1:30")
        await pilot.press("ctrl+s")
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, FlightForm)
        assert "PIC cannot be more than the total" in plain(screen.query_one("#message", Static))
        assert screen.focused.id == "f-pic"
        assert screen.focused.has_class("-invalid")

    run(make_app(logbook, tmp_path), test)
    assert logbook.flights() == []


def test_new_flight_carries_on_from_the_last(logbook, tmp_path):
    logbook.add(Flight(date=dt.date(2026, 10, 1), aircraft_type="A320", registration="G-EUUA",
                       dep="EGLL", arr="LFPG", out_time="09:00", in_time="10:10", total=70,
                       pic_name="CAPT KIRK", multi_pilot=70, copilot=70, ifr=70, night=70))

    async def test(pilot):
        await pilot.press("a")
        await pilot.pause()
        assert form_value(pilot, "date") == "2026-10-08"
        assert form_value(pilot, "dep") == "LFPG"
        assert form_value(pilot, "aircraft_type") == "A320"
        assert form_value(pilot, "pic_name") == "CAPT KIRK"
        await type_into(pilot, "out_time", "1200")
        await type_into(pilot, "in_time", "1315")
        for field in ("multi_pilot", "copilot", "ifr"):
            assert form_value(pilot, field) == "1:15"
        assert form_value(pilot, "night") == ""  # night is never assumed

    run(make_app(logbook, tmp_path), test)


def test_typing_replaces_the_prefilled_date(logbook, tmp_path):
    async def test(pilot):
        await pilot.press("a")
        await pilot.pause()
        await pilot.press("y", "tab")  # straight away, as a pilot would
        await pilot.pause()
        assert form_value(pilot, "date") == "2026-10-07"

    run(make_app(logbook, tmp_path), test)


def test_registration_fills_in_its_type(logbook, tmp_path):
    logbook.add(Flight(date=dt.date(2026, 9, 1), aircraft_type="PA28", registration="G-BRBA",
                       total=60))
    logbook.add(Flight(date=dt.date(2026, 9, 2), aircraft_type="C172", registration="G-BSFP",
                       total=60))

    async def test(pilot):
        await pilot.press("a")
        await pilot.pause()
        assert form_value(pilot, "aircraft_type") == "C172"
        await type_into(pilot, "registration", "g-brba")
        assert form_value(pilot, "aircraft_type") == "PA28"

    run(make_app(logbook, tmp_path), test)


def test_editing_keeps_a_total_that_differs_from_block_time(logbook, tmp_path):
    flight_id = logbook.add(Flight(date=dt.date(2026, 9, 1), aircraft_type="C172",
                                   out_time="09:00", in_time="10:10", total=65, pic=65))

    async def test(pilot):
        await pilot.press("e")
        await pilot.pause()
        assert form_value(pilot, "total") == "1:05"
        await type_into(pilot, "remarks", "Airborne time only")
        await pilot.press("ctrl+s")
        await pilot.pause()

    run(make_app(logbook, tmp_path), test)
    saved = logbook.get(flight_id)
    assert (saved.total, saved.pic, saved.remarks) == (65, 65, "Airborne time only")


def test_edit_and_delete(logbook, tmp_path):
    flight_id = logbook.add(Flight(date=dt.date(2026, 9, 1), aircraft_type="C172",
                                   registration="G-BSFP", total=60, pic=60, remarks="old"))

    async def test(pilot):
        await pilot.press("enter")  # edit the highlighted (only) flight
        await pilot.pause()
        assert isinstance(pilot.app.screen, FlightForm)
        await type_into(pilot, "remarks", "Circuits")
        await type_into(pilot, "total", "1.5")
        assert form_value(pilot, "pic") == "1:30"  # PIC was the whole flight, so it follows
        await pilot.click("#save")
        await pilot.pause()
        assert logbook.get(flight_id).remarks == "Circuits"
        assert logbook.get(flight_id).pic == 90

        await pilot.press("d")
        await pilot.pause()
        assert isinstance(pilot.app.screen, ConfirmDialog)
        await pilot.press("enter")  # Cancel has the focus
        await pilot.pause()
        assert logbook.get(flight_id) is not None
        await pilot.press("d")
        await pilot.pause()
        await pilot.click("#confirm")
        await pilot.pause()
        assert logbook.get(flight_id) is None

    run(make_app(logbook, tmp_path), test)


def test_cancel_asks_before_discarding(logbook, tmp_path):
    async def test(pilot):
        await pilot.press("a")
        await pilot.pause()
        await pilot.press("escape")  # nothing typed: closes straight away
        await pilot.pause()
        assert not isinstance(pilot.app.screen, FlightForm)
        await pilot.press("a")
        await pilot.pause()
        await type_into(pilot, "remarks", "x")
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(pilot.app.screen, ConfirmDialog)
        await pilot.press("escape")  # keep editing
        await pilot.pause()
        assert isinstance(pilot.app.screen, FlightForm)
        assert form_value(pilot, "remarks") == "x"

    run(make_app(logbook, tmp_path), test)


def test_search_filters_the_table(logbook, tmp_path):
    logbook.add_many([
        Flight(date=dt.date(2026, 9, 1), aircraft_type="C172", dep="EGKB", arr="EGTK", total=60),
        Flight(date=dt.date(2026, 9, 2), aircraft_type="PA28", dep="EGKB", arr="LFAT", total=90),
        Flight(date=dt.date(2026, 9, 3), aircraft_type="C172", dep="LFAT", arr="EGKB", total=30,
               remarks="Customs"),
    ])

    async def test(pilot):
        table = pilot.app.query_one("#flights", LogTable)
        assert table.row_count == 3
        await pilot.press("slash", "l", "f", "a", "t")
        await pilot.pause(0.3)
        assert table.row_count == 2
        await pilot.press("space", "c", "1", "7", "2")
        await pilot.pause(0.3)
        assert table.row_count == 1
        assert "1 of 3 entries match" in plain(pilot.app.query_one("#status", Static))
        await pilot.press("escape")
        await pilot.pause(0.3)
        assert table.row_count == 3

    run(make_app(logbook, tmp_path), test)


def test_export_import_and_settings(logbook, tmp_path):
    logbook.add(Flight(date=dt.date(2026, 9, 1), aircraft_type="C172", total=90, pic=90))
    export_path = tmp_path / "export.csv"

    async def test(pilot):
        await pilot.press("x")
        await pilot.pause()
        assert isinstance(pilot.app.screen, PathDialog)
        pilot.app.screen.query_one("#path", Input).value = f'"{export_path}"'  # pasted with quotes
        await pilot.press("enter")
        await pilot.pause()
        assert export_path.exists()

        # Importing the same file finds nothing new.
        await pilot.press("i")
        await pilot.pause()
        pilot.app.screen.query_one("#path", Input).value = str(export_path)
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(pilot.app.screen, ImportPreview)
        assert not pilot.app.screen.query("#import")
        await pilot.press("escape")
        await pilot.pause()

        export_path.write_text("Date,Type,Total\n2026-09-05,PA28,1.0\n", encoding="utf-8")
        await pilot.press("i")
        await pilot.pause()
        pilot.app.screen.query_one("#path", Input).value = str(export_path)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.click("#import")
        await pilot.pause()
        assert len(logbook.flights()) == 2

        await pilot.press("s")
        await pilot.pause()
        assert isinstance(pilot.app.screen, SettingsDialog)
        pilot.app.screen.query_one("#time-format").value = "decimal"
        await pilot.click("#save")
        await pilot.pause()
        table = pilot.app.query_one("#flights", LogTable)
        assert table.cell(1, 7) == "1.5"

    run(make_app(logbook, tmp_path), test)
    assert Settings.load(tmp_path / "settings.json").time_format == "decimal"


@pytest.mark.parametrize("rules", ["easa", "faa"])
def test_reports_render_for_both_rule_sets(logbook, tmp_path, rules):
    logbook.add_many([
        Flight(date=dt.date(2026, 9, 1), aircraft_type="C172", total=90, pic=90, ldg_day=3,
               approaches=2),
        Flight(date=dt.date(2020, 1, 1), total=6000, carried_forward=True),
    ])

    async def test(pilot):
        await pilot.press("2")
        await pilot.pause()
        assert pilot.app.focused.id == "totals-scroll"
        await pilot.press("3", "a")  # bindings still work from a report tab
        await pilot.pause()
        assert isinstance(pilot.app.screen, FlightForm)
        await pilot.press("escape")
        totals = plain(pilot.app.query_one("#totals-report", Static))
        currency = plain(pilot.app.query_one("#currency-report", Static))
        assert "Grand totals" in totals and "101:30" in totals
        assert "CURRENT" in currency
        assert ("Instrument currency" in currency) == (rules == "faa")

    run(make_app(logbook, tmp_path, rules=rules), test)


def test_small_terminal_still_works(logbook, tmp_path):
    logbook.add(Flight(date=dt.date(2026, 9, 1), aircraft_type="C172", total=60))

    async def test(pilot):
        await pilot.press("a")
        await pilot.pause()
        await type_into(pilot, "total", "1:00")
        await type_into(pilot, "aircraft_type", "C152")
        form = pilot.app.screen.query_one("#form")
        pilot.app.screen.query_one("#f-instructor", Input).focus()
        await pilot.pause()
        assert form.scroll_x > 0  # the form scrolled sideways to show the box
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert len(logbook.flights()) == 2

    run(make_app(logbook, tmp_path), test, size=(80, 24))


def test_theme_choice_is_remembered(logbook, tmp_path):
    async def test(pilot):
        pilot.app.theme = "nord"
        await pilot.pause()

    run(make_app(logbook, tmp_path), test)
    assert Settings.load(tmp_path / "settings.json").theme == "nord"

    async def check(pilot):
        assert pilot.app.theme == "nord"

    run(LoggyApp(logbook, Settings.load(tmp_path / "settings.json"), tmp_path / "settings.json",
                 today=lambda: TODAY), check)
