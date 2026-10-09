"""SQLite storage for the logbook."""

from __future__ import annotations

import dataclasses
import datetime as dt
import sqlite3
from pathlib import Path
from typing import Iterable

from .models import (
    CLOCK_FIELDS,
    COUNT_FIELDS,
    DURATION_FIELDS,
    TEXT_FIELDS,
    Endorsement,
    Flight,
)

SCHEMA_VERSION = 3
ENDORSEMENTS_TABLE = """CREATE TABLE IF NOT EXISTS endorsements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    instructor TEXT NOT NULL DEFAULT '',
    licence TEXT NOT NULL DEFAULT '',
    designation TEXT NOT NULL DEFAULT '',
    ato TEXT NOT NULL DEFAULT '',
    ato_number TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)"""
# Statements that bring a logbook from the previous version up to each version.
MIGRATIONS = {
    2: ("ALTER TABLE flights ADD COLUMN picus INTEGER NOT NULL DEFAULT 0",),
    3: (
        "ALTER TABLE flights ADD COLUMN navaids TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE flights ADD COLUMN place TEXT NOT NULL DEFAULT ''",
        ENDORSEMENTS_TABLE,
    ),
}

COLUMNS = (
    ("date", "TEXT NOT NULL"),
    *((name, "TEXT NOT NULL DEFAULT ''") for name in TEXT_FIELDS + CLOCK_FIELDS),
    *((name, "INTEGER NOT NULL DEFAULT 0") for name in DURATION_FIELDS + COUNT_FIELDS),
    ("carried_forward", "INTEGER NOT NULL DEFAULT 0"),
)
COLUMN_NAMES = tuple(name for name, _ in COLUMNS)
# Flight's fields in declaration order, so a row can be passed to Flight() positionally.
FIELD_ORDER = tuple(field.name for field in dataclasses.fields(Flight))
_SELECT = f"SELECT {', '.join(FIELD_ORDER)} FROM flights"
_DATE = FIELD_ORDER.index("date")
_CARRIED_FORWARD = FIELD_ORDER.index("carried_forward")
ENDORSEMENT_FIELDS = tuple(
    field.name for field in dataclasses.fields(Endorsement) if field.name != "id"
)


class LogbookError(Exception):
    pass


