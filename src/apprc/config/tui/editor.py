"""Interactive Textual editor for storage-local config overrides.

Applications declare config fields once through :mod:`apprc.config.schema`.
This module turns those declarations into a terminal UI that selects one
registered storage root, reads that storage's local dotenv file, and edits
only the values owned by the local override layer.

Rendering rules for table cells live in :mod:`apprc.config.tui.rendering` so
the widget code here stays focused on Textual events, modal handling, and file
persistence.
"""

from __future__ import annotations

# == Standard Library ========================
import os
from importlib.resources import as_file, files
from pathlib import Path
from typing import TYPE_CHECKING

# == 3rd Party ===============================
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Label,
    ListItem,
    ListView,
    Static,
)

# == Internal ================================
from apprc.config.local_env import (
    clear_local_env_value,
    ensure_local_env_file,
    local_env_path,
    read_local_env,
    set_local_env_value,
)
from apprc.config.storage.registry import (
    StorageRecord,
    StorageRegistry,
    suggested_storage_name,
)
from apprc.config.tui.modals import (
    ConfigValueEditScreen,
    ValueEditResult,
)
from apprc.config.tui.rendering import (
    FIELD_TABLE_COLUMNS,
    active_storage_title,
    archived_storage_title,
    build_field_table_rows,
    live_storage_title,
    missing_storage_title,
)
from apprc.config.tui.field_state import (
    SelectedField,
    config_value_sources,
    selected_field_for_row,
)
from apprc.config.tui.storage.entries import (
    StorageEntryKind,
    ordered_storage_entries,
    storage_entry_index,
    storage_entry_label,
    suggest_storage_name,
)
from apprc.config.tui.workflows import ConfigEditorStorageWorkflows

