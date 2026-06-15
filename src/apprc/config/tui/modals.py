"""Modal screens used by the storage-local config editor."""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# == 3rd Party ===============================
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, ProgressBar, Static

# == Internal ================================
from apprc.config.schema import ConfigField
from apprc.config.storage.archive import StorageArchiveProgress
from apprc.config.tui.field_state import (
    ConfigValueSource,
    ConfigValueSourceKey,
)
from apprc.config.tui.primitives import PathSuggester
from apprc.config.tui.styles import (
    LABEL_STYLE,
    MODAL_DIALOG_CLASS,
    MODAL_DIALOG_CSS,
    PATH_INPUT_CLASS,
    PATH_INPUT_CSS,
    env_key_text,
    label_value_text,
    lines_text,
    path_text,
)
from apprc.config.tui.value_modal_rendering import (
    config_value_source_key,
    field_type_text,
    local_input_classes,
    possible_values_text,
    shell_status_text,
    source_copy_is_disabled,
    source_label,
    source_label_text,
    source_origin_text,
    source_value_text,
)


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
    """Result returned when no live setup/editor default storage remains."""

    action: Literal["create", "leave"]
    path: Path | None = None


class ConfigValueEditScreen(ModalScreen[ValueEditResult | None]):
    """Modal editor for one storage-local value."""

    CSS = (
        """
    ConfigValueEditScreen {
        align: center middle;
    }

    #edit-dialog {
        width: 84;
    }

    #edit-title {
        height: 1;
    }

    #edit-env-key {
        height: 1;
    }

    #edit-details-scroll {
        height: 1fr;
        margin: 1 0;
        min-height: 1;
        scrollbar-size-vertical: 1;
    }

    #edit-metadata {
        height: auto;
        margin: 0 0 1 0;
    }

    .edit-metadata-row {
        height: 1;
    }

    .edit-metadata-label {
        width: 18;
    }

    .edit-metadata-value {
        width: 1fr;
    }

    #edit-explanation-panel {
        border: solid $border;
        height: auto;
        padding: 0 1;
        margin: 0;
    }

    #edit-explanation-title {
        height: 1;
    }

    #edit-long-explanation {
        height: auto;
        margin: 0;
    }

    #edit-source-panel {
        height: auto;
        margin: 0;
    }

    .edit-source-row {
        height: 1;
    }

    #edit-source-effective {
        height: 1;
    }

    .edit-source-label {
        width: 16;
    }

    .edit-source-value {
        width: 1fr;
    }

    .edit-source-origin {
        width: 16;
    }

    Button.edit-source-copy {
        border: none;
        height: 1;
        min-width: 8;
        padding: 0 1;
        width: 8;
    }

    Input.edit-local-input {
        border: none;
        height: 1;
        padding: 0 1;
        width: 1fr;
    }

    #edit-button-row {
        height: 3;
        margin-top: 1;
    }
    """
        + MODAL_DIALOG_CSS
        + PATH_INPUT_CSS
    )

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "save", "Save"),
    ]

    def __init__(
        self,
        *,
        spec: ConfigField,
        env_key: str,
        value_sources: Sequence[ConfigValueSource],
    ) -> None:
        """Store field metadata for modal rendering."""
        super().__init__()
        self.spec = spec
        self.env_key = env_key
        self.value_sources = tuple(value_sources)
        self.sources_by_key: dict[ConfigValueSourceKey, ConfigValueSource] = {
            source.key: source for source in self.value_sources
        }

    def compose(self) -> ComposeResult:
        """Compose field metadata, value input, and modal actions."""
        with Vertical(id="edit-dialog", classes=MODAL_DIALOG_CLASS):
            yield Static(
                Text(
                    self.spec.title or self.spec.name,
                    style="bold",
                ),
                id="edit-title",
            )
            yield Static(env_key_text(self.env_key), id="edit-env-key")
            with VerticalScroll(id="edit-details-scroll"):
                with Vertical(id="edit-metadata"):
                    with Horizontal(
                        id="edit-metadata-type",
                        classes="edit-metadata-row",
                    ):
                        yield Static(
                            Text("Type", style=LABEL_STYLE),
                            classes="edit-metadata-label",
                        )
                        yield Static(
                            field_type_text(self.spec),
                            id="edit-type-value",
                            classes="edit-metadata-value",
                        )
                    with Horizontal(
                        id="edit-metadata-possible-values",
                        classes="edit-metadata-row",
                    ):
                        yield Static(
                            Text("Possible values", style=LABEL_STYLE),
                            classes="edit-metadata-label",
                        )
                        yield Static(
                            possible_values_text(self.spec),
                            id="edit-possible-values-value",
                            classes="edit-metadata-value",
                        )
                    with Horizontal(
                        id="edit-metadata-shell",
                        classes="edit-metadata-row",
                    ):
                        yield Static(
                            Text("Shell environment", style=LABEL_STYLE),
                            classes="edit-metadata-label",
                        )
                        yield Static(
                            shell_status_text(self._source_by_key("shell")),
                            id="edit-shell-value",
                            classes="edit-metadata-value",
                        )
                with Vertical(id="edit-explanation-panel"):
                    yield Static(
                        Text("Explanation", style="bold"),
                        id="edit-explanation-title",
                    )
                    yield Static(
                        self.spec.explanation_long
                        or self.spec.explanation_short,
                        id="edit-long-explanation",
                    )
            with Vertical(id="edit-source-panel"):
                for source in self.value_sources:
                    yield from self._compose_source_row(source)
            with Horizontal(id="edit-button-row"):
                yield Button("Save", variant="primary", id="edit-save")
                yield Button("Clear Local", id="edit-clear")
                yield Button("Cancel", id="edit-cancel")

    def on_mount(self) -> None:
        """Focus the value input when the modal opens."""
        self.query_one("#edit-value-input", Input).focus()

    def _compose_source_row(
        self,
        source: ConfigValueSource,
    ) -> ComposeResult:
        """Compose one source-resolution row."""
        with Horizontal(
            id=f"edit-source-{source.key}",
            classes="edit-source-row",
        ):
            yield Static(
                source_label_text(source),
                id=f"edit-source-{source.key}-label",
                classes="edit-source-label",
            )
            if source.key == "local":
                yield Input(
                    value=self._local_value(),
                    placeholder="Local override value",
                    password=self.spec.secret,
                    id="edit-value-input",
                    classes=local_input_classes(self.spec),
                )
            else:
                yield Static(
                    source_value_text(self.spec, source),
                    id=f"edit-source-{source.key}-value",
                    classes="edit-source-value",
                )
            yield Static(
                source_origin_text(source),
                id=f"edit-source-{source.key}-origin",
                classes="edit-source-origin",
            )
            yield Button(
                "Copy",
                id=f"edit-copy-{source.key}",
                disabled=source_copy_is_disabled(
                    source,
                    local_input_value=self._local_value(),
                ),
                classes="edit-source-copy",
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle copy, save, clear, and cancel button actions."""
        if event.button.id is not None and event.button.id.startswith(
            "edit-copy-"
        ):
            self._copy_source(event.button.id.removeprefix("edit-copy-"))
            return
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

    def on_input_changed(self, event: Input.Changed) -> None:
        """Enable local copy once a new local value is visible."""
        if event.input.id != "edit-value-input":
            return
        local = self._source_by_key("local")
        if local is None:
            return
        self.query_one(
            "#edit-copy-local", Button
        ).disabled = source_copy_is_disabled(
            local, local_input_value=event.value
        )

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

    def _copy_source(self, source_key: str) -> None:
        """Copy one source value without dismissing the modal."""
        source = self._source_by_key(source_key)
        if source is None:
            self.notify("No value to copy.", severity="warning")
            return
        if source.key == "local":
            self._copy_local_source(source)
            return
        if source.raw_value is None:
            self.notify("No value to copy.", severity="warning")
            return
        self.app.copy_to_clipboard(source.raw_value)
        self.notify(f"Copied {source_label(source)}")

    def _copy_local_source(self, source: ConfigValueSource) -> None:
        """Copy the visible local input value."""
        raw_value = self.query_one("#edit-value-input", Input).value
        if raw_value == "" and not source.is_available:
            self.notify("No value to copy.", severity="warning")
            return
        self.app.copy_to_clipboard(raw_value)
        self.notify(f"Copied {source_label(source)}")

    def _source_by_key(self, source_key: str) -> ConfigValueSource | None:
        """Return one modal source by stable key."""
        resolved_key = config_value_source_key(source_key)
        if resolved_key is None:
            return None
        return self.sources_by_key.get(resolved_key)

    def _local_value(self) -> str:
        """Return the saved local value shown when the modal opens."""
        local = self._source_by_key("local")
        if local is None or local.raw_value is None:
            return ""
        return local.raw_value


class ArchiveOptionsScreen(ModalScreen[ArchiveOptionsResult | None]):
    """Modal for archive path and source deletion choice."""

    CSS = (
        """
    ArchiveOptionsScreen {
        align: center middle;
    }

    #archive-dialog {
        width: 82;
    }

    #archive-message {
        margin: 1 0;
    }

    #archive-button-row {
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
        with Vertical(id="archive-dialog", classes=MODAL_DIALOG_CLASS):
            yield Static(Text("Archive storage", style="bold"))
            yield Static(
                lines_text(
                    "Compressing can take a while. The live storage is "
                    "unchanged unless you choose to delete the source after "
                    "compression.",
                    label_value_text("Source", path_text(self.source_root)),
                ),
                id="archive-message",
            )
            yield Input(
                value=str(self.default_archive),
                placeholder="Archive path ending in *.apprc.tar.xz",
                suggester=PathSuggester(case_sensitive=True),
                id="archive-path-input",
                classes=PATH_INPUT_CLASS,
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

    CSS = (
        """
    DefaultPathScreen {
        align: center middle;
    }

    #default-path-dialog {
        width: 82;
    }

    #default-path-message {
        margin: 1 0;
    }

    #default-path-button-row {
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
        default_path: Path,
        display_name: str,
    ) -> None:
        """Store the suggested default data directory."""
        super().__init__()
        self.default_path = default_path
        self.display_name = display_name

    def compose(self) -> ComposeResult:
        """Compose the no-live-default dialog."""
        with Vertical(id="default-path-dialog", classes=MODAL_DIALOG_CLASS):
            yield Static(
                Text("No setup/editor default storage remains", style="bold")
            )
            yield Static(
                "Choose a replacement setup/editor default storage, or leave "
                f"{self.display_name} in an uninitialized state like a "
                "fresh install.",
                id="default-path-message",
            )
            yield Input(
                value=str(self.default_path),
                placeholder="Setup/editor default storage directory",
                suggester=PathSuggester(case_sensitive=True),
                id="default-path-input",
                classes=PATH_INPUT_CLASS,
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

    CSS = (
        """
    ProgressScreen {
        align: center middle;
    }

    #progress-dialog {
        width: 78;
    }

    #progress-path {
        margin-top: 1;
    }
    """
        + MODAL_DIALOG_CSS
    )

    def __init__(self, *, title: str) -> None:
        """Store the title shown above the progress bar."""
        super().__init__()
        self.dialog_title = title

    def compose(self) -> ComposeResult:
        """Compose the progress dialog."""
        with Vertical(id="progress-dialog", classes=MODAL_DIALOG_CLASS):
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
        self.query_one("#progress-path", Static).update(
            path_text(progress.path)
        )
