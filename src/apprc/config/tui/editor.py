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
    local_env_path,
    read_local_env,
    set_local_env_value,
)
from apprc.config.schema import ConfigOwner
from apprc.config.storage.registry import StorageRecord, StorageRegistry
from apprc.config.tui.modals import (
    ConfigValueEditScreen,
    ValueEditResult,
)
from apprc.config.tui.rendering import (
    FIELD_TABLE_COLUMNS,
    build_field_table_rows,
)
from apprc.config.tui.field_state import (
    SelectedField,
    archived_storage_title,
    live_storage_title,
    missing_storage_title,
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
                f"{kit.spec.config_command_name()} config init "
                "STORAGE_ROOT --name NAME"
            )
            registry_label = kit.spec.apprc_toml_filename
        if owners is None:
            raise TypeError("ConfigEditorApp requires kit or owners.")
        self.registry = registry
        self.owners = owners
        self.initial_storage = initial_storage
        self.local_env_filename = local_env_filename
        self.init_command = init_command
        self.registry_label = registry_label
        self.hidden_env_keys = frozenset(hidden_env_keys)
        self.storage_entries = ordered_storage_entries(self.registry)
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
                        "Set as setup/editor default",
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
                owner=selected.owner,
                spec=selected.spec,
                env_key=env_key,
                local_value=self.local_values.get(env_key, ""),
                env_is_set=env_key in os.environ,
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
        if event.button.id == "storage-set-default":
            await self.storage_workflows.set_current_as_default()
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
        if result is None or self.current_storage_name is None:
            return
        if result.action == "clear":
            self._clear_env_key(result.env_key)
            return
        self._save_env_key(result.env_key, result.raw_value)

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
        try:
            update = set_local_env_value(
                storage_root=self._current_storage().root,
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
                storage_root=self._current_storage().root,
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
        self.storage_entries = ordered_storage_entries(self.registry)
        storage_list = self.query_one("#storage-list", ListView)
        await storage_list.clear()
        if not self.storage_entries:
            self.current_storage_name = None
            self.current_storage_kind = None
            self.local_values = {}
            self.query_one("#storage-title", Static).update(
                "No storages registered. Use New storage to add one.\n"
                f"CLI: {self.init_command}"
            )
            self._clear_field_table()
            self._set_live_controls_enabled(False)
            return
        for entry in self.storage_entries:
            await storage_list.append(
                ListItem(Label(storage_entry_label(self.registry, entry)))
            )

        selected_index = storage_entry_index(self.storage_entries, select_name)
        if selected_index is None:
            selected_index = storage_entry_index(
                self.storage_entries, self.registry.default_storage
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

    def _select_storage(self, name: str) -> None:
        """Load one storage-local env file and refresh the field table."""
        self.current_storage_name = name
        self.current_storage_kind = "live"
        record = self.registry.selected(name)
        path = local_env_path(record.root, filename=self.local_env_filename)
        path.touch(exist_ok=True)
        self.local_values = read_local_env(path)
        self.query_one("#storage-title", Static).update(
            live_storage_title(record, path)
        )
        self._populate_field_table()
        self._set_live_controls_enabled(True)

    def _select_missing_storage(self, name: str) -> None:
        """Show a registered storage whose root no longer exists."""
        self.current_storage_name = name
        self.current_storage_kind = "missing"
        record = self.registry.selected(name)
        self.local_values = {}
        self.query_one("#storage-title", Static).update(
            missing_storage_title(record)
        )
        self._clear_field_table()
        self._set_storage_controls_enabled(
            fields=False,
            set_default=False,
            delete=True,
            archive=False,
        )

    def _select_archived_storage(self, name: str) -> None:
        """Show archived metadata without enabling field editing."""
        self.current_storage_name = name
        self.current_storage_kind = "archived"
        record = self.registry.archived_storages[name]
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
        self._set_storage_controls_enabled(
            fields=enabled,
            set_default=enabled,
            delete=enabled,
            archive=enabled,
        )

    def _set_storage_controls_enabled(
        self,
        *,
        fields: bool,
        set_default: bool,
        delete: bool,
        archive: bool,
    ) -> None:
        """Enable or disable each storage-scoped editor control.

        :param fields: Whether config field rows may be edited.
        :param set_default: Whether the current storage may become default.
        :param delete: Whether the current registry row may be removed.
        :param archive: Whether the current storage directory may be archived.
        """
        self._set_controls_enabled(fields)
        self.query_one(
            "#storage-set-default", Button
        ).disabled = not set_default
        self.query_one("#storage-delete", Button).disabled = not delete
        self.query_one("#storage-archive", Button).disabled = not archive

    def _suggest_storage_name(self, path: Path) -> str:
        """Return a simple registry-name suggestion from a path."""
        return suggest_storage_name(
            path,
            fallback_name=self._fallback_storage_name(),
        )

    def _fallback_storage_name(self) -> str:
        """Return a storage selector when no path name is available."""
        if self.kit is not None:
            return self.kit.default_storage_name()
        return "apprc_stor-1"
