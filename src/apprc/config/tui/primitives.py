"""Shared Textual widgets for AppRC config workflows."""

from __future__ import annotations

# == Standard Library ========================
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# == 3rd Party ===============================
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.suggester import Suggester
from textual.visual import VisualType
from textual.widgets import Button, Input, Static

# == Internal ================================
from apprc.config.tui.styles import (
    MODAL_DIALOG_CLASS,
    MODAL_DIALOG_CSS,
    PATH_INPUT_CLASS,
    PATH_INPUT_CSS,
)

ButtonVariant = Literal["default", "primary", "success", "warning", "error"]


@dataclass(frozen=True, slots=True)
class PathInputResult:
    """Path text returned by a modal input.

    :param path: Path entered by the user, before caller-specific validation.
    """

    path: Path


@dataclass(frozen=True, slots=True)
class StorageNameResult:
    """Storage name returned by the name modal.

    :param name: Registry selector entered by the user.
    """

    name: str


class PathSuggester(Suggester):
    """Complete filesystem paths inside Textual input widgets."""

    async def get_suggestion(self, value: str) -> str | None:
        """Return the first matching filesystem path completion.

        :param value: Current input value.
        :return: Completed path text, or ``None`` when nothing matches.
        """
        if not value:
            return None
        text = value.strip()
        expanded = Path(text).expanduser()
        parent = expanded if text.endswith(os.sep) else expanded.parent
        prefix = "" if text.endswith(os.sep) else expanded.name
        if not parent.is_dir():
            return None
        for child in sorted(parent.iterdir(), key=lambda item: item.name):
            if not child.name.startswith(prefix):
                continue
            suggestion = str(child)
            if text.startswith("~"):
                home = str(Path.home())
                suggestion = suggestion.replace(home, "~", 1)
            if child.is_dir():
                suggestion += os.sep
            return suggestion
        return None


