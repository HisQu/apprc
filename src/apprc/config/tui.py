"""Interactive Textual editor for storage-local config overrides.

Applications declare config fields once through :mod:`apprc.config.schema`.
This module turns those declarations into a terminal UI that selects one
registered storage root, reads that storage's local dotenv file, and edits
only the values owned by the local override layer.

Rendering rules for table cells live in :mod:`apprc.config.tui_rendering` so
the widget code here stays focused on Textual events, modal handling, and file
persistence.
"""

from __future__ import annotations

# == Standard Library ========================
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

# == 3rd Party ===============================
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.suggester import Suggester
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    ProgressBar,
    Static,
)
from rich.text import Text

# == Internal ================================
from apprc.config.local_env import (
    local_env_path,
    normalize_env_value,
    read_local_env,
    write_local_env,
)
from apprc.config.paths import normalize_storage_root_path
from apprc.config.schema import (
    ConfigField,
    ConfigOwner,
    find_field_by_env_key,
)
from apprc.config.storage_archive import (
    StorageArchiveProgress,
    archive_directory,
    extract_archive,
    is_storage_archive_path,
    storage_archive_default_path,
    storage_root_name_from_archive,
)
from apprc.config.storage_registry import (
    StorageRecord,
    StorageRegistry,
)
from apprc.config.tui_rendering import (
    FIELD_TABLE_COLUMNS,
    build_field_table_rows,
    field_type_label,
    possible_values_label,
)

if TYPE_CHECKING:
    from apprc.config.kit import AppConfigKit

ButtonVariant = Literal["default", "primary", "success", "warning", "error"]


@dataclass(frozen=True, slots=True)
class _SelectedField:
    """One field selected by env key in the editor table."""

    owner: ConfigOwner
    spec: ConfigField


@dataclass(frozen=True, slots=True)
class _ValueEditResult:
    """Result returned by the edit modal."""

    action: Literal["save", "clear"]
    env_key: str
    raw_value: str


@dataclass(frozen=True, slots=True)
class _StorageListEntry:
    """One selectable row in the storage list."""

    kind: Literal["live", "archived"]
    name: str


@dataclass(frozen=True, slots=True)
class _PathInputResult:
    """Path text returned by a modal input."""

    path: Path


@dataclass(frozen=True, slots=True)
class _StorageNameResult:
    """Storage name returned by the name modal."""

    name: str


@dataclass(frozen=True, slots=True)
class _ArchiveOptionsResult:
    """Archive options selected by the user."""

    archive_path: Path
    delete_source: bool


@dataclass(frozen=True, slots=True)
class _DefaultPathResult:
    """Result returned when no live default storage remains."""

    action: Literal["create", "leave"]
    path: Path | None = None


@dataclass(frozen=True, slots=True)
class _RemovalDefaultChoice:
    """Default replacement chosen before removing a live storage."""

    replacement_name: str | None = None
    create_default_path: Path | None = None


class _PathSuggester(Suggester):
    """Complete filesystem paths inside Textual input widgets."""

    async def get_suggestion(self, value: str) -> str | None:
        """Return the first matching filesystem path completion."""
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


