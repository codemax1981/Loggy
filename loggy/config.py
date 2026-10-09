"""Where Loggy keeps its files, and the user's settings."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .layouts import LAYOUTS, SACAA
from .stats import DEFAULT_RULES, RULES
from .timeutil import DECIMAL, TIME_FORMATS


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
    time_format: str = DECIMAL  # "decimal" (1.5) or "hm" (1:30)
    rules: list[str] = field(default_factory=lambda: list(DEFAULT_RULES))  # keys of RULES
    layout: str = SACAA  # key into layouts.LAYOUTS
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
        # Settings from before 1.2, which had no layout, kept H:MM only because it was the
        # default then; 1.2 follows the SACAA logbook, in decimal hours.
        if data.get("time_format") in TIME_FORMATS and "layout" in data:
            settings.time_format = data["time_format"]
        rules = data.get("rules")
        if isinstance(rules, str):  # versions before 1.1 kept a single rule set
            rules = [rules]
        if isinstance(rules, list):
            chosen = [key for key in RULES if key in rules]
            if chosen:
                settings.rules = chosen
        if data.get("layout") in LAYOUTS:
            settings.layout = data["layout"]
        if isinstance(data.get("theme"), str):
            settings.theme = data["theme"]
        return settings

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        os.replace(temporary, path)
