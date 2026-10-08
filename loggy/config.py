"""Where Loggy keeps its files, and the user's settings."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .stats import RULES
from .timeutil import HM, TIME_FORMATS


def data_dir() -> Path:
    """The per-user folder for the logbook, settings and backups."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        return Path(base) / "Loggy" if base else Path.home() / "AppData" / "Local" / "Loggy"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Loggy"
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / "loggy"


def default_db_path() -> Path:
    override = os.environ.get("LOGGY_DB")
    return Path(override).expanduser() if override else data_dir() / "logbook.db"


def documents_dir() -> Path:
    documents = Path.home() / "Documents"
    return documents if documents.is_dir() else Path.home()


@dataclass
class Settings:
    time_format: str = HM  # "hm" (1:30) or "decimal" (1.5)
    rules: str = "easa"  # key into stats.RULES
    theme: str = ""  # Textual theme name; blank for the default

    @classmethod
    def load(cls, path: Path) -> Settings:
        settings = cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return settings
        if not isinstance(data, dict):
            return settings
        for field in fields(cls):
            value = data.get(field.name)
            if isinstance(value, str):
                setattr(settings, field.name, value)
        if settings.time_format not in TIME_FORMATS:
            settings.time_format = HM
        if settings.rules not in RULES:
            settings.rules = "easa"
        return settings

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        os.replace(temporary, path)