class PathInputScreen(ModalScreen[PathInputResult | None]):
    """Modal path input with filesystem suggestions."""

    CSS = (
        """
    PathInputScreen {
        align: center middle;
    }

    #path-dialog {
        width: 82;
    }

    #path-message {
        margin: 1 0;
    }

    #path-button-row {
        height: 3;
        margin-top: 1;
    }
    """
        + MODAL_DIALOG_CSS
        + PATH_INPUT_CSS
    )

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        *,
        title: str,
        message: VisualType,
        placeholder: str,
        value: str = "",
    ) -> None:
        """Store input labels and the prefilled path text.

        :param title: Dialog title.
        :param message: Help text or Rich renderable shown above the input.
        :param placeholder: Placeholder when the input is empty.
        :param value: Prefilled path text.
        """
        super().__init__()
        self.dialog_title = title
        self.message = message
        self.placeholder = placeholder
        self.value = value

    def compose(self) -> ComposeResult:
        """Compose the path input dialog.

        :return: Textual widgets for the modal.
        """
        with Vertical(id="path-dialog", classes=MODAL_DIALOG_CLASS):
            yield Static(Text(self.dialog_title, style="bold"), id="path-title")
            yield Static(self.message, id="path-message")
            yield Input(
                value=self.value,
                placeholder=self.placeholder,
                suggester=PathSuggester(case_sensitive=True),
                id="path-input",
                classes=PATH_INPUT_CLASS,
            )
            with Horizontal(id="path-button-row"):
                yield Button("Continue", variant="primary", id="path-continue")
                yield Button("Cancel", id="path-cancel")

    def on_mount(self) -> None:
        """Focus the path input when the modal opens."""
        self.query_one("#path-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Continue when Enter is submitted from the path input.

        :param event: Textual input event.
        """
        if event.input.id == "path-input":
            self._continue()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle dialog button clicks.

        :param event: Textual button event.
        """
        if event.button.id == "path-continue":
            self._continue()
            return
        if event.button.id == "path-cancel":
            self.action_cancel()

    def _continue(self) -> None:
        """Dismiss with the typed path when it is not empty."""
        value = self.query_one("#path-input", Input).value.strip()
        if not value:
            self.notify("Enter a path first.", severity="warning")
            return
        self.dismiss(PathInputResult(path=Path(value)))

    def action_cancel(self) -> None:
        """Dismiss without choosing a path."""
        self.dismiss(None)


class StorageNameScreen(ModalScreen[StorageNameResult | None]):
    """Modal storage-name input."""

    CSS = (
        """
    StorageNameScreen {
        align: center middle;
    }

    #name-dialog {
        width: 64;
    }

    #name-message {
        margin: 1 0;
    }

    #name-button-row {
        height: 3;
        margin-top: 1;
    }
    """
        + MODAL_DIALOG_CSS
    )

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        *,
        default_name: str,
        message: VisualType,
    ) -> None:
        """Store the default storage name and helper text.

        :param default_name: Prefilled registry selector.
        :param message: Help text or Rich renderable shown above the input.
        """
        super().__init__()
        self.default_name = default_name
        self.message = message

    def compose(self) -> ComposeResult:
        """Compose the storage name dialog.

        :return: Textual widgets for the modal.
        """
        with Vertical(id="name-dialog", classes=MODAL_DIALOG_CLASS):
            yield Static(Text("Storage name", style="bold"), id="name-title")
            yield Static(self.message, id="name-message")
            yield Input(value=self.default_name, id="name-input")
            with Horizontal(id="name-button-row"):
                yield Button("Continue", variant="primary", id="name-continue")
                yield Button("Cancel", id="name-cancel")

    def on_mount(self) -> None:
        """Focus the name input when the modal opens."""
        self.query_one("#name-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Continue when Enter is submitted from the name input.

        :param event: Textual input event.
        """
        if event.input.id == "name-input":
            self._continue()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle dialog button clicks.

        :param event: Textual button event.
        """
        if event.button.id == "name-continue":
            self._continue()
            return
        if event.button.id == "name-cancel":
            self.action_cancel()

    def _continue(self) -> None:
        """Dismiss with the typed storage name when it is not empty."""
        name = self.query_one("#name-input", Input).value.strip()
        if not name:
            self.notify("Enter a storage name first.", severity="warning")
            return
        self.dismiss(StorageNameResult(name=name))

    def action_cancel(self) -> None:
        """Dismiss without choosing a name."""
        self.dismiss(None)


class ConfirmScreen(ModalScreen[str | None]):
    """Generic confirmation dialog with caller-defined actions."""

    CSS = (
        """
    ConfirmScreen {
        align: center middle;
    }

    #confirm-dialog {
        width: 82;
    }

    #confirm-message {
        margin: 1 0;
    }

    #confirm-button-row {
        height: auto;
        margin-top: 1;
    }
    """
        + MODAL_DIALOG_CSS
    )

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        *,
        title: str,
        message: VisualType,
        actions: tuple[tuple[str, str, ButtonVariant], ...],
    ) -> None:
        """Store confirmation text and ``(id, label, variant)`` actions.

        :param title: Dialog title.
        :param message: Question, warning, or Rich renderable shown above
            action buttons.
        :param actions: Button IDs, labels, and Textual variants.
        """
        super().__init__()
        self.dialog_title = title
        self.message = message
        self.actions = actions

    def compose(self) -> ComposeResult:
        """Compose the confirmation dialog.

        :return: Textual widgets for the modal.
        """
        with Vertical(id="confirm-dialog", classes=MODAL_DIALOG_CLASS):
            yield Static(
                Text(self.dialog_title, style="bold"),
                id="confirm-title",
            )
            yield Static(self.message, id="confirm-message")
            with Horizontal(id="confirm-button-row"):
                for action_id, label, variant in self.actions:
                    yield Button(label, variant=variant, id=action_id)
                yield Button("Cancel", id="confirm-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Dismiss with the selected action id.

        :param event: Textual button event.
        """
        if event.button.id == "confirm-cancel":
            self.action_cancel()
            return
        self.dismiss(str(event.button.id))

    def action_cancel(self) -> None:
        """Dismiss without confirming."""
        self.dismiss(None)
