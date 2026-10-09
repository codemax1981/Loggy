from loggy.table import Column, LogTable, column_widths, groups

COLUMNS = (
    Column("Date"),
    Column("Registration", short="Reg."),
    Column("Dual", right=True, group="SE day"),
    Column("PIC", right=True, group="SE day"),
    Column("Dual", right=True, group="SE night"),
    Column("Day", right=True, group="Landings"),
    Column("Night", right=True, group="Landings"),
    Column("Details of flight", short="Details"),
)
ROWS = [("2026-06-18", "ZS-KWT", "3.0", "", "", "3", "", "Initial PPL skills test")]


def test_groups_are_runs_of_columns():
    assert groups(COLUMNS) == [(2, 4), (4, 5), (5, 7)]


def test_widths_fit_cells_short_headings_and_groups():
    widths = column_widths(COLUMNS, ROWS)
    assert widths[1] == 6  # "ZS-KWT": the short heading "Reg." fits
    assert widths[4] == 8  # widened from 4 so that "SE night" fits over its one column
    assert widths[7] == len("Initial PPL skills test")
    assert column_widths(COLUMNS, [])[1] == 4  # no rows: as wide as "Reg."


def test_headings():
    table = LogTable(COLUMNS)
    table.widths = column_widths(COLUMNS, ROWS)
    headings = table._line([column.heading(width)
                            for column, width in zip(COLUMNS, table.widths)])
    assert "Reg. " in headings and "Registration" not in headings
    assert " Details of flight " in headings
    groups_line = table._group_line()
    assert groups_line.split() == ["SE", "day", "SE", "night", "Landings"]
    wide = list(table.widths)
    wide[2] += 6  # room to spare: the heading sits between rules
    table.widths = wide
    assert "─ SE day ─" in table._group_line()