class _ConfigValueEditScreen(ModalScreen[_ValueEditResult | None]):
    """Modal editor for one storage-local value."""

    CSS = """
    _ConfigValueEditScreen {
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

    def on_button_pressed(self, event: Any) -> None:
        """Dismiss the modal with the selected action."""
        if event.button.id == "edit-save":
            self.action_save()
            return
        if event.button.id == "edit-clear":
            self.dismiss(
                _ValueEditResult(
                    action="clear",
                    env_key=self.env_key,
                    raw_value="",
                )
            )
            return
        if event.button.id == "edit-cancel":
            self.action_cancel()

    def on_input_submitted(self, event: Any) -> None:
        """Save when Enter is submitted from the value input."""
        if event.input.id == "edit-value-input":
            self.action_save()

    def action_save(self) -> None:
        """Dismiss with the current input value."""
        raw_value = self.query_one("#edit-value-input", Input).value
        self.dismiss(
            _ValueEditResult(
                action="save",
                env_key=self.env_key,
                raw_value=raw_value,
            )
        )

    def action_cancel(self) -> None:
        """Dismiss without applying a change."""
        self.dismiss(None)


class _PathInputScreen(ModalScreen[_PathInputResult | None]):
    """Modal path input with filesystem suggestions."""

    CSS = """
    _PathInputScreen {
        align: center middle;
    }

    #path-dialog {
        width: 82;
        max-width: 95%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #path-message {
        margin: 1 0;
    }

    #path-button-row {
        height: 3;
        margin-top: 1;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        *,
        title: str,
        message: str,
        placeholder: str,
        value: str = "",
    ) -> None:
        """Store input labels and the prefilled path text."""
        super().__init__()
        self.dialog_title = title
        self.message = message
        self.placeholder = placeholder
        self.value = value

    def compose(self) -> ComposeResult:
        """Compose the path input dialog."""
        with Vertical(id="path-dialog"):
            yield Static(Text(self.dialog_title, style="bold"), id="path-title")
            yield Static(self.message, id="path-message")
            yield Input(
                value=self.value,
                placeholder=self.placeholder,
                suggester=_PathSuggester(case_sensitive=True),
                id="path-input",
            )
            with Horizontal(id="path-button-row"):
                yield Button("Continue", variant="primary", id="path-continue")
                yield Button("Cancel", id="path-cancel")

    def on_mount(self) -> None:
        """Focus the path input when the modal opens."""
        self.query_one("#path-input", Input).focus()

    def on_input_submitted(self, event: Any) -> None:
        """Continue when Enter is submitted from the path input."""
        if event.input.id == "path-input":
            self._continue()

    def on_button_pressed(self, event: Any) -> None:
        """Handle dialog button clicks."""
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
        self.dismiss(_PathInputResult(path=Path(value)))

    def action_cancel(self) -> None:
        """Dismiss without choosing a path."""
        self.dismiss(None)


class _StorageNameScreen(ModalScreen[_StorageNameResult | None]):
    """Modal storage-name input."""

    CSS = """
    _StorageNameScreen {
        align: center middle;
    }

    #name-dialog {
        width: 64;
        max-width: 95%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #name-message {
        margin: 1 0;
    }

    #name-button-row {
        height: 3;
        margin-top: 1;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, *, default_name: str, message: str) -> None:
        """Store the default storage name and helper text."""
        super().__init__()
        self.default_name = default_name
        self.message = message

    def compose(self) -> ComposeResult:
        """Compose the storage name dialog."""
        with Vertical(id="name-dialog"):
            yield Static(Text("Storage name", style="bold"), id="name-title")
            yield Static(self.message, id="name-message")
            yield Input(value=self.default_name, id="name-input")
            with Horizontal(id="name-button-row"):
                yield Button("Continue", variant="primary", id="name-continue")
                yield Button("Cancel", id="name-cancel")

    def on_mount(self) -> None:
        """Focus the name input when the modal opens."""
        self.query_one("#name-input", Input).focus()

    def on_input_submitted(self, event: Any) -> None:
        """Continue when Enter is submitted from the name input."""
        if event.input.id == "name-input":
            self._continue()

    def on_button_pressed(self, event: Any) -> None:
        """Handle dialog button clicks."""
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
        self.dismiss(_StorageNameResult(name=name))

    def action_cancel(self) -> None:
        """Dismiss without choosing a name."""
        self.dismiss(None)


class _ConfirmScreen(ModalScreen[str | None]):
    """Generic confirmation dialog with caller-defined actions."""

    CSS = """
    _ConfirmScreen {
        align: center middle;
    }

    #confirm-dialog {
        width: 82;
        max-width: 95%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #confirm-message {
        margin: 1 0;
    }

    #confirm-button-row {
        height: auto;
        margin-top: 1;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        *,
        title: str,
        message: str,
        actions: tuple[tuple[str, str, ButtonVariant], ...],
    ) -> None:
        """Store confirmation text and ``(id, label, variant)`` actions."""
        super().__init__()
        self.dialog_title = title
        self.message = message
        self.actions = actions

    def compose(self) -> ComposeResult:
        """Compose the confirmation dialog."""
        with Vertical(id="confirm-dialog"):
            yield Static(
                Text(self.dialog_title, style="bold"),
                id="confirm-title",
            )
            yield Static(self.message, id="confirm-message")
            with Horizontal(id="confirm-button-row"):
                for action_id, label, variant in self.actions:
                    yield Button(label, variant=variant, id=action_id)
                yield Button("Cancel", id="confirm-cancel")

    def on_button_pressed(self, event: Any) -> None:
        """Dismiss with the selected action id."""
        if event.button.id == "confirm-cancel":
            self.action_cancel()
            return
        self.dismiss(str(event.button.id))

    def action_cancel(self) -> None:
        """Dismiss without confirming."""
        self.dismiss(None)


