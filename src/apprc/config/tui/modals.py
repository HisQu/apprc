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
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, ProgressBar, Static

# == Internal ================================
from apprc.config.schema import ConfigField, ConfigOwner
from apprc.config.storage.archive import StorageArchiveProgress
from apprc.config.tui.field_state import (
    ConfigResolvedSourceKey,
    ConfigValueSource,
)
from apprc.config.tui.primitives import PathSuggester
from apprc.config.tui.rendering import (
    field_type_label,
    possible_values_label,
)
from apprc.config.tui.styles import (
    BOOL_STYLE,
    CHOICE_STYLE,
    DEFAULT_STYLE,
    ERROR_STYLE,
    LABEL_STYLE,
    NUMBER_STYLE,
    PATH_INPUT_CLASS,
    PATH_STYLE,
    SECRET_STYLE,
    TEXT_STYLE,
    env_key_text,
    label_value_text,
    lines_text,
    path_text,
)

EFFECTIVE_SOURCE_STYLE = f"bold {ERROR_STYLE}"
GENERIC_VALUE_STYLE = "dim italic"
SOURCE_ORIGIN_LABELS: dict[ConfigResolvedSourceKey, str] = {
    "shell": "Shell",
    "local": "Local",
    "shared": "Shared default",
}


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

    CSS = """
    ConfigValueEditScreen {
        align: center middle;
    }

    #edit-dialog {
        width: 84;
        max-width: 95%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #edit-metadata {
        margin: 1 0;
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
        padding: 0 1;
        margin: 1 0;
    }

    #edit-explanation-title {
        height: 1;
    }

    #edit-long-explanation {
        height: auto;
        margin: 0;
    }

    #edit-source-panel {
        margin: 1 0;
    }

    .edit-source-row {
        height: 1;
    }

    #edit-source-effective {
        border: solid $error;
        height: 3;
        margin-bottom: 1;
        padding: 0 1;
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

    Input.path-input {
        color: cyan;
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
        value_sources: Sequence[ConfigValueSource],
    ) -> None:
        """Store field metadata for modal rendering."""
        super().__init__()
        self.owner = owner
        self.spec = spec
        self.env_key = env_key
        self.local_value = local_value
        self.env_is_set = env_is_set
        self.value_sources = tuple(value_sources)

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
            yield Static(env_key_text(self.env_key), id="edit-env-key")
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
                        self._type_value_text(),
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
                        self._possible_values_text(),
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
                        self._shell_status_text(),
                        id="edit-shell-value",
                        classes="edit-metadata-value",
                    )
            with Vertical(id="edit-explanation-panel"):
                yield Static(
                    Text("Explanation", style="bold"),
                    id="edit-explanation-title",
                )
                yield Static(
                    self.spec.explanation_long or self.spec.explanation_short,
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
                self._source_label_text(source),
                id=f"edit-source-{source.key}-label",
                classes="edit-source-label",
            )
            if source.key == "local":
                yield Input(
                    value=self.local_value,
                    placeholder="Local override value",
                    password=self.spec.secret,
                    id="edit-value-input",
                    classes=self._local_input_classes(),
                )
            else:
                yield Static(
                    self._source_value_text(source),
                    id=f"edit-source-{source.key}-value",
                    classes="edit-source-value",
                )
            yield Static(
                self._source_origin_text(source),
                id=f"edit-source-{source.key}-origin",
                classes="edit-source-origin",
            )
            yield Button(
                "Copy",
                id=f"edit-copy-{source.key}",
                disabled=self._copy_button_is_disabled(source),
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
        self.query_one("#edit-copy-local", Button).disabled = (
            event.value == "" and not local.is_available
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
        self.notify(f"Copied {source.label}")

    def _copy_local_source(self, source: ConfigValueSource) -> None:
        """Copy the visible local input value."""
        raw_value = self.query_one("#edit-value-input", Input).value
        if raw_value == "" and not source.is_available:
            self.notify("No value to copy.", severity="warning")
            return
        self.app.copy_to_clipboard(raw_value)
        self.notify(f"Copied {source.label}")

    def _source_value_text(self, source: ConfigValueSource) -> Text:
        """Return redacted or styled text for one source row."""
        if source.raw_value is None:
            return Text(
                "missing" if source.key in {"effective", "shared"} else "unset",
                style=(
                    EFFECTIVE_SOURCE_STYLE
                    if source.key == "effective"
                    else LABEL_STYLE
                ),
            )
        if source.raw_value == "":
            return Text(
                "<empty>",
                style=(
                    EFFECTIVE_SOURCE_STYLE
                    if source.key == "effective"
                    else LABEL_STYLE
                ),
            )
        if self.spec.secret:
            return Text(
                "<secret>",
                style=(
                    EFFECTIVE_SOURCE_STYLE
                    if source.key == "effective"
                    else SECRET_STYLE
                ),
            )
        return Text(
            source.raw_value,
            style=(
                EFFECTIVE_SOURCE_STYLE
                if source.key == "effective"
                else self._type_style()
            ),
        )

    def _type_value_text(self) -> Text:
        """Return the field type with type-specific color."""
        return Text(field_type_label(self.spec), style=self._type_style())

    def _possible_values_text(self) -> Text:
        """Return accepted values with literal and choice styling."""
        style = CHOICE_STYLE if self.spec.choices else GENERIC_VALUE_STYLE
        return Text(possible_values_label(self.spec), style=style)

    def _shell_status_text(self) -> Text:
        """Return current shell status with quiet or active styling."""
        if self.env_is_set:
            return Text("set", style=DEFAULT_STYLE)
        return Text("unset", style=LABEL_STYLE)

    def _source_label_text(self, source: ConfigValueSource) -> Text:
        """Return the source label with Effective emphasized."""
        if source.key == "effective":
            return Text(source.label, style=EFFECTIVE_SOURCE_STYLE)
        return Text(source.label, style=LABEL_STYLE)

    def _source_origin_text(self, source: ConfigValueSource) -> Text:
        """Return the concrete origin for the effective source row."""
        if source.key != "effective" or source.origin_key is None:
            return Text("")
        return Text(
            f"from {SOURCE_ORIGIN_LABELS[source.origin_key]}",
            style=LABEL_STYLE,
        )

    def _copy_button_is_disabled(self, source: ConfigValueSource) -> bool:
        """Return whether a copy button should start disabled."""
        if source.key == "local":
            return not source.is_available and self.local_value == ""
        return not source.is_available

    def _source_by_key(self, source_key: str) -> ConfigValueSource | None:
        """Return one modal source by stable key."""
        return next(
            (
                candidate
                for candidate in self.value_sources
                if candidate.key == source_key
            ),
            None,
        )

    def _local_input_classes(self) -> str:
        """Return CSS classes for the embedded local override input."""
        classes = ["edit-local-input"]
        if self.spec.python_type is Path:
            classes.append(PATH_INPUT_CLASS)
        return " ".join(classes)

    def _type_style(self) -> str:
        """Return the color used for values governed by the declared type."""
        if self.spec.python_type is bool:
            return BOOL_STYLE
        if self.spec.python_type in {int, float}:
            return NUMBER_STYLE
        if self.spec.python_type is Path:
            return PATH_STYLE
        return TEXT_STYLE


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

    Input.path-input {
        color: cyan;
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

    Input.path-input {
        color: cyan;
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
        self.query_one("#progress-path", Static).update(
            path_text(progress.path)
        )
