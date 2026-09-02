"""Interactive Textual editor for AppRC dotenv override files.

Applications declare config fields once through :mod:`apprc.definition.env_config.schema`.
This module turns those declarations into a terminal UI that inspects shell,
app-wide, storage, and packaged-default layers without writing files on open.

Rendering rules for table cells live in :mod:`apprc.interfaces.tui._rendering` so
the widget code here stays focused on Textual events, modal handling, and file
persistence.
"""

from __future__ import annotations

# == Standard Library ========================
import os
from collections.abc import Awaitable, Callable
from importlib.resources import as_file, files
from pathlib import Path
from typing import TYPE_CHECKING

# == 3rd Party ===============================
from textual.app import App, ComposeResult
from textual.containers import Horizontal, HorizontalScroll, Vertical
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
from apprc.user_files.env_files.files import read_env_file
from apprc.user_files.env_files.updates import (
    clear_env_file_value,
    clear_storage_env_value,
    set_env_file_value,
    set_storage_env_value,
)
from apprc.user_files.app_home.locations import ConfigHomeError
from apprc.user_files.storage_roots.paths import StorageRootPathError
from apprc.user_files.storage_roots.registry import (
    StorageRegistry,
    suggested_storage_name,
)
from apprc.interfaces.tui.modals import (
    ConfigValueEditScreen,
    ValueEditResult,
)
from apprc.interfaces.tui._rendering import (
    FIELD_TABLE_COLUMNS,
    active_storage_title,
    archived_storage_title,
    build_field_table_rows,
    live_storage_title,
    missing_storage_title,
)
from apprc.interfaces.tui._field_state import (
    ConfigWriteScope,
    SelectedField,
    config_value_sources,
    selected_field_for_row,
)
from apprc.interfaces.tui.storage.entries import (
    ordered_storage_entries,
    storage_entry_index,
    storage_entry_label,
    suggest_storage_name,
)
from apprc.interfaces.tui.storage.selection import (
    ActivePathStorageSelection,
    ArchivedStorageSelection,
    EditorStorageSelection,
    LiveStorageSelection,
    MissingStorageSelection,
    NoStorageSelection,
)
from apprc.interfaces.tui.editor.workflows import (
    ConfigEditorStorageWorkflows,
)
from apprc.interfaces.tui.editor.setup import ConfigEditorSetupWorkflow

if TYPE_CHECKING:
    from apprc.definition.app_config.kit import AppConfigKit


