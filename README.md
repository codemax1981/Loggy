# Loggy

A pilot's logbook that runs in the terminal. It works on Windows (Windows Terminal,
PowerShell or the classic command prompt), and on macOS and Linux too.

![The logbook](docs/logbook.png)

- **Every logbook column**: date, aircraft type and registration, route, off- and
  on-block times (UTC), single-pilot SE/ME and multi-pilot time, PIC, PICUS (P1 U/S),
  co-pilot, dual and instructor time, night, IFR, actual and simulated instrument,
  cross-country, simulator (FSTD), day and night landings, approaches and remarks. That covers
  SACAA, DGCA, EASA/ICAO and FAA style logbooks.
- **Quick entry**: the total is worked out from the block times, including flights past
  midnight. Type `=` in any time box to copy the total. A new flight starts from your last one
  (same aircraft and PIC, departing where you last landed). Airports, registrations, types and
  names are suggested as you type, and a known registration fills in its aircraft type.
- **Totals**: grand totals; day and night time by role, single- and multi-engine, the way
  South African and Indian logbooks add it up; rolling 7/28/90-day, 6-month, 365-day and
  calendar-year totals; and totals by aircraft type and by year.
- **Currency** under SACAA and DGCA rules (or EASA/ICAO and FAA): take-off and landing
  currency by day and night, for any aircraft and for each type, plus instrument approaches,
  each with its regulation reference and the date it runs out.
- **Your data stays yours**: a single file on your computer, backed up automatically each day.
  CSV import and export works with Excel and with most other logbook apps.
- **Previous logbooks**: carry over the totals from a paper logbook as one brought-forward entry.

## Install on Windows

