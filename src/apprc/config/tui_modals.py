"""Modal screens used by the storage-local config editor."""

from __future__ import annotations

# == Standard Library ========================
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# == 3rd Party ===============================
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, ProgressBar, Static

# == Internal ================================
from apprc.config.schema import ConfigField, ConfigOwner
from apprc.config.storage_archive import StorageArchiveProgress
from apprc.config.tui_primitives import PathSuggester
from apprc.config.tui_rendering import field_type_label, possible_values_label


@dataclass(frozen=True, slots=True)
class ValueEditResult:
    """Result returned by the config value edit modal."""

    action: Literal["save", "clear"]
    env_key: str
    raw_value: str


@dataclass(frozen=True, slots=True)
class ArchiveOptionsResult:
    """Archive options selected by the user."""

    archive_path: Path
    delete_source: bool


@dataclass(frozen=True, slots=True)
class DefaultPathResult:
    """Result returned when no live default storage remains."""

    action: Literal["create", "leave"]
    path: Path | None = None


class ConfigValueEditScreen(ModalScreen[ValueEditResult | None]):
    """Modal editor for one storage-local value."""

    CSS = """
    ConfigValueEditScreen {
        align: center middle;
    }

    #edit-dialog {
        width: 78;
        max-width: 95%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #edit-long-explanation {
        height: 5;
        margin: 1 0;
    }

    #edit-button-row {
        height: 3;
        margin-top: 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "save", "Save"),
    ]

    def __init__(
        self,
        *,
        owner: ConfigOwner,
        spec: ConfigField,
        env_key: str,
        local_value: str,
        env_is_set: bool,
    ) -> None:
        """Store field metadata for modal rendering."""
        super().__init__()
        self.owner = owner
        self.spec = spec
        self.env_key = env_key
        self.local_value = local_value
        self.env_is_set = env_is_set

    def compose(self) -> ComposeResult:
        """Compose field metadata, value input, and modal actions."""
        with Vertical(id="edit-dialog"):
            yield Static(
                Text(
                    self.spec.title or self.spec.name,
                    style="bold",
                ),
                id="edit-title",
            )
            yield Static(self.env_key, id="edit-env-key")
            yield Static(
                "\n".join(
                    (
                        f"Type: {field_type_label(self.spec)}",
                        f"Possible values: {possible_values_label(self.spec)}",
                        "Shell environment: "
                        + ("set" if self.env_is_set else "unset"),
                    )
                ),
                id="edit-metadata",
            )
            yield Static(
                self.spec.explanation_long or self.spec.explanation_short,
                id="edit-long-explanation",
            )
            yield Input(
                value=self.local_value,
                placeholder="Local override value",
                password=self.spec.secret,
                id="edit-value-input",
            )
            with Horizontal(id="edit-button-row"):
                yield Button("Save", variant="primary", id="edit-save")
                yield Button("Clear Local", id="edit-clear")
                yield Button("Cancel", id="edit-cancel")

    def on_mount(self) -> None:
        """Focus the value input when the modal opens."""
        self.query_one("#edit-value-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Dismiss the modal with the selected action."""
        if event.button.id == "edit-save":
            self.action_save()
            return
        if event.button.id == "edit-clear":
            self.dismiss(
                ValueEditResult(
                    action="clear",
                    env_key=self.env_key,
                    raw_value="",
                )
            )
            return
        if event.button.id == "edit-cancel":
            self.action_cancel()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Save when Enter is submitted from the value input."""
        if event.input.id == "edit-value-input":
            self.action_save()

    def action_save(self) -> None:
        """Dismiss with the current input value."""
        raw_value = self.query_one("#edit-value-input", Input).value
        self.dismiss(
            ValueEditResult(
                action="save",
                env_key=self.env_key,
                raw_value=raw_value,
            )
        )

    def action_cancel(self) -> None:
        """Dismiss without applying a change."""
        self.dismiss(None)


class ArchiveOptionsScreen(ModalScreen[ArchiveOptionsResult | None]):
    """Modal for archive path and source deletion choice."""

    CSS = """
    ArchiveOptionsScreen {
        align: center middle;
    }

    #archive-dialog {
        width: 82;
        max-width: 95%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #archive-message {
        margin: 1 0;
    }

    #archive-button-row {
        height: 3;
        margin-top: 1;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        *,
        storage_name: str,
        source_root: Path,
        default_archive: Path,
    ) -> None:
        """Store archive defaults for the selected storage."""
        super().__init__()
        self.storage_name = storage_name
        self.source_root = source_root
        self.default_archive = default_archive
        self.delete_source = False

    def compose(self) -> ComposeResult:
        """Compose the archive options dialog."""
        with Vertical(id="archive-dialog"):
            yield Static(Text("Archive storage", style="bold"))
            yield Static(
                "Compressing can take a while. The live storage is unchanged "
                "unless you choose to delete the source after compression.\n"
                f"Source: {self.source_root}",
                id="archive-message",
            )
            yield Input(
                value=str(self.default_archive),
                placeholder="Archive path ending in *.apprc.tar.xz",
                suggester=PathSuggester(case_sensitive=True),
                id="archive-path-input",
            )
            with Horizontal(id="archive-button-row"):
                yield Button("Archive", variant="primary", id="archive-run")
                yield Button(
                    "Delete source: no",
                    id="archive-toggle-delete",
                )
                yield Button("Cancel", id="archive-cancel")

    def on_mount(self) -> None:
        """Focus the archive path input."""
        self.query_one("#archive-path-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle archive option buttons."""
        if event.button.id == "archive-run":
            self._run()
            return
        if event.button.id == "archive-toggle-delete":
            self.delete_source = not self.delete_source
            label = (
                "Delete source: yes"
                if self.delete_source
                else "Delete source: no"
            )
            event.button.label = label
            return
        if event.button.id == "archive-cancel":
            self.action_cancel()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Archive when Enter is submitted from the path input."""
        if event.input.id == "archive-path-input":
            self._run()

    def _run(self) -> None:
        """Dismiss with archive options when the path is valid enough."""
        path_text = self.query_one("#archive-path-input", Input).value.strip()
        if not path_text:
            self.notify("Enter an archive path first.", severity="warning")
            return
        self.dismiss(
            ArchiveOptionsResult(
                archive_path=Path(path_text),
                delete_source=self.delete_source,
            )
        )

    def action_cancel(self) -> None:
        """Dismiss without archiving."""
        self.dismiss(None)


class DefaultPathScreen(ModalScreen[DefaultPathResult | None]):
    """Prompt for a new default path when no live storages remain."""

    CSS = """
    DefaultPathScreen {
        align: center middle;
    }

    #default-path-dialog {
        width: 82;
        max-width: 95%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #default-path-message {
        margin: 1 0;
    }

    #default-path-button-row {
        height: 3;
        margin-top: 1;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        *,
        default_path: Path,
        display_name: str,
    ) -> None:
        """Store the suggested default data directory."""
        super().__init__()
        self.default_path = default_path
        self.display_name = display_name

    def compose(self) -> ComposeResult:
        """Compose the no-live-default dialog."""
        with Vertical(id="default-path-dialog"):
            yield Static(Text("No default storage remains", style="bold"))
            yield Static(
                "Choose a replacement default storage, or leave "
                f"{self.display_name} in an uninitialized state like a "
                "fresh install.",
                id="default-path-message",
            )
            yield Input(
                value=str(self.default_path),
                placeholder="Default storage directory",
                suggester=PathSuggester(case_sensitive=True),
                id="default-path-input",
            )
            with Horizontal(id="default-path-button-row"):
                yield Button(
                    "Create default", variant="primary", id="default-create"
                )
                yield Button("Leave no default", id="default-leave")
                yield Button("Cancel", id="default-cancel")

    def on_mount(self) -> None:
        """Focus the default path input."""
        self.query_one("#default-path-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle default replacement buttons."""
        if event.button.id == "default-create":
            path_text = self.query_one(
                "#default-path-input", Input
            ).value.strip()
            if not path_text:
                self.notify("Enter a default path first.", severity="warning")
                return
            self.dismiss(
                DefaultPathResult(action="create", path=Path(path_text))
            )
            return
        if event.button.id == "default-leave":
            self.dismiss(DefaultPathResult(action="leave"))
            return
        if event.button.id == "default-cancel":
            self.action_cancel()

    def action_cancel(self) -> None:
        """Dismiss without changing the default."""
        self.dismiss(None)


class ProgressScreen(ModalScreen[None]):
    """Modal progress bar for archive operations."""

    CSS = """
    ProgressScreen {
        align: center middle;
    }

    #progress-dialog {
        width: 78;
        max-width: 95%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #progress-path {
        margin-top: 1;
    }
    """

    def __init__(self, *, title: str) -> None:
        """Store the title shown above the progress bar."""
        super().__init__()
        self.dialog_title = title

    def compose(self) -> ComposeResult:
        """Compose the progress dialog."""
        with Vertical(id="progress-dialog"):
            yield Static(
                Text(self.dialog_title, style="bold"),
                id="progress-title",
            )
            yield ProgressBar(total=1, id="progress-bar")
            yield Static("", id="progress-path")

    def update_progress(self, progress: StorageArchiveProgress) -> None:
        """Refresh the bar and current path label."""
        bar = self.query_one("#progress-bar", ProgressBar)
        total = max(progress.total, 1)
        bar.update(total=total, progress=progress.completed)
        self.query_one("#progress-path", Static).update(str(progress.path))