class ConfigEditorApp(App[None]):
    """Small terminal UI for editing AppRC dotenv override files."""

    CSS = """
    #storage-list {
        width: 28;
        border: solid $primary;
    }

    #editor-pane {
        width: 1fr;
        padding: 0 1;
    }

    #config-action-row {
        height: 4;
        margin: 1 0;
    }

    #config-action-row Button {
        min-width: 0;
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
        storage_registry: StorageRegistry | None,
        storage_registry_error: str | None = None,
        initial_storage: str | None = None,
        active_storage_root: Path | None = None,
        config_group_name: str = "config",
    ) -> None:
        """Keep storage table and field metadata while editing dotenv state.

        :param kit: Application config facade.
        :param storage_registry: Optional named-storage index shown by the
            editor.
        :param storage_registry_error: Read failure that prevents named-storage
            writes while direct-path editing remains available.
        :param initial_storage: Optional storage entry selected on startup.
        :param active_storage_root: Optional path-backed storage selected by
            the current CLI invocation.
        :param config_group_name: Config command group name used in generated
            guidance.
        """
        super().__init__()
        self.kit = kit
        self.storage_registry = storage_registry
        self.storage_registry_error = storage_registry_error
        self.owners = kit.spec.owners
        self.initial_storage = initial_storage
        self.config_group_name = config_group_name
        self.storage_enabled = kit.spec.storage_required()
        self.named_storage_enabled = kit.spec.named_storage_allowed()
        self.init_command = (
            f"{kit.spec.config_command_name()} "
            f"{config_group_name} storage add NAME PATH"
        )
        self.index_label = kit.spec.index_filename
        self.hidden_env_keys = (
            frozenset({kit.spec.storage_env_key})
            if kit.spec.storage_env_key is not None
            else frozenset()
        )
        if active_storage_root is not None and self.storage_enabled:
            self.active_storage_root = (
                Path(active_storage_root).expanduser().resolve()
            )
        else:
            self.active_storage_root = None
        self.app_wide_active = self._app_wide_layer_is_active()
        self.app_values = (
            read_env_file(kit.spec.app_wide_env_path())
            if self.app_wide_active
            else {}
        )
        self.shared_values = _read_packaged_shared_values(kit)
        self.storage_entries = (
            ordered_storage_entries(storage_registry)
            if storage_registry is not None
            else []
        )
        self.selection: EditorStorageSelection = NoStorageSelection()
        self.storage_values: dict[str, str] = {}
        self.row_env_keys: list[str | None] = []
        self._config_action_in_progress = False
        self.storage_workflows = ConfigEditorStorageWorkflows(self)
        self.setup_workflow = ConfigEditorSetupWorkflow(self)

    def compose(self) -> ComposeResult:
        """Compose the storage list and field editor."""
        yield Header()
        with Horizontal():
            if self.named_storage_enabled:
                yield ListView(id="storage-list")
            with Vertical(id="editor-pane"):
                yield Static("", id="storage-title")
                with HorizontalScroll(id="config-action-row"):
                    yield Button(
                        "Setup",
                        variant="primary",
                        id="config-setup",
                    )
                    if self.named_storage_enabled:
                        yield Button(
                            "New",
                            id="storage-new",
                        )
                        yield Button(
                            "Register",
                            id="storage-register-active",
                            disabled=True,
                        )
                        yield Button(
                            "Rename",
                            id="storage-rename",
                            disabled=True,
                        )
                        yield Button(
                            "Location",
                            id="storage-location",
                            disabled=True,
                        )
                        yield Button(
                            "Move",
                            id="storage-move",
                            disabled=True,
                        )
                        yield Button(
                            "Archive",
                            id="storage-archive",
                            disabled=True,
                        )
                        yield Button(
                            "Delete",
                            id="storage-delete",
                            disabled=True,
                        )
                yield DataTable(id="field-table")
        yield Footer()

    async def on_mount(self) -> None:
        """Populate selectable sources and select the active one."""
        await self._refresh_storage_list(select_name=self.initial_storage)
        if self.storage_registry_error is not None:
            self.notify(
                self.storage_registry_error,
                severity="error",
                markup=False,
            )

    async def action_quit(self) -> None:
        """Keep an in-flight config action from being canceled on exit."""
        if self._config_action_in_progress:
            self.notify(
                "Finish the current config action before quitting.",
                severity="warning",
            )
            return
        await super().action_quit()

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Switch the edited dotenv file when a storage is selected."""
        if self._config_action_in_progress:
            return
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
        self._select_archived_storage(entry.name)
        self._start_config_action(
            lambda: self.storage_workflows.restore_or_prune_archived_storage(
                entry.name
            )
        )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Open a modal editor when a config field row is selected."""
        del event
        if self._config_action_in_progress:
            return
        self._open_selected_field_editor()

    def _open_selected_field_editor(self) -> None:
        """Open the modal editor for the current table row."""
        if self._config_action_in_progress:
            return
        selected = self._selected_field()
        if selected is None:
            return
        if not selected.spec.editable:
            self.notify(
                f"This setting is managed by {self.index_label}.",
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
                    app_values=self.app_values,
                    storage_values=self.storage_values,
                    shell_env=os.environ,
                    shared_values=self.shared_values,
                    include_app=self.app_wide_active,
                    include_storage=self._storage_scope_is_active(),
                ),
                writable_scopes=self._writable_scopes(),
            ),
            self._handle_edit_result,
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle config action button clicks."""
        if event.button.id == "config-setup":
            self._start_config_action(self.setup_workflow.open_setup_flow)
            return
        if event.button.id == "storage-new":
            self._start_config_action(
                self.storage_workflows.open_new_storage_flow
            )
            return
        if event.button.id == "storage-register-active":
            self._start_config_action(
                self.storage_workflows.register_active_storage_flow
            )
            return
        if event.button.id == "storage-rename":
            self._start_config_action(
                self.storage_workflows.open_rename_storage_flow
            )
            return
        if event.button.id == "storage-location":
            self._start_config_action(
                self.storage_workflows.open_storage_location_flow
            )
            return
        if event.button.id == "storage-move":
            self._start_config_action(
                self.storage_workflows.open_move_storage_flow
            )
            return
        if event.button.id == "storage-delete":
            self._start_config_action(
                self.storage_workflows.open_delete_storage_flow
            )
            return
        if event.button.id == "storage-archive":
            self._start_config_action(
                self.storage_workflows.open_archive_storage_flow
            )

    def _start_config_action(
        self,
        workflow: Callable[[], Awaitable[None]],
    ) -> None:
        """Run one config workflow while preventing conflicting edits.

        :param workflow: Async config operation to run after the action lock
            is active.
        """
        if self._config_action_in_progress:
            self.notify(
                "Finish the current config action before starting another.",
                severity="warning",
            )
            return
        self._config_action_in_progress = True
        self._disable_config_action_controls()
        self.run_worker(
            self._run_config_action(workflow),
            group="config-actions",
        )

    async def _run_config_action(
        self,
        workflow: Callable[[], Awaitable[None]],
    ) -> None:
        """Complete a locked workflow and restore controls from selection.

        :param workflow: Async config operation that owns the active lock.
        """
        try:
            await workflow()
        finally:
            self._config_action_in_progress = False
            await self._refresh_storage_list(
                select_name=self._selected_storage_name()
            )

    def _disable_config_action_controls(self) -> None:
        """Block controls that could conflict with a config action."""
        self.query_one("#field-table", DataTable).disabled = True
        self.query_one("#config-setup", Button).disabled = True
        if not self.named_storage_enabled:
            return
        self.query_one("#storage-list", ListView).disabled = True
        for button_id in (
            "storage-new",
            "storage-register-active",
            "storage-rename",
            "storage-location",
            "storage-move",
            "storage-archive",
            "storage-delete",
        ):
            self.query_one(f"#{button_id}", Button).disabled = True

    def _handle_edit_result(self, result: ValueEditResult | None) -> None:
        """Persist the value returned by the edit modal."""
        if result is None:
            return
        if result.action == "clear":
            self._clear_env_key(result.env_key, scope=result.scope)
            return
        self._save_env_key(
            result.env_key,
            result.raw_value,
            scope=result.scope,
        )

    def _require_storage_registry(self) -> StorageRegistry | None:
        """Return the storage table required for multi-storage editor actions."""
        if self.storage_registry is None:
            if self.storage_registry_error is not None:
                self.notify(
                    self.storage_registry_error,
                    severity="error",
                    markup=False,
                )
                return None
            self.notify(
                "Storage management requires a named-storage index.",
                severity="error",
            )
            return None
        return self.storage_registry

    def _save_env_key(
        self,
        env_key: str,
        raw_value: str,
        *,
        scope: ConfigWriteScope,
    ) -> None:
        """Validate and persist one app-wide or storage env value."""
        try:
            if scope == "app":
                update = set_env_file_value(
                    path=self.kit.spec.app_wide_env_path(),
                    reference=env_key,
                    raw_value=raw_value,
                    owners=self.owners,
                    layer_name=self.kit.spec.app_wide_env_filename,
                )
            else:
                update = set_storage_env_value(
                    storage_root=self._current_storage_root(),
                    reference=env_key,
                    raw_value=raw_value,
                    owners=self.owners,
                    storage_env_filename=self.kit.spec.storage_env_filename,
                )
        except (
            ConfigHomeError,
            OSError,
            StorageRootPathError,
            TypeError,
            ValueError,
        ) as exc:
            self.notify(str(exc), severity="error", markup=False)
            return
        self._refresh_values_after_write(scope=scope, path=update.path)
        self._populate_field_table()
        self.notify(f"Saved {update.env_key}")

    def _clear_env_key(
        self,
        env_key: str,
        *,
        scope: ConfigWriteScope,
    ) -> None:
        """Remove one key from an app-wide or storage env file."""
        try:
            if scope == "app":
                update = clear_env_file_value(
                    path=self.kit.spec.app_wide_env_path(),
                    reference=env_key,
                    owners=self.owners,
                    layer_name=self.kit.spec.app_wide_env_filename,
                )
            else:
                update = clear_storage_env_value(
                    storage_root=self._current_storage_root(),
                    reference=env_key,
                    owners=self.owners,
                    storage_env_filename=self.kit.spec.storage_env_filename,
                )
        except (
            ConfigHomeError,
            OSError,
            StorageRootPathError,
            ValueError,
        ) as exc:
            self.notify(str(exc), severity="error", markup=False)
            return
        if update is None:
            return
        self._refresh_values_after_write(scope=scope, path=update.path)
        self._populate_field_table()
        self.notify(f"Cleared {update.env_key}")

    async def _refresh_storage_list(
        self,
        *,
        select_name: str | None = None,
    ) -> None:
        """Reload storage rows and select the requested storage."""
        registry = self.storage_registry if self.named_storage_enabled else None
        self.storage_entries = (
            ordered_storage_entries(registry) if registry is not None else []
        )
        if not self.storage_enabled:
            self._select_app_wide()
            return
        if not self.named_storage_enabled:
            if self.active_storage_root is not None:
                self._select_active_storage()
                return
            self._select_app_wide()
            return
        storage_list = self.query_one("#storage-list", ListView)
        await storage_list.clear()
        if not self.storage_entries:
            if self.active_storage_root is not None:
                self._select_active_storage()
                return
            self._select_app_wide()
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
        """Load the env-selected active path without requiring a named row."""
        root = self.active_storage_root
        if root is None:
            return
        self.selection = ActivePathStorageSelection(root=root)
        path = self._env_file_path_for_root(root)
        self.storage_values = read_env_file(path)
        self.query_one("#storage-title", Static).update(
            active_storage_title(root, path)
        )
        self._populate_field_table()
        self._set_storage_controls_enabled(
            fields=True,
            register_active=self.storage_registry is not None,
            rename=False,
            location=False,
            move=False,
            delete=False,
            archive=False,
        )

    def _select_storage(self, name: str) -> None:
        """Load one storage env file and refresh the field table."""
        registry = self._require_storage_registry()
        if registry is None:
            return
        record = registry.selected(name)
        self.selection = LiveStorageSelection(record=record)
        path = self._env_file_path_for_root(record.root)
        self.storage_values = read_env_file(path)
        self.query_one("#storage-title", Static).update(
            live_storage_title(record, path)
        )
        self._populate_field_table()
        self._set_live_controls_enabled(True)

    def _select_missing_storage(self, name: str) -> None:
        """Show a registered storage whose root no longer exists."""
        registry = self._require_storage_registry()
        if registry is None:
            return
        record = registry.selected(name)
        self.selection = MissingStorageSelection(record=record)
        self.storage_values = {}
        self.query_one("#storage-title", Static).update(
            missing_storage_title(record)
        )
        self._clear_field_table()
        self._set_storage_controls_enabled(
            fields=False,
            register_active=False,
            rename=True,
            location=True,
            move=False,
            delete=True,
            archive=False,
        )

    def _select_archived_storage(self, name: str) -> None:
        """Show archived metadata without enabling field editing."""
        registry = self._require_storage_registry()
        if registry is None:
            return
        record = registry.archived_storages[name]
        self.selection = ArchivedStorageSelection(record=record)
        self.storage_values = {}
        self.query_one("#storage-title", Static).update(
            archived_storage_title(record)
        )
        self._clear_field_table()
        self._set_live_controls_enabled(False)

    def _select_app_wide(self) -> None:
        """Show app-wide/shell/default sources when no storage is selected."""
        self._clear_selection()
        self.query_one("#storage-title", Static).update(
            self._no_storage_message()
        )
        self._populate_field_table()
        self._set_storage_controls_enabled(
            fields=True,
            register_active=False,
            rename=False,
            location=False,
            move=False,
            delete=False,
            archive=False,
        )

    def _populate_field_table(self) -> None:
        """Render every known config field for the active storage."""
        table = self.query_one("#field-table", DataTable)
        table.clear(columns=True)
        table.cursor_type = "row"
        table.add_columns(*FIELD_TABLE_COLUMNS)
        self.row_env_keys = []
        for row in build_field_table_rows(
            owners=self.owners,
            app_values=self.app_values,
            storage_values=self.storage_values,
            shared_values=self.shared_values,
            include_app=self.app_wide_active,
            include_storage=self._storage_scope_is_active(),
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

    def _current_storage_root(self) -> Path:
        """Return the selected editable storage root."""
        selection = self.selection
        if isinstance(selection, ActivePathStorageSelection):
            return selection.root
        if isinstance(selection, LiveStorageSelection):
            return selection.record.root
        raise RuntimeError("No editable storage is selected.")

    def _env_file_path_for_root(self, root: Path) -> Path:
        """Return the editable dotenv path below one current root."""
        return (
            Path(root).expanduser().resolve()
            / self.kit.spec.storage_env_filename
        )

    def _set_controls_enabled(self, enabled: bool) -> None:
        """Enable or disable editor controls."""
        self.query_one("#field-table", DataTable).disabled = (
            self._config_action_in_progress or not enabled
        )
        self.query_one(
            "#config-setup", Button
        ).disabled = self._config_action_in_progress

    def _set_live_controls_enabled(self, enabled: bool) -> None:
        """Enable storage-specific controls only for live storages."""
        self._set_storage_controls_enabled(
            fields=enabled,
            register_active=False,
            rename=enabled,
            location=enabled,
            move=enabled,
            delete=enabled,
            archive=enabled,
        )

    def _set_storage_controls_enabled(
        self,
        *,
        fields: bool,
        register_active: bool,
        rename: bool,
        location: bool,
        move: bool,
        delete: bool,
        archive: bool,
    ) -> None:
        """Enable or disable each storage-scoped editor control.

        :param fields: Whether config field rows may be edited.
        :param register_active: Whether the active path may be registered.
        :param rename: Whether the selected named storage may be renamed.
        :param location: Whether the selected named storage may be repointed.
        :param move: Whether the selected storage directory may be moved.
        :param delete: Whether the current named storage may be removed.
        :param archive: Whether the current storage directory may be archived.
        """
        self._set_controls_enabled(fields)
        if not self.named_storage_enabled:
            return
        self.query_one(
            "#storage-list", ListView
        ).disabled = self._config_action_in_progress
        self.query_one("#storage-new", Button).disabled = (
            self._config_action_in_progress or self.storage_registry is None
        )
        self.query_one("#storage-register-active", Button).disabled = (
            self._config_action_in_progress or not register_active
        )
        self.query_one("#storage-rename", Button).disabled = (
            self._config_action_in_progress or not rename
        )
        self.query_one("#storage-location", Button).disabled = (
            self._config_action_in_progress or not location
        )
        self.query_one("#storage-move", Button).disabled = (
            self._config_action_in_progress or not move
        )
        self.query_one("#storage-delete", Button).disabled = (
            self._config_action_in_progress or not delete
        )
        self.query_one("#storage-archive", Button).disabled = (
            self._config_action_in_progress or not archive
        )

    def _clear_selection(self) -> None:
        """Clear storage selection and storage values."""
        self.selection = NoStorageSelection()
        self.storage_values = {}

    def _selected_storage_name(self) -> str | None:
        """Return the current named row for control-state restoration."""
        selection = self.selection
        if isinstance(
            selection,
            LiveStorageSelection
            | MissingStorageSelection
            | ArchivedStorageSelection,
        ):
            return selection.record.name
        return None

    def _refresh_values_after_write(
        self,
        *,
        scope: ConfigWriteScope,
        path: Path,
    ) -> None:
        """Refresh cached source values after a scoped save."""
        if scope == "app":
            self.app_wide_active = True
            self.app_values = read_env_file(path)
            return
        self.storage_values = read_env_file(path)

    def _app_wide_layer_is_active(self) -> bool:
        """Return whether app-wide sources should be visible."""
        if not self.kit.spec.app_wide_allowed():
            return False
        return (
            self.kit.spec.app_wide_default()
            or self.kit.spec.app_wide_env_path().is_file()
        )

    def _storage_scope_is_active(self) -> bool:
        """Return whether the current selection can read/write storage env."""
        return isinstance(
            self.selection,
            ActivePathStorageSelection | LiveStorageSelection,
        )

    def _writable_scopes(self) -> tuple[ConfigWriteScope, ...]:
        """Return write scopes currently available for the selected field."""
        scopes: list[ConfigWriteScope] = []
        if self.app_wide_active:
            scopes.append("app")
        if self._storage_scope_is_active():
            scopes.append("storage")
        return tuple(scopes)

    def _registered_active_storage_name(self) -> str | None:
        """Return the named storage that matches the active path, if any."""
        if self.active_storage_root is None or self.storage_registry is None:
            return None
        for name in sorted(self.storage_registry.storages):
            record = self.storage_registry.storages[name]
            record_root = Path(record.root).expanduser().resolve()
            if record_root == self.active_storage_root:
                return name
        return None

    def _suggest_storage_name(self, path: Path) -> str:
        """Return a simple storage-name suggestion from a path."""
        return suggest_storage_name(
            path,
            fallback_name=self._fallback_storage_name(),
        )

    def _fallback_storage_name(self) -> str:
        """Return a storage selector when no path name is available."""
        return suggested_storage_name(self.kit.spec.app_name)

    def _no_storage_message(self) -> str:
        """Return empty-list guidance for current multi-storage capability."""
        if not self.storage_enabled:
            return self._app_wide_message()
        if self.app_wide_active and self.active_storage_root is None:
            return (
                f"{self._app_wide_message()}\n\n"
                "No active storage path is selected."
            )
        storage_env_key = self.kit.spec.require_storage_env_key()
        if self.storage_registry is not None:
            return (
                "No storages registered. Use New storage to add one, or set "
                f"{storage_env_key} to edit an active path.\n"
                f"CLI: {self.init_command}"
            )
        return (
            "No active storage path is selected. Set "
            f"{storage_env_key} to edit a storage env file. Create a "
            "named-storage index to enable storage management actions."
        )

    def _app_wide_message(self) -> str:
        """Return source guidance for the app-wide layer."""
        if self.app_wide_active:
            return (
                "Editing app-wide settings from the AppRC config home:\n"
                f"{self.kit.spec.app_wide_env_path()}"
            )
        return (
            "No AppRC writable layer is active. Existing shell environment "
            "values and packaged defaults are shown."
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
        return read_env_file(path)