1. Install Python 3.9 or newer from [python.org](https://www.python.org/downloads/). On the
   first screen of the installer, tick **Add python.exe to PATH**.
2. Download Loggy: on GitHub choose **Code → Download ZIP** and unzip it somewhere, such as
   your Documents folder. Or `git clone` it.
3. Double-click **`loggy.bat`**.

The first start takes a minute while it installs what it needs into a `.venv` folder next to
the program. After that it starts straight away. Pin a shortcut to `loggy.bat` on your Start
menu or taskbar if you like.

Loggy looks best in [Windows Terminal](https://aka.ms/terminal), which is the default on
Windows 11. A window of at least 120 × 30 characters shows everything at once; smaller
windows scroll.

### Other ways to install

With Python already set up, you can install Loggy as a command instead:

```
py -m pip install .
loggy
```

(`python -m pip install .` on macOS and Linux.) If the `loggy` command is not found, run
`py -m loggy` instead.

## Using Loggy

| Key | Does |
| --- | --- |
| `a` | add a flight |
| `Enter` or `e` | edit the selected flight |
| `c` | copy the selected flight as a new one (same aircraft and route, today's date) |
| `d` | delete the selected flight (asks first) |
| `/` | search; `Esc` clears it |
| `1` `2` `3` | Logbook, Totals and Currency tabs |
| `x` / `i` | export to / import from CSV |
| `s` | settings: hours and minutes or decimal hours; which authorities' currency rules to check |
| `?` | help |
| `q` | quit |

The colour theme can be changed with `Ctrl+P` → *Theme*, and Loggy remembers your choice.

### Entering a flight

![Entering a flight](docs/new-flight.png)

- All times are **UTC**. Type clock times as `0930`, `930` or `09:30`.
- The **total** is worked out from the off-block and on-block times. You can also type it
  yourself, for example for flights logged without block times.
- Durations can be typed as `1:30`, `1.5` or `130`.
- Type **`=`** in any time box to copy the total into it. A box that equals the total
  *follows* it: if you then correct the on-block time, those boxes update too.
- A new flight starts from your last one. Boxes that were the whole flight last time (say PIC
  and single-pilot SE, or co-pilot, multi-pilot and IFR) fill in as soon as the total is
  known. Night time is never assumed.
- Dates: `t` = today, `y` = yesterday, `-3` = three days ago, or `YYYY-MM-DD`.
- The **→** key accepts a suggested airport, registration, type or name.
- `Enter` moves to the next box, `Ctrl+S` saves and `Esc` cancels (you are asked before
  anything you typed is thrown away).

**Single-engine and multi-engine time.** Put single-engine time in **SP SE** and multi-engine
time in **SP ME**, or in **Multi-pilot** when the aircraft is flown by a crew of two (airline
flying). Loggy's day and night summary counts SP ME and Multi-pilot together as multi-engine
time. **PICUS** is pilot in command under supervision (P1 U/S).

Loggy checks each entry before saving it. For example, PIC or night time can't be more than
the total, and both block times must be given or neither.

In the logbook the **Role** column shows PIC, PICUS, SIC (co-pilot), DUAL or INSTR. **SIM** marks a
simulator session (its session time is shown as the total) and **B/F** marks
brought-forward totals.

### Carrying on from a paper logbook

Add one entry dated the day of your last paper entry, put your totals in it (total, PIC,
night, landings and so on), and tick **Brought forward**. It counts towards your grand totals
and totals by type, but not towards currency, the recent-period totals or the day and night
summary by role (a paper total has no day and night split by role).

### Currency

![Currency](docs/currency.png)

Choose the authorities whose rules you fly under in Settings (`s`): **SACAA (South Africa)**
and **DGCA (India)** are ticked to start with, and EASA/ICAO and FAA are there too. Each
requirement is shown once, with every regulation that asks for it, for any aircraft and for
each type you have flown:

| Requirement | SACAA | DGCA | EASA / ICAO | FAA |
| --- | --- | --- | --- | --- |
| 3 take-offs and landings in 90 days, by day or night | CAR 91.02.4(1) | CAR Section 8 Series F Part I (on type, or an approved simulator) | FCL.060(b)(1) | 61.57(a) |
| Take-offs and landings at night in 90 days | 3, CAR 91.02.4(2) | | 1 without an instrument rating, FCL.060(b)(2) | 3 to a full stop, 61.57(b) |
| Instrument approaches | 2 in 90 days, CAR 91.02.4(4) | | | 6 in 6 calendar months, 61.57(c) |

Each line shows the date it runs out. **CURRENT** turns amber when that is within 14 days.

Some things to know:

- The DGCA 90-day rule is written for multi-pilot aeroplanes and those of 5,700 kg and more;
  check DGCA Operations Circular 1 of 2024 for lighter single-pilot aeroplanes. Loggy does not
  check a DGCA night or instrument recency rule, because none could be confirmed from the
  published regulations.
- Loggy counts take-offs as equal to landings, as paper logbooks do, and counts approaches and
  landings flown in a simulator, which SACAA and DGCA allow.
- Loggy is a record-keeping aid, not legal advice. Regulations change, so check the current
  rules for your licence and aircraft.

## Your data

| | Windows | macOS | Linux |
| --- | --- | --- | --- |
| Logbook | `%LOCALAPPDATA%\Loggy\logbook.db` | `~/Library/Application Support/Loggy/logbook.db` | `~/.local/share/loggy/logbook.db` |

The settings file (`settings.json`) sits in the same folder. Press `s` in Loggy to see the
exact paths.

- **Backups**: each day you open Loggy it saves a copy of the logbook to the `backups` folder
  next to it, keeping the last 30. To restore one, close Loggy and copy it over `logbook.db`.
- **Another logbook file**: `loggy --db D:\logbook.db` (or `loggy.bat --db ...`), or set the
  `LOGGY_DB` environment variable. This is handy for keeping the logbook in a synced folder.
- **Export**: `x` writes everything to a CSV file that opens in Excel. It's worth keeping a
  copy somewhere safe now and then.

### Importing

`i` reads a CSV file and shows what it found before adding anything. Entries already in the
logbook are skipped, so importing the same file twice is harmless. Loggy reads its own exports
and most spreadsheets and logbook-app exports:

- Column names are matched loosely: `From`, `Dep` or `Departure`; `Reg`, `Tail` or `Ident`;
  `Total`, `Block time` or `Total time`; `PIC`, `P1 U/S`, `SIC`, `Night`, `IFR`, `Landings`
  and so on.
  Columns it doesn't know are listed and ignored.
- Commas, semicolons or tabs; dates as `2026-10-07`, `07/10/2026` or `10/07/2026` (whether the
  day comes first is worked out from the whole file), or `07-Oct-2026`.
- Times as `1:30`, `1.5`, or Excel's `01:30:00`.

Rows with problems are skipped and listed with their row number, so you can fix them and
import again.

### Command line

```
loggy                         open the logbook
loggy export logbook.csv      export (add --decimal for decimal hours)
loggy import old-logbook.csv  import, printing anything that was skipped
loggy --db PATH               use another logbook file
```

## Development

```
py -m pip install -e .[dev]
py -m pytest
```

The code is in `loggy/`:

- `models.py`: the flight record and its validation
- `db.py`: SQLite storage and backups
- `stats.py`: totals and currency
- `csvio.py`: CSV import and export
- `app.py`, `form.py`, `dialogs.py`, `table.py` and `reports.py`: the
  [Textual](https://textual.textualize.io/) interface
