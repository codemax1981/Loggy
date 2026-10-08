"""Command line entry point: ``loggy`` or ``python -m loggy``."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from . import __version__
from .config import Settings, data_dir, default_db_path
from .db import Logbook, LogbookError, daily_backup
from .timeutil import DECIMAL, HM, utc_today


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="loggy",
        description="Loggy - a pilot's logbook for the terminal. "
        "Run without a command to open the logbook.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        metavar="FILE",
        help=f"the logbook file to use (default: {default_db_path()})",
    )
    parser.add_argument("--version", action="version", version=f"Loggy {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")
    export = commands.add_parser("export", help="save the logbook as a CSV file")
    export.add_argument("file", type=Path)
    export.add_argument("--decimal", action="store_true", help="write times as decimal hours")
    load = commands.add_parser("import", help="add flights from a CSV file")
    load.add_argument("file", type=Path)
    return parser


def _export(logbook: Logbook, path: Path, decimal: bool) -> int:
    from .csvio import export_csv

    try:
        count = export_csv(logbook.flights(), path, DECIMAL if decimal else HM)
    except OSError as error:
        print(f"loggy: could not write {path}: {error}", file=sys.stderr)
        return 1
    print(f"Exported {count} entries to {path}")
    return 0


def _import(logbook: Logbook, path: Path) -> int:
    from .csvio import import_csv, split_duplicates

    try:
        result = import_csv(path, utc_today())
    except OSError as error:
        print(f"loggy: could not read {path}: {error}", file=sys.stderr)
        return 1
    for warning in result.warnings:
        print(f"Note: {warning}")
    for error in result.errors:
        print(f"Skipped {error}")
    fresh, duplicates = split_duplicates(result.flights, logbook.flights())
    logbook.add_many(fresh)
    print(f"Imported {len(fresh)} entries ({len(duplicates)} already in the logbook, "
          f"{len(result.errors)} with problems)")
    return 0 if not result.errors else 2


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    db_path = (args.db or default_db_path()).expanduser()
    try:
        logbook = Logbook(db_path)
    except (LogbookError, OSError) as error:
        print(f"loggy: {error}", file=sys.stderr)
        return 1
    try:
        if args.command == "export":
            return _export(logbook, args.file, args.decimal)
        if args.command == "import":
            return _import(logbook, args.file)

        backup_dir = db_path.parent / "backups"
        try:
            daily_backup(logbook, backup_dir, utc_today())
        except (OSError, sqlite3.Error) as error:
            print(f"loggy: warning: could not back up the logbook: {error}", file=sys.stderr)
        settings_path = data_dir() / "settings.json"
        from .app import run  # Textual loads only when the interface is needed

        run(logbook, Settings.load(settings_path), settings_path, backup_dir)
        return 0
    finally:
        logbook.close()


if __name__ == "__main__":
    sys.exit(main())
