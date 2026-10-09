"""Small modal dialogs."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Select, Static

from .config import Settings
from .csvio import ImportResult
from .models import Flight
from .stats import RULES
from .timeutil import DECIMAL, HM

DIALOG_CSS = """
.dialog {
    width: 72;
    max-width: 100%;
    height: auto;
    max-height: 100%;
    background: $panel;
    border: round $primary;
    border-title-style: bold;
    padding: 1 2;
}
.dialog .buttons {
    height: auto;
    align-horizontal: right;
    margin-top: 1;
}
.dialog .buttons Button {
    margin-left: 2;
    min-width: 12;
}
.dialog .hint {
    color: $text-muted;
}
.dialog .error {
    color: $text-error;
    text-style: bold;
}
.dialog, .dialog VerticalScroll {
    scrollbar-size-vertical: 1;
}
"""


class ConfirmDialog(ModalScreen[bool]):
    DEFAULT_CSS = "ConfirmDialog { align: center middle; } ConfirmDialog .dialog { width: 60; }"
    BINDINGS = [Binding("escape", "dismiss(False)", "Cancel")]

    def __init__(self, message: str, *, confirm: str = "OK", cancel: str = "Cancel",
                 danger: bool = False) -> None:
        super().__init__()
        self._message = message
        self._confirm = confirm
        self._cancel = cancel
        self._danger = danger

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Static(self._message)
            with Horizontal(classes="buttons"):
                yield Button(self._confirm, variant="error" if self._danger else "primary",
                             id="confirm", compact=True)
                yield Button(self._cancel, id="cancel", compact=True)

    def on_mount(self) -> None:
        # A careless Enter should never destroy anything.
        self.query_one("#cancel" if self._danger else "#confirm").focus()

    @on(Button.Pressed)
    def _pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")


def clean_path(text: str) -> Path:
    """Turn pasted text (perhaps quoted, with ~ or %VARS%) into a path."""
    text = text.strip().strip('"').strip("'").strip()
    return Path(os.path.expandvars(os.path.expanduser(text)))


class PathDialog(ModalScreen[Optional[Path]]):
    """Ask for a file name to export to or import from."""

    DEFAULT_CSS = "PathDialog { align: center middle; } PathDialog Input { margin: 1 0 0 0; }"
    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, *, title: str, prompt: str, default: Path, action: str,
                 must_exist: bool) -> None:
        super().__init__()
        self._title = title
        self._prompt = prompt
        self._default = default
        self._action = action
        self._must_exist = must_exist

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog") as box:
            box.border_title = self._title
            yield Static(self._prompt)
            yield Input(str(self._default), id="path")
            yield Static("", id="problem", classes="error")
            with Horizontal(classes="buttons"):
                yield Button(self._action, variant="primary", id="go", compact=True)
                yield Button("Cancel", id="cancel", compact=True)

    def on_mount(self) -> None:
        widget = self.query_one("#path", Input)
        widget.focus()
        widget.select_on_focus = False
        widget.cursor_position = len(widget.value)

    def _problem(self, message: str) -> None:
        self.query_one("#problem", Static).update(message)

    def _go(self) -> None:
        text = self.query_one("#path", Input).value
        if not text.strip():
            self._problem("Enter a file name")
            return
        path = clean_path(text)
        if self._must_exist:
            if not path.is_file():
                self._problem(f"There is no file at {path}")
                return
            self.dismiss(path)
            return
        if path.is_dir():
            self._problem("That is a folder - add a file name such as logbook.csv")
            return
        if not path.parent.is_dir():
            self._problem(f"The folder {path.parent} does not exist")
            return
        if path.exists():
            def answer(replace: bool | None) -> None:
                if replace:
                    self.dismiss(path)

            self.app.push_screen(
                ConfirmDialog(f"{path.name} already exists. Replace it?", confirm="Replace",
                              danger=True),
                answer,
            )
            return
        self.dismiss(path)

    @on(Input.Submitted)
    def _submitted(self) -> None:
        self._go()

    @on(Input.Changed)
    def _changed(self) -> None:
        self._problem("")

    @on(Button.Pressed)
    def _pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "go":
            self._go()
        else:
            self.dismiss(None)


class ImportPreview(ModalScreen[bool]):
    """Show what an import would do before anything is written."""

    DEFAULT_CSS = """
    ImportPreview { align: center middle; }
    ImportPreview .dialog { width: 84; }
    ImportPreview #details { height: auto; max-height: 14; margin-top: 1; }
    """
    BINDINGS = [Binding("escape", "dismiss(False)", "Cancel")]

    def __init__(self, path: Path, result: ImportResult, fresh: list[Flight],
                 duplicates: list[Flight]) -> None:
        super().__init__()
        self._path = path
        self._result = result
        self._fresh = fresh
        self._duplicates = duplicates

    def compose(self) -> ComposeResult:
        fresh, duplicates, errors = (
            len(self._fresh), len(self._duplicates), len(self._result.errors)
        )
        summary = Text()
        summary.append(f"{self._path.name}\n\n", style="bold")
        summary.append(f"{fresh}", style="bold")
        summary.append(" new entry" if fresh == 1 else " new entries")
        summary.append(" will be added")
        if self._fresh:
            first = min(f.date for f in self._fresh)
            last = max(f.date for f in self._fresh)
            summary.append(f" ({first} to {last})")
        summary.append(".\n")
        if duplicates:
            summary.append(f"{duplicates} {'row is' if duplicates == 1 else 'rows are'} "
                           "already in your logbook and will be skipped.\n")
        if errors:
            summary.append(f"{errors} {'row has' if errors == 1 else 'rows have'} "
                           "problems and will be skipped.\n", style="bold")
        details = Text()
        for warning in self._result.warnings:
            details.append(f"Note: {warning}\n", style="italic")
        shown = self._result.errors[:50]
        for error in shown:
            details.append(f"{error}\n")
        if len(self._result.errors) > len(shown):
            details.append(f"... and {len(self._result.errors) - len(shown)} more\n")

        with Vertical(classes="dialog") as box:
            box.border_title = "Import from CSV"
            yield Static(summary)
            if details:
                with VerticalScroll(id="details"):
                    yield Static(details, classes="hint")
            with Horizontal(classes="buttons"):
                if self._fresh:
                    yield Button(f"Import {len(self._fresh)}", variant="primary", id="import",
                                 compact=True)
                yield Button("Cancel" if self._fresh else "Close", id="cancel", compact=True)

    @on(Button.Pressed)
    def _pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "import")


class SettingsDialog(ModalScreen[Optional[Settings]]):
    DEFAULT_CSS = """
    SettingsDialog { align: center middle; }
    SettingsDialog .dialog { width: 80; }
    SettingsDialog Label { margin-top: 1; text-style: bold; }
    SettingsDialog Select { width: 40; }
    SettingsDialog Checkbox { background: transparent; }
    SettingsDialog #files { margin-top: 1; }
    """
    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, settings: Settings, files: list[tuple[str, Path]]) -> None:
        super().__init__()
        self._settings = settings
        self._files = files

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog") as box:
            box.border_title = "Settings"
            yield Label("Show times as")
            yield Select(
                [("Hours and minutes (1:30)", HM), ("Decimal hours (1.5)", DECIMAL)],
                value=self._settings.time_format,
                allow_blank=False,
                id="time-format",
            )
            yield Label("Check currency for")
            for key, rules in RULES.items():
                yield Checkbox(rules.name, value=key in self._settings.rules, id=f"rules-{key}",
                               compact=True)
            yield Static("", id="problem", classes="error")
            files = Text()
            for label, path in self._files:
                files.append(f"{label}: ", style="bold")
                files.append(f"{path}\n")
            files.append("Change the colour theme with Ctrl+P, then 'Theme'.")
            yield Static(files, id="files", classes="hint")
            with Horizontal(classes="buttons"):
                yield Button("Save", variant="primary", id="save", compact=True)
                yield Button("Cancel", id="cancel", compact=True)

    @on(Button.Pressed)
    def _pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "save":
            self.dismiss(None)
            return
        rules = [key for key in RULES if self.query_one(f"#rules-{key}", Checkbox).value]
        if not rules:
            self.query_one("#problem", Static).update("Choose at least one authority")
            return
        self.dismiss(
            Settings(
                time_format=str(self.query_one("#time-format", Select).value),
                rules=rules,
                theme=self._settings.theme,
            )
        )


HELP_TEXT = """\
[b]Logbook[/b]
  a         add a flight
  Enter, e  edit the selected flight
  c         copy the selected flight (same aircraft and route)
  d         delete the selected flight
  /         search             Esc  clear the search
  1, 2, 3   Logbook, Totals and Currency tabs
  x, i      export to or import from a CSV file
  s         settings: time format and which rules to check
  q         quit

