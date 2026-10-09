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
from textual.widgets import Button, Checkbox, Input, Label, Select, Static, TextArea

from .config import Settings
from .csvio import ImportResult
from .layouts import LAYOUTS
from .models import Endorsement, Flight
from .stats import RULES
from .timeutil import DECIMAL, HM, parse_date

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
            yield Label("Logbook layout")
            yield Select(
                [(name, key) for key, name in LAYOUTS.items()],
                value=self._settings.layout,
                allow_blank=False,
                id="layout",
            )
            yield Label("Show times as")
            yield Select(
                [("Decimal hours (1.5)", DECIMAL), ("Hours and minutes (1:30)", HM)],
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
                layout=str(self.query_one("#layout", Select).value),
                theme=self._settings.theme,
            )
        )


class ParagraphInput(TextArea):
    """A box for a paragraph that wraps as it is typed; Enter moves on, as in an Input."""

    BINDINGS = [Binding("enter", "app.focus_next", "Next", show=False, priority=True)]


class EndorsementDialog(ModalScreen[Optional[Endorsement]]):
    """Add or edit an instructor's endorsement."""

    DEFAULT_CSS = """
    EndorsementDialog { align: center middle; }
    EndorsementDialog .dialog { width: 84; }
    EndorsementDialog .pair { height: auto; }
    EndorsementDialog .pair Vertical { height: auto; width: 1fr; margin-right: 2; }
    EndorsementDialog Label { color: $text-muted; margin-top: 1; }
    EndorsementDialog Input, EndorsementDialog ParagraphInput { background: $surface; }
    EndorsementDialog Input:focus, EndorsementDialog ParagraphInput:focus {
        background: $primary 35%;
    }
    EndorsementDialog ParagraphInput { height: 3; padding: 0; }
    """
    BINDINGS = [
        Binding("escape", "dismiss(None)", "Cancel"),
        Binding("ctrl+s", "save", "Save", priority=True),
    ]
    FIELDS = (
        ("date", "Date"),
        ("text", "Endorsement"),
        ("instructor", "Instructor"),
        ("licence", "Licence number"),
        ("designation", "Designation"),
        ("ato", "ATO name"),
        ("ato_number", "ATO number"),
    )

    def __init__(self, title: str, endorsement: Endorsement, today, on_save) -> None:
        super().__init__()
        self._title = title
        self._endorsement = endorsement
        self._today = today
        self._on_save = on_save

    def _input(self, name: str) -> Input | TextArea:
        value = getattr(self._endorsement, name)
        if name == "text":
            return ParagraphInput(value, id="e-text", compact=True, highlight_cursor_line=False)
        text = value.isoformat() if name == "date" else value
        return Input(text, id=f"e-{name}", compact=True)

    def compose(self) -> ComposeResult:
        labels = dict(self.FIELDS)
        with Vertical(classes="dialog") as box:
            box.border_title = self._title
            box.border_subtitle = "Ctrl+S save · Esc cancel"
            yield Label(labels["date"])
            yield self._input("date")
            yield Label(labels["text"])
            yield self._input("text")
            for left, right in (("instructor", "licence"), ("designation", "ato"),
                                ("ato_number", "")):
                with Horizontal(classes="pair"):
                    for name in (left, right):
                        with Vertical():
                            if name:
                                yield Label(labels[name])
                                yield self._input(name)
            yield Static("", id="problem", classes="error")
            with Horizontal(classes="buttons"):
                yield Button("Save", variant="primary", id="save", compact=True)
                yield Button("Cancel", id="cancel", compact=True)

    def on_mount(self) -> None:
        self.query_one("#e-date", Input).focus()

    @on(Input.Submitted)
    def _submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.focus_next()

    def action_save(self) -> None:
        values = {name: self.query_one(f"#e-{name}", Input).value.strip()
                  for name, _ in self.FIELDS if name != "text"}
        values["text"] = " ".join(self.query_one("#e-text", TextArea).text.split())
        try:
            day = parse_date(values.pop("date"), self._today)
        except ValueError as error:
            self.query_one("#problem", Static).update(f"Date: {error}")
            self.query_one("#e-date", Input).focus()
            return
        if not values["text"]:
            self.query_one("#problem", Static).update("Write what the endorsement says")
            self.query_one("#e-text", TextArea).focus()
            return
        endorsement = Endorsement(day, id=self._endorsement.id, **values)
        try:
            self._on_save(endorsement)
        except Exception as error:  # keep what was typed if the write fails
            self.query_one("#problem", Static).update(f"Could not save: {error}")
            return
        self.dismiss(endorsement)

    @on(Button.Pressed)
    def _pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self.action_save()
        else:
            self.dismiss(None)


HELP_TEXT = """\
[b]Keys[/b]
  a         add a flight (an endorsement, on that tab)
  Enter, e  edit the selected flight or endorsement
  c         copy it: a new flight in the same aircraft
  d         delete the selected flight or endorsement
  /         search             Esc  clear the search
  ←, →      scroll a wide logbook sideways
  1 to 4    Logbook, Totals, Currency and Endorsements tabs
  x, i      export to or import from a CSV file
  s         settings: layout, time format and rules to check
  q         quit

[b]Entering a flight[/b]
  All times are UTC. Type clock times as 0930, 930 or 09:30,
  and durations as 1.5, 1:30 or 130.
  In the SACAA layout, put the time in the column for your role:
  SE or ME, by day or night, as Dual, PIC, PICUS or Co-pilot.
  Type [b]=[/b] in one of those columns to copy the block time (from
  the off- and on-block times); in any other time box, = copies
  the flight time. A box that holds the whole flight follows it
  when you change the times.
  In the standard layout, the total comes from the block times,
  or you can type it; = copies the total.
  A new flight starts from your last one: same aircraft and PIC,
  departing from where you last landed.
  Dates: t = today, y = yesterday, -3 = three days ago.
  → accepts a suggested airport, registration, type or name.
  Enter moves to the next box. Ctrl+S saves, Esc cancels.
  SP SE / SP ME: single- or multi-engine time; Multi-pilot: flown
  by a crew of two. PICUS: pilot in command under supervision.

[b]Previous logbooks[/b]
  To carry over totals from a paper logbook, add an entry with
  your totals and tick 'Brought forward'. In the SACAA layout, add
  one for each row of the grid you use (SE day, SE night and so
  on). They count towards your totals but not towards currency
  or the recent-period totals.

[b]Endorsements[/b]
  Keep your instructors' endorsements on the Endorsements tab:
  solo and navigation authorisations, dual checks, skills tests.
"""


class HelpScreen(ModalScreen[None]):
    DEFAULT_CSS = "HelpScreen { align: center middle; } HelpScreen .dialog { width: 76; }"
    BINDINGS = [Binding("escape,q,question_mark,f1", "dismiss(None)", "Close")]

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="dialog") as box:
            box.border_title = "Help"
            box.border_subtitle = "Esc to close"
            yield Static(HELP_TEXT)