if TYPE_CHECKING:
    from apprc.config.kit import AppConfigKit


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
        kit: AppConfigKit,
        registry: StorageRegistry | None,
        initial_storage: str | None = None,
        active_storage_root: Path | None = None,
    ) -> None:
        """Keep registry and field metadata while editing storage state."""
        super().__init__()
        self.kit = kit
        self.registry = registry
        self.owners = kit.spec.owners
        self.initial_storage = initial_storage
        self.local_env_filename = kit.spec.local_env_filename
        self.init_command = (
            f"{kit.spec.config_command_name()} config init "
            "STORAGE_ROOT --name NAME"
        )
        self.registry_label = kit.spec.apprc_toml_filename
        self.hidden_env_keys = frozenset({kit.spec.storage_env_key})
        self.active_storage_root = (
            Path(active_storage_root).expanduser().resolve()
            if active_storage_root is not None
            else None
        )
        self.shared_values = _read_packaged_shared_values(kit)
        self.storage_entries = (
            ordered_storage_entries(registry) if registry is not None else []
        )
        self.current_storage_name: str | None = None
        self.current_storage_kind: StorageEntryKind | None = None
        self.local_values: dict[str, str] = {}
        self.row_env_keys: list[str | None] = []
        self.storage_workflows = ConfigEditorStorageWorkflows(self)

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
                        "Register active storage",
                        id="storage-register-active",
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

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Switch the edited ``.env.local`` when a storage is selected."""
        index = event.list_view.index
        if index is None or index >= len(self.storage_entries):
            return
        entry = self.storage_entries[index]
        if entry.kind == "live":
            self._select_storage(entry.name)
            return
        if entry.kind == "missing":
            self._select_missing_storage(entry.name)
            return
        self.run_worker(
            self.storage_workflows.restore_or_prune_archived_storage(
                entry.name
            ),
            exclusive=True,
        )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
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
            ConfigValueEditScreen(
                spec=selected.spec,
                env_key=env_key,
                value_sources=config_value_sources(
                    spec=selected.spec,
                    env_key=env_key,
                    local_values=self.local_values,
                    shell_env=os.environ,
                    shared_values=self.shared_values,
                ),
            ),
            self._handle_edit_result,
        )

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle storage action button clicks."""
        if event.button.id == "storage-new":
            self.run_worker(
                self.storage_workflows.open_new_storage_flow(),
                exclusive=True,
            )
            return
        if event.button.id == "storage-register-active":
            await self.storage_workflows.register_active_storage_flow()
            return
        if event.button.id == "storage-delete":
            self.run_worker(
                self.storage_workflows.open_delete_storage_flow(),
                exclusive=True,
            )
            return
        if event.button.id == "storage-archive":
            self.run_worker(
                self.storage_workflows.open_archive_storage_flow(),
                exclusive=True,
            )

    def _handle_edit_result(self, result: ValueEditResult | None) -> None:
        """Persist the value returned by the edit modal."""
        if result is None or self.current_storage_kind is None:
            return
        if result.action == "clear":
            self._clear_env_key(result.env_key)
            return
        self._save_env_key(result.env_key, result.raw_value)

    def _require_registry(self) -> StorageRegistry | None:
        """Return the registry required for registry-only editor actions."""
        if self.registry is None:
            self.notify(
                "Storage management requires an AppRC TOML.",
                severity="error",
            )
            return None
        return self.registry

    def _save_env_key(self, env_key: str, raw_value: str) -> None:
        """Validate and persist one local env value."""
        try:
            update = set_local_env_value(
                storage_root=self._current_storage_root(),
                reference=env_key,
                raw_value=raw_value,
                owners=self.owners,
                local_env_filename=self.local_env_filename,
            )
        except (TypeError, ValueError) as exc:
            self.notify(str(exc), severity="error", markup=False)
            return
        self.local_values = read_local_env(update.path)
        self._populate_field_table()
        self.notify(f"Saved {update.env_key}")

    def _clear_env_key(self, env_key: str) -> None:
        """Remove one key from the active local env file."""
        try:
            update = clear_local_env_value(
                storage_root=self._current_storage_root(),
                reference=env_key,
                owners=self.owners,
                local_env_filename=self.local_env_filename,
            )
        except ValueError as exc:
            self.notify(str(exc), severity="error", markup=False)
            return
        if update is None:
            return
        self.local_values = read_local_env(update.path)
        self._populate_field_table()
        self.notify(f"Cleared {update.env_key}")

    async def _refresh_storage_list(
        self,
        *,
        select_name: str | None = None,
    ) -> None:
        """Reload registry rows and select the requested storage."""
        registry = self.registry
        self.storage_entries = (
            ordered_storage_entries(registry) if registry is not None else []
        )
        storage_list = self.query_one("#storage-list", ListView)
        await storage_list.clear()
        if not self.storage_entries:
            if self.active_storage_root is not None:
                self._select_active_storage()
                return
            self._clear_selection()
            self.query_one("#storage-title", Static).update(
                self._no_storage_message()
            )
            self._clear_field_table()
            self._set_live_controls_enabled(False)
            return
        for entry in self.storage_entries:
            if registry is None:
                return
            await storage_list.append(
                ListItem(Label(storage_entry_label(registry, entry)))
            )

        selected_index = storage_entry_index(self.storage_entries, select_name)
        if selected_index is None:
            active_name = self._registered_active_storage_name()
            if active_name is None and self.active_storage_root is not None:
                self._select_active_storage()
                return
            selected_index = storage_entry_index(
                self.storage_entries, active_name
            )
        if selected_index is None:
            selected_index = 0
        storage_list.index = selected_index
        entry = self.storage_entries[selected_index]
        if entry.kind == "live":
            self._select_storage(entry.name)
            return
        if entry.kind == "missing":
            self._select_missing_storage(entry.name)
            return
        self._select_archived_storage(entry.name)

    def _select_active_storage(self) -> None:
        """Load the env-selected active path without requiring a registry row."""
        root = self.active_storage_root
        if root is None:
            return
        self.current_storage_name = None
        self.current_storage_kind = "live"
        path = ensure_local_env_file(root, filename=self.local_env_filename)
        self.local_values = read_local_env(path)
        self.query_one("#storage-title", Static).update(
            active_storage_title(root, path)
        )
        self._populate_field_table()
        self._set_storage_controls_enabled(
            fields=True,
            register_active=self.registry is not None,
            delete=False,
            archive=False,
        )

    def _select_storage(self, name: str) -> None:
        """Load one storage-local env file and refresh the field table."""
        registry = self._require_registry()
        if registry is None:
            return
        self.current_storage_name = name
        self.current_storage_kind = "live"
        record = registry.selected(name)
        path = ensure_local_env_file(
            record.root,
            filename=self.local_env_filename,
        )
        self.local_values = read_local_env(path)
        self.query_one("#storage-title", Static).update(
            live_storage_title(record, path)
        )
        self._populate_field_table()
        self._set_live_controls_enabled(True)

    def _select_missing_storage(self, name: str) -> None:
        """Show a registered storage whose root no longer exists."""
        registry = self._require_registry()
        if registry is None:
            return
        self.current_storage_name = name
        self.current_storage_kind = "missing"
        record = registry.selected(name)
        self.local_values = {}
        self.query_one("#storage-title", Static).update(
            missing_storage_title(record)
        )
        self._clear_field_table()
        self._set_storage_controls_enabled(
            fields=False,
            register_active=False,
            delete=True,
            archive=False,
        )

    def _select_archived_storage(self, name: str) -> None:
        """Show archived metadata without enabling field editing."""
        registry = self._require_registry()
        if registry is None:
            return
        self.current_storage_name = name
        self.current_storage_kind = "archived"
        record = registry.archived_storages[name]
        self.local_values = {}
        self.query_one("#storage-title", Static).update(
            archived_storage_title(record)
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

    def _selected_field(self) -> SelectedField | None:
        """Return the field represented by the current table cursor."""
        table = self.query_one("#field-table", DataTable)
        return selected_field_for_row(
            owners=self.owners,
            row_env_keys=self.row_env_keys,
            row_index=table.cursor_row,
        )

    def _current_storage(self) -> StorageRecord:
        """Return the active storage record."""
        registry = self._require_registry()
        if registry is None:
            raise RuntimeError("No registry is loaded.")
        if self.current_storage_name is None:
            raise RuntimeError("No storage is selected.")
        return registry.selected(self.current_storage_name)

    def _current_storage_root(self) -> Path:
        """Return the selected storage root, registered or active-path only."""
        if self.current_storage_name is not None:
            return self._current_storage().root
        if self.active_storage_root is None:
            raise RuntimeError("No storage is selected.")
        return self.active_storage_root

    def _current_local_env_path(self) -> Path:
        """Return the active storage-local env path."""
        return local_env_path(
            self._current_storage_root(),
            filename=self.local_env_filename,
        )

    def _set_controls_enabled(self, enabled: bool) -> None:
        """Enable or disable editor controls."""
        self.query_one("#field-table", DataTable).disabled = not enabled

    def _set_live_controls_enabled(self, enabled: bool) -> None:
        """Enable storage-specific controls only for live storages."""
        self._set_storage_controls_enabled(
            fields=enabled,
            register_active=False,
            delete=enabled,
            archive=enabled,
        )

    def _set_storage_controls_enabled(
        self,
        *,
        fields: bool,
        register_active: bool,
        delete: bool,
        archive: bool,
    ) -> None:
        """Enable or disable each storage-scoped editor control.

        :param fields: Whether config field rows may be edited.
        :param register_active: Whether the active path may be registered.
        :param delete: Whether the current registry row may be removed.
        :param archive: Whether the current storage directory may be archived.
        """
        self._set_controls_enabled(fields)
        self.query_one("#storage-new", Button).disabled = self.registry is None
        self.query_one(
            "#storage-register-active", Button
        ).disabled = not register_active
        self.query_one("#storage-delete", Button).disabled = not delete
        self.query_one("#storage-archive", Button).disabled = not archive

    def _clear_selection(self) -> None:
        """Clear storage selection and local values."""
        self.current_storage_name = None
        self.current_storage_kind = None
        self.local_values = {}

    def _registered_active_storage_name(self) -> str | None:
        """Return the registry row that matches the active path, if any."""
        if self.active_storage_root is None or self.registry is None:
            return None
        for name in sorted(self.registry.storages):
            record = self.registry.storages[name]
            record_root = Path(record.root).expanduser().resolve()
            if record_root == self.active_storage_root:
                return name
        return None

    def _suggest_storage_name(self, path: Path) -> str:
        """Return a simple registry-name suggestion from a path."""
        return suggest_storage_name(
            path,
            fallback_name=self._fallback_storage_name(),
        )

    def _fallback_storage_name(self) -> str:
        """Return a storage selector when no path name is available."""
        return suggested_storage_name(self.kit.spec.app_name)

    def _no_storage_message(self) -> str:
        """Return empty-list guidance for the current registry capability."""
        storage_env_key = self.kit.spec.storage_env_key
        if self.registry is not None:
            return (
                "No storages registered. Use New storage to add one, or set "
                f"{storage_env_key} to edit an active path.\n"
                f"CLI: {self.init_command}"
            )
        return (
            "No active storage path is selected. Set "
            f"{storage_env_key} to edit a storage-local env file. Configure "
            "the AppRC TOML to enable registry actions."
        )


def _read_packaged_shared_values(kit: AppConfigKit) -> dict[str, str]:
    """Return packaged shared dotenv values for a kit-backed editor.

    :param kit: Application facade that owns the shared dotenv resource.
    :return: Parsed shared values.
    """
    resource = files(kit.spec.config_package).joinpath(
        kit.spec.shared_env_filename
    )
    with as_file(resource) as path:
        return read_local_env(path)