[b]Entering a flight[/b]
  All times are UTC. Type clock times as 0930, 930 or 09:30.
  The total is worked out from the off-block and on-block times
  (past midnight is fine), or you can type it yourself.
  Durations can be typed as 1:30, 1.5 or 130.
  Type [b]=[/b] in any time box to copy the total into it. A box that
  equals the total follows it when you change the times.
  A new flight starts from your last one: same aircraft and PIC,
  departing from where you last landed.
  Dates: t = today, y = yesterday, -3 = three days ago.
  → accepts a suggested airport, registration, type or name.
  Enter moves to the next box. Ctrl+S saves, Esc cancels.
  SP SE / SP ME: single- or multi-engine time; Multi-pilot: flown
  by a crew of two. PICUS: pilot in command under supervision.

[b]Previous logbooks[/b]
  To carry over totals from a paper logbook, add one entry with
  your totals and tick 'Brought forward'. It counts towards your
  totals but not towards currency or the recent-period totals.
"""


class HelpScreen(ModalScreen[None]):
    DEFAULT_CSS = "HelpScreen { align: center middle; } HelpScreen .dialog { width: 76; }"
    BINDINGS = [Binding("escape,q,question_mark,f1", "dismiss(None)", "Close")]

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="dialog") as box:
            box.border_title = "Help"
            box.border_subtitle = "Esc to close"
            yield Static(HELP_TEXT)
