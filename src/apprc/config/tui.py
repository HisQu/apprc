"""Textual editor for storage-local config overrides."""

from __future__ import annotations

# == Standard Library ========================
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# == 3rd Party ===============================
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Static,
)

# == Internal ================================
from apprc.config.local_env import (
    local_env_path,
    normalize_env_value,
    read_local_env,
    write_local_env,
)
from apprc.config.schema import (
    CONFIG_MISSING,
    ConfigField,
    ConfigOwner,
    find_field_by_env_key,
    iter_config_fields,
)
from apprc.config.storage_registry import StorageRecord, StorageRegistry


@dataclass(frozen=True, slots=True)
class _SelectedField:
    """One field selected by env key in the editor table."""

    owner: ConfigOwner
    spec: ConfigField


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

    #field-help {
        height: 6;
        margin: 1 0;
    }

    #button-row {
        height: 3;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("ctrl+s", "save_value", "Save"),
    ]

    def __init__(
        self,
        *,
        registry: StorageRegistry,
        owners: tuple[ConfigOwner, ...],
        initial_storage: str | None = None,
        local_env_filename: str = ".env.local",
        init_command: str = "app config init STORAGE_ROOT --name NAME",
        registry_label: str = "storage registry",
    ) -> None:
        """Keep the registry immutable while the app edits per-storage files."""
        super().__init__()
        self.registry = registry
        self.owners = owners
        self.initial_storage = initial_storage
        self.local_env_filename = local_env_filename
        self.init_command = init_command
        self.registry_label = registry_label
        self.storage_names = self._ordered_storage_names()
        self.current_storage_name: str | None = None
        self.local_values: dict[str, str] = {}
        self.row_env_keys: list[str] = []

    def compose(self) -> ComposeResult:
        """Compose the storage list and field editor."""
        yield Header()
        with Horizontal():
            yield ListView(id="storage-list")
            with Vertical(id="editor-pane"):
                yield Static("", id="storage-title")
                yield DataTable(id="field-table")
                yield Static("", id="field-help")
                yield Input(
                    placeholder="Local override value", id="value-input"
                )
                with Horizontal(id="button-row"):
                    yield Button("Save", variant="primary", id="save")
                    yield Button("Clear", id="clear")
        yield Footer()

    def on_mount(self) -> None:
        """Populate storages and select the active one."""
        storage_list = self.query_one("#storage-list", ListView)
        if not self.storage_names:
            self.query_one("#storage-title", Static).update(
                f"No storages registered. Run `{self.init_command}`."
            )
            self._set_controls_enabled(False)
            return
        for name in self.storage_names:
            record = self.registry.selected(name)
            label = f"{name}\n{record.root}"
            storage_list.append(ListItem(Label(label)))
        initial_name = self.initial_storage or self.registry.default_storage
        initial_index = (
            self.storage_names.index(initial_name)
            if initial_name in self.storage_names
            else 0
        )
        storage_list.index = initial_index
        self._select_storage(self.storage_names[initial_index])

    def on_list_view_selected(self, event: Any) -> None:
        """Switch the edited ``.env.local`` when a storage is selected."""
        index = event.list_view.index
        if index is None or index >= len(self.storage_names):
            return
        self._select_storage(self.storage_names[index])

    def on_data_table_row_selected(self, event: Any) -> None:
        """Update the value input from the selected table row."""
        del event
        self._refresh_selected_field_panel()

    def on_button_pressed(self, event: Any) -> None:
        """Handle Save and Clear button clicks."""
        if event.button.id == "save":
            self.action_save_value()
            return
        if event.button.id == "clear":
            self._clear_value()

    def action_save_value(self) -> None:
        """Validate and persist the current input value."""
        selected = self._selected_field()
        if selected is None or self.current_storage_name is None:
            return
        if not selected.spec.editable:
            self.notify(
                "This setting is managed outside .env.local.",
                severity="warning",
            )
            return
        raw_value = self.query_one("#value-input", Input).value
        try:
            value = normalize_env_value(selected.spec, raw_value)
        except (TypeError, ValueError) as exc:
            self.notify(str(exc), severity="error")
            return
        env_key = selected.owner.env_key(selected.spec.name)
        self.local_values[env_key] = value
        write_local_env(
            self._current_local_env_path(),
            self.local_values,
            owners=self.owners,
        )
        self._populate_field_table()
        self.notify(f"Saved {env_key}")

    def _clear_value(self) -> None:
        """Remove the selected key from the active local env file."""
        selected = self._selected_field()
        if selected is None:
            return
        env_key = selected.owner.env_key(selected.spec.name)
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

    def _ordered_storage_names(self) -> list[str]:
        """Return default storage first, then remaining storages by name."""
        names = sorted(self.registry.storages)
        default_name = self.registry.default_storage
        if default_name in names:
            names.remove(default_name)
            names.insert(0, default_name)
        return names

    def _select_storage(self, name: str) -> None:
        """Load one storage-local env file and refresh the field table."""
        self.current_storage_name = name
        record = self.registry.selected(name)
        path = local_env_path(record.root, filename=self.local_env_filename)
        path.touch(exist_ok=True)
        self.local_values = read_local_env(path)
        self.query_one("#storage-title", Static).update(
            f"{record.name}: {record.root}\n{path}"
        )
        self._populate_field_table()

    def _populate_field_table(self) -> None:
        """Render every known config field for the active storage."""
        table = self.query_one("#field-table", DataTable)
        table.clear(columns=True)
        table.cursor_type = "row"
        table.add_columns("Key", "Local", "Default", "Section")
        self.row_env_keys = []
        for owner, spec in iter_config_fields(self.owners):
            env_key = owner.env_key(spec.name)
            local = self.local_values.get(env_key, "")
            default = _display_default(spec)
            table.add_row(
                env_key,
                _display_value(local, secret=spec.secret),
                default,
                owner.title,
            )
            self.row_env_keys.append(env_key)
        self._refresh_selected_field_panel()

    def _refresh_selected_field_panel(self) -> None:
        """Display metadata and current local value for the selected field."""
        selected = self._selected_field()
        help_panel = self.query_one("#field-help", Static)
        value_input = self.query_one("#value-input", Input)
        if selected is None:
            help_panel.update("")
            self._set_controls_enabled(False)
            return
        env_key = selected.owner.env_key(selected.spec.name)
        editable = selected.spec.editable
        value_input.value = self.local_values.get(env_key, "")
        value_input.disabled = not editable
        self.query_one("#save", Button).disabled = not editable
        self.query_one("#clear", Button).disabled = not editable
        edit_note = (
            ""
            if editable
            else f"\nManaged by {self.registry_label}, not {self.local_env_filename}."
        )
        help_panel.update(
            f"{selected.spec.title or selected.spec.name}\n"
            f"{selected.owner.config_path_text(selected.spec.name)}\n"
            f"{selected.spec.explanation}{edit_note}"
        )

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
        found = find_field_by_env_key(self.owners, self.row_env_keys[row_index])
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
        self.query_one("#value-input", Input).disabled = not enabled
        self.query_one("#save", Button).disabled = not enabled
        self.query_one("#clear", Button).disabled = not enabled


def _display_default(spec: ConfigField) -> str:
    """Return a compact default value for table display."""
    value = spec.shared_env_value()
    if value is CONFIG_MISSING:
        return "<required>"
    return str(value)


def _display_value(value: str, *, secret: bool) -> str:
    """Return a local value safe for table display."""
    if value == "":
        return ""
    if secret:
        return "<secret>"
    return value
