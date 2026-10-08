import datetime as dt

from loggy.csvio import (
    detect_date_order,
    export_csv,
    import_csv,
    parse_csv,
    parse_import_date,
    split_duplicates,
)
from loggy.models import Flight
from loggy.timeutil import DECIMAL, HM

TODAY = dt.date(2026, 10, 8)


def sample_flights():
    return [
        Flight(date=dt.date(2026, 10, 7), flight_no="BAW123", aircraft_type="A320",
               registration="G-EUUA", dep="EGLL", arr="LFPG", out_time="09:30", in_time="10:45",
               total=75, pic_name="Capt. Ståhl, J", multi_pilot=75, copilot=75, ifr=75,
               night=20, ldg_day=1, approaches=1, remarks='Line check, "good", 1,2'),
        Flight(date=dt.date(2026, 10, 1), aircraft_type="A320 FFS", registration="SIM-1",
               sim=240, sim_inst=240, remarks="OPC"),
        Flight(date=dt.date(2020, 1, 1), total=1234 * 60, pic=600 * 60, ldg_day=900,
               carried_forward=True, remarks="Paper logbook 1"),
    ]


def test_export_and_import_round_trip(tmp_path):
    path = tmp_path / "out.csv"
    assert export_csv(sample_flights(), path, HM) == 3
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")  # BOM for Excel
    result = import_csv(path, TODAY)
    assert result.errors == [] and result.warnings == []
    assert result.flights == sample_flights()


def test_decimal_export_round_trip(tmp_path):
    path = tmp_path / "out.csv"
    flights = [Flight(date=TODAY, aircraft_type="C152", total=78, pic=78, dual=18)]
    export_csv(flights, path, DECIMAL)
    assert "1.3" in path.read_text(encoding="utf-8-sig")
    assert import_csv(path, TODAY).flights == flights


def test_import_from_excel_style_file(tmp_path):
    # Semicolons, day-first dates, H:MM:SS times, a title row and Windows-1252 text.
    text = (
        "My logbook;;;;;;\r\n"
        "Date;Type;Reg;Departure;Arrival;Off Block;On Block;Total Time;Landings;Notes;Fuel\r\n"
        "07/10/2026;c172;g-abcd;egkb;egkb;09:30:00;10:45:00;;3;Circuits – café;40\r\n"
        "25/09/2026;C172;G-ABCD;EGKB;EGTK;;;01:17:59;1;;\r\n"
        ";;;;;;;;;;\r\n"
    )
    path = tmp_path / "excel.csv"
    path.write_bytes(text.encode("cp1252"))
    result = import_csv(path, TODAY)
    assert result.errors == []
    assert result.warnings == ["Ignored columns: Fuel"]
    first, second = result.flights
    assert first.date == dt.date(2026, 10, 7)
    assert (first.aircraft_type, first.registration, first.dep) == ("C172", "G-ABCD", "EGKB")
    assert (first.out_time, first.in_time, first.total) == ("09:30", "10:45", 75)
    assert first.ldg_day == 3 and first.remarks == "Circuits – café"
    assert second.total == 78  # rounded to the nearest minute


def test_import_reports_bad_rows_and_keeps_good_ones():
    text = (
        "Date,Aircraft Type,Total,PIC\n"
        "2026-10-01,C172,1:00,1:00\n"
        "2026-10-02,C172,1:00,2:00\n"
        "not a date,C172,1:00,\n"
        "2026-10-03,C172,abc,\n"
    )
    result = parse_csv(text, TODAY)
    assert len(result.flights) == 1
    assert result.errors == [
        "Row 3: PIC cannot be more than the total time",
        "Row 4: 'not a date' is not a date Loggy understands",
        "Row 5: 'abc' is not a duration - use H:MM or decimal hours",
    ]


def test_import_needs_a_date_column():
    result = parse_csv("Type,Total\nC172,1:00\n", TODAY)
    assert result.flights == [] and result.errors == ["No 'Date' column was found"]
    assert parse_csv("", TODAY).errors == ["The file is empty"]


def test_date_order_detection():
    assert detect_date_order(["07/10/2026", "25/09/2026"]) == ("dmy", None)
    assert detect_date_order(["10/07/2026", "09/25/2026"]) == ("mdy", None)
    order, warning = detect_date_order(["01/02/2026"])
    assert order == "dmy" and "day-first or month-first" in warning
    assert detect_date_order(["2026-10-07"]) == ("dmy", None)


def test_parse_import_date_formats():
    assert parse_import_date("2026/10/07") == dt.date(2026, 10, 7)
    assert parse_import_date("20261007") == dt.date(2026, 10, 7)
    assert parse_import_date("2026-10-07 00:00:00") == dt.date(2026, 10, 7)
    assert parse_import_date("2026-10-07T00:00") == dt.date(2026, 10, 7)
    assert parse_import_date("7.10.26", "dmy", TODAY) == dt.date(2026, 10, 7)
    assert parse_import_date("10/7/99", "mdy", TODAY) == dt.date(1999, 10, 7)
    assert parse_import_date("07-Oct-2026") == dt.date(2026, 10, 7)
    assert parse_import_date("Oct 7, 2026") == dt.date(2026, 10, 7)


def test_split_duplicates():
    existing = sample_flights()
    new = sample_flights() + [Flight(date=TODAY, aircraft_type="C172", total=60)]
    fresh, duplicates = split_duplicates(new, existing)
    assert len(fresh) == 1 and len(duplicates) == 3
