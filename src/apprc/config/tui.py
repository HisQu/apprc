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
import shutil
from collections.abc import Callable
from dataclasses import dataclass
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
from apprc.config.paths import normalize_storage_root_path
from apprc.config.schema import ConfigOwner
from apprc.config.storage_archive import (
    StorageArchiveProgress,
    archive_directory,
    extract_archive,
    is_storage_archive_path,
    storage_archive_default_path,
    storage_root_name_from_archive,
)
from apprc.config.storage_registry import StorageRecord, StorageRegistry
from apprc.config.tui_primitives import (
    ButtonVariant,
    ConfirmScreen,
    PathInputScreen,
    StorageNameScreen,
)
from apprc.config.tui_modals import (
    ArchiveOptionsScreen,
    ConfigValueEditScreen,
    DefaultPathScreen,
    ProgressScreen,
    ValueEditResult,
)
from apprc.config.tui_rendering import (
    FIELD_TABLE_COLUMNS,
    build_field_table_rows,
)
from apprc.config.tui_field_state import (
    SelectedField,
    archived_storage_title,
    live_storage_title,
    missing_storage_title,
    selected_field_for_row,
)
from apprc.config.tui_storage_entries import (
    StorageEntryKind,
    ordered_existing_storage_names,
    ordered_storage_entries,
    storage_entry_index,
    storage_entry_label,
    suggest_storage_name,
)

if TYPE_CHECKING:
    from apprc.config.kit import AppConfigKit


@dataclass(frozen=True, slots=True)
class _RemovalDefaultChoice:
    """Default replacement chosen before removing a live storage."""

    replacement_name: str | None = None
    create_default_path: Path | None = None


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
            self._restore_or_prune_archived_storage(entry.name),
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

    def _handle_edit_result(self, result: ValueEditResult | None) -> None:
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
            PathInputScreen(
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
            PathInputScreen(
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
                ConfirmScreen(
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
            StorageNameScreen(
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
                ConfirmScreen(
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
                    ConfirmScreen(
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
            ConfirmScreen(
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
            self.current_storage_kind not in {"live", "missing"}
            or self.current_storage_name is None
        ):
            return
        record = self._current_storage()
        can_delete_content = record.root.is_dir()
        message = (
            f"Storage: {record.name}\nRoot: {record.root}\n\n"
            "Choose whether to only unregister it or delete the "
            "directory contents too."
            if can_delete_content
            else (
                f"Storage: {record.name}\nRoot: {record.root}\n\n"
                "The storage root is missing or is not a directory. "
                "Only the registry entry will be removed."
            )
        )
        actions: tuple[tuple[str, str, ButtonVariant], ...] = (
            (
                ("unregister", "Unregister only", "warning"),
                (
                    "delete-content",
                    "Delete directory and unregister",
                    "error",
                ),
            )
            if can_delete_content
            else (("unregister", "Unregister only", "warning"),)
        )
        action = await self.push_screen_wait(
            ConfirmScreen(
                title="Delete storage",
                message=message,
                actions=actions,
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
            ArchiveOptionsScreen(
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
                replacement_name = kit.default_storage_name()
                self.registry = kit.register_storage(
                    name=replacement_name,
                    root=replacement.create_default_path,
                    make_default=True,
                )
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            return False
        select_name = replacement.replacement_name
        if select_name is None and replacement.create_default_path is not None:
            select_name = kit.default_storage_name()
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
            for name in ordered_existing_storage_names(self.registry)
            if name != removed_name
        ]
        if remaining:
            actions: list[tuple[str, str, ButtonVariant]] = []
            for index, name in enumerate(remaining):
                variant: ButtonVariant = "primary" if index == 0 else "default"
                actions.append((f"default-{name}", name, variant))
            action = await self.push_screen_wait(
                ConfirmScreen(
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
            DefaultPathScreen(
                default_path=kit.default_storage_data_root(),
                display_name=kit.spec.display_name,
            )
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
        return await self._run_storage_progress(
            title="Compressing storage",
            operation=lambda progress: archive_directory(
                source_root=source_root,
                archive_path=archive_path,
                progress=progress,
            ),
        )

    async def _run_extract_progress(
        self,
        *,
        archive_path: Path,
        destination_root: Path,
    ) -> Path:
        """Run archive extraction with a progress modal."""
        return await self._run_storage_progress(
            title="Decompressing storage",
            operation=lambda progress: extract_archive(
                archive_path=archive_path,
                destination_root=destination_root,
                progress=progress,
            ),
        )

    async def _run_storage_progress(
        self,
        *,
        title: str,
        operation: Callable[[Callable[[StorageArchiveProgress], None]], Path],
    ) -> Path:
        """Run one storage archive operation with a progress modal.

        :param title: Modal title shown above the progress bar.
        :param operation: Blocking storage operation that accepts progress
            callbacks and returns the final path.
        :return: Path returned by the storage operation.
        """
        progress_screen = ProgressScreen(title=title)
        await self.push_screen(progress_screen)

        def progress(progress_update: StorageArchiveProgress) -> None:
            self.call_from_thread(
                progress_screen.update_progress, progress_update
            )

        worker = self.run_worker(
            lambda: operation(progress),
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
        try:
            update = set_local_env_value(
                storage_root=self._current_storage().root,
                reference=env_key,
                raw_value=raw_value,
                owners=self.owners,
                local_env_filename=self.local_env_filename,
            )
        except (TypeError, ValueError) as exc:
            self.notify(str(exc), severity="error")
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
            self.notify(str(exc), severity="error")
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