class _ArchiveOptionsScreen(ModalScreen[_ArchiveOptionsResult | None]):
    """Modal for archive path and source deletion choice."""

    CSS = """
    _ArchiveOptionsScreen {
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
                suggester=_PathSuggester(case_sensitive=True),
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

    def on_button_pressed(self, event: Any) -> None:
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

    def on_input_submitted(self, event: Any) -> None:
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
            _ArchiveOptionsResult(
                archive_path=Path(path_text),
                delete_source=self.delete_source,
            )
        )

    def action_cancel(self) -> None:
        """Dismiss without archiving."""
        self.dismiss(None)


class _DefaultPathScreen(ModalScreen[_DefaultPathResult | None]):
    """Prompt for a new default path when no live storages remain."""

    CSS = """
    _DefaultPathScreen {
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

    def __init__(self, *, default_path: Path) -> None:
        """Store the suggested default data directory."""
        super().__init__()
        self.default_path = default_path

    def compose(self) -> ComposeResult:
        """Compose the no-live-default dialog."""
        with Vertical(id="default-path-dialog"):
            yield Static(Text("No default storage remains", style="bold"))
            yield Static(
                "Choose a replacement default storage, or leave AppRC in an "
                "uninitialized state like a fresh install.",
                id="default-path-message",
            )
            yield Input(
                value=str(self.default_path),
                placeholder="Default storage directory",
                suggester=_PathSuggester(case_sensitive=True),
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

    def on_button_pressed(self, event: Any) -> None:
        """Handle default replacement buttons."""
        if event.button.id == "default-create":
            path_text = self.query_one(
                "#default-path-input", Input
            ).value.strip()
            if not path_text:
                self.notify("Enter a default path first.", severity="warning")
                return
            self.dismiss(
                _DefaultPathResult(action="create", path=Path(path_text))
            )
            return
        if event.button.id == "default-leave":
            self.dismiss(_DefaultPathResult(action="leave"))
            return
        if event.button.id == "default-cancel":
            self.action_cancel()

    def action_cancel(self) -> None:
        """Dismiss without changing the default."""
        self.dismiss(None)


class _ProgressScreen(ModalScreen[None]):
    """Modal progress bar for archive operations."""

    CSS = """
    _ProgressScreen {
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


class ConfigEditorApp(App[None]):
    """Small terminal UI for editing storage-local ``.env.local`` files."""

    CSS = """
    #storage-list {
        width: 28;
        border: solid $primary;
    }

    #editor-pane {
        width: 1fr;
        padding: 0 1;
    }

    #storage-action-row {
        height: 3;
        margin: 1 0;
    }

    #field-table {
        height: 1fr;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        *,
        registry: StorageRegistry,
        kit: AppConfigKit | None = None,
        owners: tuple[ConfigOwner, ...] | None = None,
        initial_storage: str | None = None,
        local_env_filename: str = ".env.local",
        init_command: str = "app config init STORAGE_ROOT --name NAME",
        registry_label: str = "storage registry",
        hidden_env_keys: tuple[str, ...] = (),
    ) -> None:
        """Keep registry and field metadata while editing storage state."""
        super().__init__()
        self.kit = kit
        if kit is not None:
            owners = kit.spec.owners
            local_env_filename = kit.spec.local_env_filename
            init_command = (
                f"{kit.spec.app_name} config init STORAGE_ROOT --name NAME"
            )
            registry_label = kit.spec.registry_filename
        if owners is None:
            raise TypeError("ConfigEditorApp requires kit or owners.")
        self.registry = registry
        self.owners = owners
        self.initial_storage = initial_storage
        self.local_env_filename = local_env_filename
        self.init_command = init_command
        self.registry_label = registry_label
        self.hidden_env_keys = frozenset(hidden_env_keys)
        self.storage_entries = self._ordered_storage_entries()
        self.current_storage_name: str | None = None
        self.current_storage_kind: Literal["live", "archived"] | None = None
        self.local_values: dict[str, str] = {}
        self.row_env_keys: list[str | None] = []

    def compose(self) -> ComposeResult:
        """Compose the storage list and field editor."""
        yield Header()
        with Horizontal():
            yield ListView(id="storage-list")
            with Vertical(id="editor-pane"):
                yield Static("", id="storage-title")
                with Horizontal(id="storage-action-row"):
                    yield Button(
                        "New storage", variant="primary", id="storage-new"
                    )
                    yield Button(
                        "Set this as default storage",
                        id="storage-set-default",
                        disabled=True,
                    )
                    yield Button(
                        "Delete storage",
                        id="storage-delete",
                        disabled=True,
                    )
                    yield Button(
                        "Archive storage",
                        id="storage-archive",
                        disabled=True,
                    )
                yield DataTable(id="field-table")
        yield Footer()

    async def on_mount(self) -> None:
        """Populate storages and select the active one."""
        await self._refresh_storage_list(select_name=self.initial_storage)

    async def on_list_view_selected(self, event: Any) -> None:
        """Switch the edited ``.env.local`` when a storage is selected."""
        index = event.list_view.index
        if index is None or index >= len(self.storage_entries):
            return
        entry = self.storage_entries[index]
        if entry.kind == "live":
            self._select_storage(entry.name)
            return
        self.run_worker(
            self._restore_or_prune_archived_storage(entry.name),
            exclusive=True,
        )

    def on_data_table_row_selected(self, event: Any) -> None:
        """Open a modal editor when a config field row is selected."""
        del event
        self._open_selected_field_editor()

    def _open_selected_field_editor(self) -> None:
        """Open the modal editor for the current table row."""
        selected = self._selected_field()
        if selected is None:
            return
        if not selected.spec.editable:
            self.notify(
                f"This setting is managed by {self.registry_label}.",
                severity="warning",
            )
            return
        env_key = selected.owner.env_key(selected.spec.name)
        self.push_screen(
            _ConfigValueEditScreen(
                owner=selected.owner,
                spec=selected.spec,
                env_key=env_key,
                local_value=self.local_values.get(env_key, ""),
                env_is_set=env_key in os.environ,
            ),
            self._handle_edit_result,
        )

    async def on_button_pressed(self, event: Any) -> None:
        """Handle storage action button clicks."""
        if event.button.id == "storage-new":
            self.run_worker(self._open_new_storage_flow(), exclusive=True)
            return
        if event.button.id == "storage-set-default":
            await self._set_current_as_default()
            return
        if event.button.id == "storage-delete":
            self.run_worker(self._open_delete_storage_flow(), exclusive=True)
            return
        if event.button.id == "storage-archive":
            self.run_worker(self._open_archive_storage_flow(), exclusive=True)

    def _handle_edit_result(self, result: _ValueEditResult | None) -> None:
        """Persist the value returned by the edit modal."""
        if result is None or self.current_storage_name is None:
            return
        if result.action == "clear":
            self._clear_env_key(result.env_key)
            return
        self._save_env_key(result.env_key, result.raw_value)

    async def _open_new_storage_flow(self) -> None:
        """Prompt for a new directory or archive path and register it."""
        if self._require_kit() is None:
            return
        result = await self.push_screen_wait(
            _PathInputScreen(
                title="New storage",
                message=(
                    "Enter path to a directory or an archived *.apprc.tar.xz."
                ),
                placeholder="Directory or *.apprc.tar.xz archive",
            )
        )
        if result is None:
            return
        path = result.path.expanduser()
        if is_storage_archive_path(path):
            await self._open_archive_import_flow(path)
            return
        await self._register_storage_directory_flow(
            path,
            default_name=self._suggest_storage_name(path),
        )

    async def _open_archive_import_flow(
        self,
        archive_path: Path,
        *,
        default_name: str | None = None,
        default_destination: Path | None = None,
    ) -> None:
        """Restore an archive path, then register the destination."""
        archive = archive_path.expanduser()
        if not archive.is_file():
            self.notify(
                f"Storage archive does not exist: {archive}", severity="error"
            )
            return
        restored_name = default_name or storage_root_name_from_archive(archive)
        destination = default_destination or archive.parent / restored_name
        result = await self.push_screen_wait(
            _PathInputScreen(
                title="Restore archived storage",
                message="Enter destination directory for the restored storage.",
                placeholder="Destination directory",
                value=str(destination),
            )
        )
        if result is None:
            return
        destination_root = result.path.expanduser()
        try:
            normalized_destination = normalize_storage_root_path(
                destination_root
            )
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            return
        if normalized_destination.exists() and any(
            normalized_destination.iterdir()
        ):
            action = await self.push_screen_wait(
                _ConfirmScreen(
                    title="Destination is not empty",
                    message=(
                        "Extracting the archive may overwrite files in:\n"
                        f"{normalized_destination}\n\nProceed?"
                    ),
                    actions=(("confirm", "Proceed", "warning"),),
                )
            )
            if action != "confirm":
                return
        try:
            await self._run_extract_progress(
                archive_path=archive,
                destination_root=normalized_destination,
            )
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            return
        await self._register_storage_directory_flow(
            normalized_destination,
            default_name=self._suggest_storage_name(Path(restored_name)),
        )

    async def _register_storage_directory_flow(
        self,
        storage_root: Path,
        *,
        default_name: str,
    ) -> None:
        """Prompt for confirmation and register one live storage root."""
        kit = self._require_kit()
        if kit is None:
            return
        guarded_root = await self._guard_storage_directory(storage_root)
        if guarded_root is None:
            return
        name_result = await self.push_screen_wait(
            _StorageNameScreen(
                default_name=default_name,
                message="Choose the registry name used by --storage.",
            )
        )
        if name_result is None:
            return
        name = name_result.name
        if name in self.registry.storages:
            existing = self.registry.selected(name)
            action = await self.push_screen_wait(
                _ConfirmScreen(
                    title="Replace storage entry?",
                    message=(
                        f"{name!r} is already registered at:\n"
                        f"{existing.root}\n\nReplace it with:\n{guarded_root}"
                    ),
                    actions=(("replace", "Replace", "warning"),),
                )
            )
            if action != "replace":
                return
        try:
            self.registry = kit.register_storage(
                name=name,
                root=guarded_root,
                make_default=self.registry.default_storage is None,
            )
        except (TypeError, ValueError) as exc:
            self.notify(str(exc), severity="error")
            return
        await self._refresh_storage_list(select_name=name)
        self.notify(f"Registered storage {name!r}")

    async def _guard_storage_directory(self, storage_root: Path) -> Path | None:
        """Confirm the requested directory is safe to register."""
        try:
            root = normalize_storage_root_path(storage_root)
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            return None
        if not root.exists():
            parent = root.parent
            if parent.exists():
                action = await self.push_screen_wait(
                    _ConfirmScreen(
                        title="Directory does not exist",
                        message=(
                            "Directory does not exist, create new directory "
                            f"inside {parent}?"
                        ),
                        actions=(("create", "Create", "primary"),),
                    )
                )
                return root if action == "create" else None
            self.notify(f"Path not found! {parent}", severity="error")
            return None
        resolved_root = root.resolve()
        if not resolved_root.is_dir():
            self.notify(
                f"Storage path exists but is not a directory: {resolved_root}",
                severity="error",
            )
            return None
        if not any(resolved_root.iterdir()):
            return resolved_root

        env_path = resolved_root / self.local_env_filename
        if env_path.is_file():
            keys = list(read_local_env(env_path))[:10]
            preview = ", ".join(keys) if keys else "<none>"
            message = (
                f"Storage not empty, found {self.local_env_filename} with "
                f"these env vars: {preview}.\n"
                "All these local env vars will be exported on runtime. "
                "Proceed?"
            )
        else:
            message = (
                "Storage not empty, but no "
                f"{self.local_env_filename} found, initialize with empty "
                f"{self.local_env_filename}?\n{resolved_root}"
            )
        action = await self.push_screen_wait(
            _ConfirmScreen(
                title="Confirm storage directory",
                message=message,
                actions=(("proceed", "Proceed", "warning"),),
            )
        )
        return resolved_root if action == "proceed" else None

    async def _set_current_as_default(self) -> None:
        """Set the selected live storage as the registry default."""
        kit = self._require_kit()
        if kit is None or self.current_storage_name is None:
            return
        if self.current_storage_kind != "live":
            self.notify("Select a live storage first.", severity="warning")
            return
        if self.registry.default_storage == self.current_storage_name:
            self.notify(
                f"{self.current_storage_name!r} is already the default."
            )
            return
        try:
            self.registry = kit.set_default_storage(
                name=self.current_storage_name
            )
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            return
        await self._refresh_storage_list(select_name=self.current_storage_name)
        self.notify(f"Default storage set to {self.current_storage_name!r}")

    async def _open_delete_storage_flow(self) -> None:
        """Prompt for unregister/delete behavior for the current storage."""
        if (
            self.current_storage_kind != "live"
            or self.current_storage_name is None
        ):
            return
        record = self._current_storage()
        action = await self.push_screen_wait(
            _ConfirmScreen(
                title="Delete storage",
                message=(
                    f"Storage: {record.name}\nRoot: {record.root}\n\n"
                    "Choose whether to only unregister it or delete the "
                    "directory contents too."
                ),
                actions=(
                    ("unregister", "Unregister only", "warning"),
                    (
                        "delete-content",
                        "Delete directory and unregister",
                        "error",
                    ),
                ),
            )
        )
        if action == "unregister":
            await self._remove_live_storage(record.name, delete_content=False)
        if action == "delete-content":
            await self._remove_live_storage(record.name, delete_content=True)

    async def _open_archive_storage_flow(self) -> None:
        """Prompt for archive options and compress the selected storage."""
        kit = self._require_kit()
        if (
            kit is None
            or self.current_storage_kind != "live"
            or self.current_storage_name is None
        ):
            return
        record = self._current_storage()
        options = await self.push_screen_wait(
            _ArchiveOptionsScreen(
                storage_name=record.name,
                source_root=record.root,
                default_archive=storage_archive_default_path(record.root),
            )
        )
        if options is None:
            return
        try:
            archive_path = await self._run_archive_progress(
                source_root=record.root,
                archive_path=options.archive_path,
            )
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            return
        self.registry = kit.record_archived_storage(
            name=record.name,
            archive=archive_path,
            source_root=record.root,
        )
        if options.delete_source:
            removed = await self._remove_live_storage(
                record.name,
                delete_content=True,
            )
            if not removed:
                await self._refresh_storage_list(select_name=record.name)
                self.notify(
                    f"Archived {record.name!r}; source deletion was canceled.",
                    severity="warning",
                )
                return
        else:
            await self._refresh_storage_list(select_name=record.name)
        self.notify(f"Archived storage {record.name!r} to {archive_path}")

    async def _remove_live_storage(
        self,
        name: str,
        *,
        delete_content: bool,
    ) -> bool:
        """Remove one live storage and repair the default if needed."""
        kit = self._require_kit()
        if kit is None:
            return False
        try:
            record = self.registry.selected(name)
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            return False
        replacement = await self._default_choice_before_removal(name)
        if replacement is None:
            return False
        if delete_content and record.root.exists():
            try:
                shutil.rmtree(record.root)
            except OSError as exc:
                self.notify(str(exc), severity="error")
                return False
        try:
            self.registry = kit.unregister_storage(
                name=name,
                replacement_default=replacement.replacement_name,
            )
            if replacement.create_default_path is not None:
                self.registry = kit.register_storage(
                    name="default",
                    root=replacement.create_default_path,
                    make_default=True,
                )
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            return False
        select_name = replacement.replacement_name or (
            "default" if replacement.create_default_path is not None else None
        )
        await self._refresh_storage_list(select_name=select_name)
        self.notify(f"Removed storage {name!r}")
        return True

    async def _default_choice_before_removal(
        self,
        removed_name: str,
    ) -> _RemovalDefaultChoice | None:
        """Return how the default should look after removing a storage."""
        if self.registry.default_storage != removed_name:
            return _RemovalDefaultChoice()
        remaining = [
            name
            for name in self._ordered_live_storage_names()
            if name != removed_name
        ]
        if remaining:
            actions: list[tuple[str, str, ButtonVariant]] = []
            for index, name in enumerate(remaining):
                variant: ButtonVariant = "primary" if index == 0 else "default"
                actions.append((f"default-{name}", name, variant))
            action = await self.push_screen_wait(
                _ConfirmScreen(
                    title="Choose replacement default",
                    message=(
                        f"{removed_name!r} is the default storage. "
                        "Choose the new default before removing it."
                    ),
                    actions=tuple(actions),
                )
            )
            if action is None or not action.startswith("default-"):
                return None
            return _RemovalDefaultChoice(
                replacement_name=action.removeprefix("default-")
            )

        kit = self._require_kit()
        if kit is None:
            return None
        result = await self.push_screen_wait(
            _DefaultPathScreen(default_path=kit.default_storage_data_root())
        )
        if result is None:
            return None
        if result.action == "leave":
            return _RemovalDefaultChoice()
        return _RemovalDefaultChoice(create_default_path=result.path)

    async def _restore_or_prune_archived_storage(self, name: str) -> None:
        """Restore an archived row or delete it when its file is gone."""
        kit = self._require_kit()
        if kit is None:
            return
        record = self.registry.archived_storages.get(name)
        if record is None:
            return
        if not record.archive.is_file():
            self.registry = kit.remove_archived_storage(name=name)
            await self._refresh_storage_list()
            self.notify(
                f"Removed stale archive entry {name!r}; file was not found.",
                severity="warning",
            )
            return
        await self._open_archive_import_flow(
            record.archive,
            default_name=record.name,
            default_destination=record.source_root,
        )

    async def _run_archive_progress(
        self,
        *,
        source_root: Path,
        archive_path: Path,
    ) -> Path:
        """Run archive compression with a progress modal."""
        progress_screen = _ProgressScreen(title="Compressing storage")
        await self.push_screen(progress_screen)

        def progress(progress_update: StorageArchiveProgress) -> None:
            self.call_from_thread(
                progress_screen.update_progress, progress_update
            )

        worker = self.run_worker(
            lambda: archive_directory(
                source_root=source_root,
                archive_path=archive_path,
                progress=progress,
            ),
            thread=True,
            exit_on_error=False,
        )
        try:
            return await worker.wait()
        finally:
            progress_screen.dismiss(None)

    async def _run_extract_progress(
        self,
        *,
        archive_path: Path,
        destination_root: Path,
    ) -> Path:
        """Run archive extraction with a progress modal."""
        progress_screen = _ProgressScreen(title="Decompressing storage")
        await self.push_screen(progress_screen)

        def progress(progress_update: StorageArchiveProgress) -> None:
            self.call_from_thread(
                progress_screen.update_progress, progress_update
            )

        worker = self.run_worker(
            lambda: extract_archive(
                archive_path=archive_path,
                destination_root=destination_root,
                progress=progress,
            ),
            thread=True,
            exit_on_error=False,
        )
        try:
            return await worker.wait()
        finally:
            progress_screen.dismiss(None)

    def _require_kit(self) -> AppConfigKit | None:
        """Return the kit required for registry mutations."""
        if self.kit is None:
            self.notify(
                "Storage management requires ConfigEditorApp(kit=...).",
                severity="error",
            )
            return None
        return self.kit

    def _save_env_key(self, env_key: str, raw_value: str) -> None:
        """Validate and persist one local env value."""
        found = find_field_by_env_key(self.owners, env_key)
        if found is None:
            return
        owner, spec = found
        try:
            value = normalize_env_value(spec, raw_value)
        except (TypeError, ValueError) as exc:
            self.notify(str(exc), severity="error")
            return
        self.local_values[env_key] = value
        write_local_env(
            self._current_local_env_path(),
            self.local_values,
            owners=self.owners,
        )
        self._populate_field_table()
        self.notify(f"Saved {env_key}")

    def _clear_env_key(self, env_key: str) -> None:
        """Remove one key from the active local env file."""
        if env_key not in self.local_values:
            return
        self.local_values.pop(env_key)
        write_local_env(
            self._current_local_env_path(),
            self.local_values,
            owners=self.owners,
        )
        self._populate_field_table()
        self.notify(f"Cleared {env_key}")

    async def _refresh_storage_list(
        self,
        *,
        select_name: str | None = None,
    ) -> None:
        """Reload registry rows and select the requested live storage."""
        self.storage_entries = self._ordered_storage_entries()
        storage_list = self.query_one("#storage-list", ListView)
        await storage_list.clear()
        if not self.storage_entries:
            self.current_storage_name = None
            self.current_storage_kind = None
            self.local_values = {}
            self.query_one("#storage-title", Static).update(
                "No storages registered. Use New storage to add one."
            )
            self._clear_field_table()
            self._set_live_controls_enabled(False)
            return
        for entry in self.storage_entries:
            await storage_list.append(
                ListItem(Label(self._storage_entry_label(entry)))
            )

        selected_index = self._storage_entry_index(select_name)
        if selected_index is None:
            selected_index = self._storage_entry_index(
                self.registry.default_storage
            )
        if selected_index is None:
            selected_index = 0
        storage_list.index = selected_index
        entry = self.storage_entries[selected_index]
        if entry.kind == "live":
            self._select_storage(entry.name)
        else:
            self._select_archived_storage(entry.name)

    def _ordered_storage_entries(self) -> list[_StorageListEntry]:
        """Return live storages followed by archived restore rows."""
        entries = [
            _StorageListEntry(kind="live", name=name)
            for name in self._ordered_live_storage_names()
        ]
        live_names = {entry.name for entry in entries}
        entries.extend(
            _StorageListEntry(kind="archived", name=name)
            for name in sorted(self.registry.archived_storages)
            if name not in live_names
        )
        return entries

    def _ordered_live_storage_names(self) -> list[str]:
        """Return default storage first, then remaining live storages."""
        names = sorted(self.registry.storages)
        default_name = self.registry.default_storage
        if default_name in names:
            names.remove(default_name)
            names.insert(0, default_name)
        return names

    def _storage_entry_index(self, name: str | None) -> int | None:
        """Return the first list index for a storage name."""
        if name is None:
            return None
        for index, entry in enumerate(self.storage_entries):
            if entry.name == name:
                return index
        return None

    def _storage_entry_label(self, entry: _StorageListEntry) -> str:
        """Return a readable storage-list label."""
        if entry.kind == "live":
            record = self.registry.selected(entry.name)
            default = (
                " [default]"
                if record.name == self.registry.default_storage
                else ""
            )
            return f"{record.name}{default}\n{record.root}"
        record = self.registry.archived_storages[entry.name]
        return f"{record.name} [Last Archived]\n{record.archive}"

    def _select_storage(self, name: str) -> None:
        """Load one storage-local env file and refresh the field table."""
        self.current_storage_name = name
        self.current_storage_kind = "live"
        record = self.registry.selected(name)
        path = local_env_path(record.root, filename=self.local_env_filename)
        path.touch(exist_ok=True)
        self.local_values = read_local_env(path)
        self.query_one("#storage-title", Static).update(
            f"{record.name}: {record.root}\n{path}"
        )
        self._populate_field_table()
        self._set_live_controls_enabled(True)

    def _select_archived_storage(self, name: str) -> None:
        """Show archived metadata without enabling field editing."""
        self.current_storage_name = name
        self.current_storage_kind = "archived"
        record = self.registry.archived_storages[name]
        self.local_values = {}
        self.query_one("#storage-title", Static).update(
            f"{record.name}: Last Archived\n"
            f"Archive: {record.archive}\n"
            f"Last source: {record.source_root}"
        )
        self._clear_field_table()
        self._set_live_controls_enabled(False)

    def _populate_field_table(self) -> None:
        """Render every known config field for the active storage."""
        table = self.query_one("#field-table", DataTable)
        table.clear(columns=True)
        table.cursor_type = "row"
        table.add_columns(*FIELD_TABLE_COLUMNS)
        self.row_env_keys = []
        for row in build_field_table_rows(
            owners=self.owners,
            local_values=self.local_values,
            hidden_env_keys=self.hidden_env_keys,
            shell_env=os.environ,
        ):
            if row.height is None:
                table.add_row(*row.cells)
            else:
                table.add_row(*row.cells, height=row.height)
            self.row_env_keys.append(row.env_key)

    def _clear_field_table(self) -> None:
        """Clear the field table when no live storage is selected."""
        table = self.query_one("#field-table", DataTable)
        table.clear(columns=True)
        self.row_env_keys = []

    def _selected_field(self) -> _SelectedField | None:
        """Return the field represented by the current table cursor."""
        table = self.query_one("#field-table", DataTable)
        row_index = table.cursor_row
        if (
            row_index is None
            or row_index < 0
            or row_index >= len(self.row_env_keys)
        ):
            return None
        env_key = self.row_env_keys[row_index]
        if env_key is None:
            return None
        found = find_field_by_env_key(self.owners, env_key)
        if found is None:
            return None
        owner, spec = found
        return _SelectedField(owner=owner, spec=spec)

    def _current_storage(self) -> StorageRecord:
        """Return the active storage record."""
        if self.current_storage_name is None:
            raise RuntimeError("No storage is selected.")
        return self.registry.selected(self.current_storage_name)

    def _current_local_env_path(self) -> Path:
        """Return the active storage-local env path."""
        return local_env_path(
            self._current_storage().root,
            filename=self.local_env_filename,
        )

    def _set_controls_enabled(self, enabled: bool) -> None:
        """Enable or disable editor controls."""
        self.query_one("#field-table", DataTable).disabled = not enabled

    def _set_live_controls_enabled(self, enabled: bool) -> None:
        """Enable storage-specific controls only for live storages."""
        self._set_controls_enabled(enabled)
        for button_id in (
            "#storage-set-default",
            "#storage-delete",
            "#storage-archive",
        ):
            self.query_one(button_id, Button).disabled = not enabled

    def _suggest_storage_name(self, path: Path) -> str:
        """Return a simple registry-name suggestion from a path."""
        name = path.name or "default"
        if is_storage_archive_path(path):
            name = storage_root_name_from_archive(path)
        normalized = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-_")
        return normalized or "default"