class Logbook:
    """A logbook stored in a single SQLite file."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(str(path))
            self._migrate()
        except sqlite3.DatabaseError as error:
            raise LogbookError(f"Cannot open logbook {self.path}: {error}") from error

    def _migrate(self) -> None:
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise LogbookError(
                f"{self.path} was written by a newer version of Loggy - please upgrade"
            )
        if version < 1:
            columns = ",\n    ".join(f"{name} {kind}" for name, kind in COLUMNS)
            with self._conn:
                self._conn.execute(
                    f"CREATE TABLE IF NOT EXISTS flights (\n"
                    f"    id INTEGER PRIMARY KEY AUTOINCREMENT,\n    {columns},\n"
                    f"    created_at TEXT NOT NULL,\n    updated_at TEXT NOT NULL\n)"
                )
                self._conn.execute(
                    "CREATE INDEX IF NOT EXISTS flights_by_date ON flights (date, out_time)"
                )
                self._conn.execute(ENDORSEMENTS_TABLE)
                self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            return
        for target in range(version + 1, SCHEMA_VERSION + 1):
            with self._conn:
                self._conn.execute("BEGIN")  # each step commits completely or not at all
                for statement in MIGRATIONS[target]:
                    self._conn.execute(statement)
                self._conn.execute(f"PRAGMA user_version = {target}")

    def close(self) -> None:
        self._conn.close()

    # -- reading -----------------------------------------------------------------

    def flights(self) -> list[Flight]:
        """All entries in chronological order."""
        rows = self._conn.execute(f"{_SELECT} ORDER BY date, out_time, id")
        return [self._from_row(row) for row in rows]

    def get(self, flight_id: int) -> Flight | None:
        row = self._conn.execute(f"{_SELECT} WHERE id = ?", (flight_id,)).fetchone()
        return self._from_row(row) if row else None

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM flights").fetchone()[0]

    @staticmethod
    def _from_row(row: tuple) -> Flight:
        values = list(row)
        values[_DATE] = dt.date.fromisoformat(values[_DATE])
        values[_CARRIED_FORWARD] = bool(values[_CARRIED_FORWARD])
        return Flight(*values)

    # -- writing -----------------------------------------------------------------

    @staticmethod
    def _values(flight: Flight) -> list:
        values = []
        for name in COLUMN_NAMES:
            value = getattr(flight, name)
            if name == "date":
                value = value.isoformat()
            elif name == "carried_forward":
                value = int(value)
            values.append(value)
        return values

    @staticmethod
    def _now() -> str:
        return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    def add(self, flight: Flight) -> int:
        return self.add_many([flight])[0]

    def add_many(self, flights: Iterable[Flight]) -> list[int]:
        """Add several flights in one transaction; returns their new ids."""
        now = self._now()
        placeholders = ", ".join("?" for _ in range(len(COLUMN_NAMES) + 2))
        sql = (
            f"INSERT INTO flights ({', '.join(COLUMN_NAMES)}, created_at, updated_at) "
            f"VALUES ({placeholders})"
        )
        ids = []
        with self._conn:
            for flight in flights:
                cursor = self._conn.execute(sql, [*self._values(flight), now, now])
                flight.id = cursor.lastrowid
                ids.append(cursor.lastrowid)
        return ids

    def update(self, flight: Flight) -> None:
        if flight.id is None:
            raise ValueError("Cannot update a flight that has not been saved")
        assignments = ", ".join(f"{name} = ?" for name in COLUMN_NAMES)
        with self._conn:
            cursor = self._conn.execute(
                f"UPDATE flights SET {assignments}, updated_at = ? WHERE id = ?",
                [*self._values(flight), self._now(), flight.id],
            )
        if cursor.rowcount == 0:
            raise LogbookError(f"Flight {flight.id} no longer exists")

    def delete(self, flight_id: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM flights WHERE id = ?", (flight_id,))

    # -- endorsements --------------------------------------------------------------

    def endorsements(self) -> list[Endorsement]:
        """All endorsements in date order."""
        rows = self._conn.execute(
            f"SELECT {', '.join(ENDORSEMENT_FIELDS)}, id FROM endorsements ORDER BY date, id"
        )
        return [Endorsement(dt.date.fromisoformat(row[0]), *row[1:]) for row in rows]

    @staticmethod
    def _endorsement_values(endorsement: Endorsement) -> list:
        return [endorsement.date.isoformat(),
                *(getattr(endorsement, name) for name in ENDORSEMENT_FIELDS[1:])]

    def add_endorsement(self, endorsement: Endorsement) -> int:
        now = self._now()
        placeholders = ", ".join("?" for _ in range(len(ENDORSEMENT_FIELDS) + 2))
        with self._conn:
            cursor = self._conn.execute(
                f"INSERT INTO endorsements ({', '.join(ENDORSEMENT_FIELDS)}, created_at, "
                f"updated_at) VALUES ({placeholders})",
                [*self._endorsement_values(endorsement), now, now],
            )
        endorsement.id = cursor.lastrowid
        return cursor.lastrowid

    def update_endorsement(self, endorsement: Endorsement) -> None:
        if endorsement.id is None:
            raise ValueError("Cannot update an endorsement that has not been saved")
        assignments = ", ".join(f"{name} = ?" for name in ENDORSEMENT_FIELDS)
        with self._conn:
            cursor = self._conn.execute(
                f"UPDATE endorsements SET {assignments}, updated_at = ? WHERE id = ?",
                [*self._endorsement_values(endorsement), self._now(), endorsement.id],
            )
        if cursor.rowcount == 0:
            raise LogbookError(f"Endorsement {endorsement.id} no longer exists")

    def delete_endorsement(self, endorsement_id: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM endorsements WHERE id = ?", (endorsement_id,))

    # -- maintenance ---------------------------------------------------------------

    def backup_to(self, destination: Path) -> None:
        """Write a consistent copy of the logbook to ``destination``."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        target = sqlite3.connect(str(destination))
        try:
            self._conn.backup(target)
        finally:
            target.close()


def daily_backup(logbook: Logbook, backup_dir: Path, today: dt.date, keep: int = 30) -> Path | None:
    """Keep one backup per day of use, deleting all but the newest ``keep``.

    Returns the path of the backup written today, or ``None`` if there was
    nothing to do (the logbook is empty or today's backup already exists).
    """
    if logbook.count() == 0 and not logbook.endorsements():
        return None
    target = backup_dir / f"logbook-{today.isoformat()}.db"
    written = None
    if not target.exists():
        logbook.backup_to(target)
        written = target
    backups = sorted(backup_dir.glob("logbook-????-??-??.db"))
    for old in backups[:-keep]:
        try:
            old.unlink()
        except OSError:
            pass
    return written
