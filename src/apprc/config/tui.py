"""Textual editor for storage-local config overrides."""

from __future__ import annotations

# == Standard Library ========================
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

# == 3rd Party ===============================
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
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
from rich.text import Text

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
)
from apprc.config.storage_registry import StorageRecord, StorageRegistry

if TYPE_CHECKING:
    from apprc.config.kit import AppConfigKit


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
                        f"Type: {_type_label(self.spec)}",
                        f"Possible values: {_possible_values_label(self.spec)}",
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
        """Keep the registry immutable while editing per-storage files."""
        super().__init__()
        if kit is not None:
            owners = kit.spec.owners
            local_env_filename = kit.spec.local_env_filename
            init_command = (
                f"{kit.spec.app_name} config init STORAGE_ROOT --name NAME"
            )
            registry_label = kit.spec.registry_filename
            hidden_env_keys = (
                kit.spec.storage_root_env_key,
                *hidden_env_keys,
            )
        if owners is None:
            raise TypeError("ConfigEditorApp requires kit or owners.")
        self.registry = registry
        self.owners = owners
        self.initial_storage = initial_storage
        self.local_env_filename = local_env_filename
        self.init_command = init_command
        self.registry_label = registry_label
        self.hidden_env_keys = frozenset(hidden_env_keys)
        self.storage_names = self._ordered_storage_names()
        self.current_storage_name: str | None = None
        self.local_values: dict[str, str] = {}
        self.row_env_keys: list[str | None] = []

    def compose(self) -> ComposeResult:
        """Compose the storage list and field editor."""
        yield Header()
        with Horizontal():
            yield ListView(id="storage-list")
            with Vertical(id="editor-pane"):
                yield Static("", id="storage-title")
                yield DataTable(id="field-table")
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

    def on_button_pressed(self, event: Any) -> None:
        """Handle Save and Clear button clicks."""
        del event

    def _handle_edit_result(self, result: _ValueEditResult | None) -> None:
        """Persist the value returned by the edit modal."""
        if result is None or self.current_storage_name is None:
            return
        if result.action == "clear":
            self._clear_env_key(result.env_key)
            return
        self._save_env_key(result.env_key, result.raw_value)

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
        table.add_columns(
            "#",
            "Section",
            "Key",
            "Status",
            "Local",
            "Default",
            "Explanation",
        )
        self.row_env_keys = []
        row_number = 1
        rendered_section = False
        for owner in self.owners:
            visible_specs = [
                spec
                for spec in owner.fields
                if owner.env_key(spec.name) not in self.hidden_env_keys
            ]
            if not visible_specs:
                continue
            if rendered_section:
                table.add_row(*_separator_cells(), height=1)
                self.row_env_keys.append(None)
            rendered_section = True
            for spec in visible_specs:
                env_key = owner.env_key(spec.name)
                local = self.local_values.get(env_key, "")
                env_is_set = env_key in os.environ
                default = _display_default(
                    spec,
                    local_value=local,
                    env_is_set=env_is_set,
                )
                table.add_row(
                    str(row_number),
                    Text(owner.title, style="bold"),
                    env_key,
                    _status_cell(env_is_set),
                    _display_value(local, secret=spec.secret),
                    default,
                    Text(_short_explanation(spec), style="dim"),
                )
                self.row_env_keys.append(env_key)
                row_number += 1

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


def _display_default(
    spec: ConfigField,
    *,
    local_value: str,
    env_is_set: bool,
) -> str | Text:
    """Return a compact default value for table display."""
    value = spec.shared_env_value()
    if value is CONFIG_MISSING:
        if local_value == "" and not env_is_set:
            return Text("<required>", style="bold white on red")
        return ""
    return str(value)


def _display_value(value: str, *, secret: bool) -> str:
    """Return a local value safe for table display."""
    if value == "":
        return ""
    if secret:
        return "<secret>"
    return value


def _separator_cells() -> tuple[Text, ...]:
    """Return a non-editable horizontal separator row."""
    return tuple(
        Text("─" * width, style="dim") for width in (3, 14, 22, 8, 14, 14, 32)
    )


def _status_cell(env_is_set: bool) -> Text:
    """Return the shell environment status cell."""
    if env_is_set:
        return Text("shell", style="green")
    return Text("unset", style="dim")


def _short_explanation(spec: ConfigField) -> str:
    """Return the field's compact table explanation."""
    return spec.explanation_short or spec.explanation_long


def _type_label(spec: ConfigField) -> str:
    """Return a human-readable type label for editor metadata."""
    type_name = getattr(spec.python_type, "__name__", None)
    if isinstance(type_name, str):
        return type_name
    return str(spec.python_type)


def _possible_values_label(spec: ConfigField) -> str:
    """Return accepted values for editor metadata."""
    if spec.choices:
        return ", ".join(spec.choices)
    if spec.python_type is bool:
        return "true, false, yes, no, on, off, 1, 0"
    if spec.python_type is int:
        return "integer"
    if spec.python_type is float:
        return "number"
    if spec.python_type is Path:
        return "filesystem path"
    return "free text"
