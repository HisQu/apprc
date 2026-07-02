"""Storage workflow orchestration for the config editor TUI."""

from __future__ import annotations

# == Internal ================================
from apprc.user_files.storage_roots.archive import (
    is_storage_archive_path,
    storage_archive_default_path,
)
from apprc.user_files.storage_roots.registry import record_archived_storage
from apprc.interfaces.tui._primitives import PathInputScreen
from apprc.interfaces.tui._styles import path_markup
from apprc.interfaces.tui.editor.storage_archive import StorageArchiveWorkflows
from apprc.interfaces.tui.editor.storage_registration import (
    StorageRegistrationWorkflows,
)
from apprc.interfaces.tui.editor.storage_removal import StorageRemovalWorkflows
from apprc.interfaces.tui.modals import ArchiveOptionsScreen
from apprc.interfaces.tui.storage.selection import LiveStorageSelection


class ConfigEditorStorageWorkflows(
    StorageArchiveWorkflows,
    StorageRegistrationWorkflows,
    StorageRemovalWorkflows,
):
    """Coordinate storage-management actions for :class:`ConfigEditorApp`."""

    async def open_new_storage_flow(self) -> None:
        """Prompt for a new directory or archive path and register it."""
        if self.editor._require_storage_registry() is None:
            return
        result = await self.editor.push_screen_wait(
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
            await self.open_archive_import_flow(path)
            return
        await self.register_storage_directory_flow(
            path,
            default_name=self.editor._suggest_storage_name(path),
        )

    async def open_archive_storage_flow(self) -> None:
        """Prompt for archive options and compress the selected storage."""
        registry = self.editor._require_storage_registry()
        selection = self.editor.selection
        if registry is None or not isinstance(selection, LiveStorageSelection):
            return
        record = selection.record
        options = await self.editor.push_screen_wait(
            ArchiveOptionsScreen(
                storage_name=record.name,
                source_root=record.root,
                default_archive=storage_archive_default_path(record.root),
            )
        )
        if options is None:
            return
        try:
            archive_path = await self.run_archive_progress(
                source_root=record.root,
                archive_path=options.archive_path,
            )
        except ValueError as exc:
            self.editor.notify(str(exc), severity="error", markup=False)
            return
        self.editor.storage_registry = record_archived_storage(
            name=record.name,
            archive=archive_path,
            source_root=record.root,
            path=registry.path,
        )
        if options.delete_source:
            removed = await self.remove_live_storage(
                record.name,
                delete_content=True,
            )
            if not removed:
                await self.editor._refresh_storage_list(select_name=record.name)
                self.editor.notify(
                    f"Archived {record.name!r}; source deletion was canceled.",
                    severity="warning",
                )
                return
        else:
            await self.editor._refresh_storage_list(select_name=record.name)
        self.editor.notify(
            f"Archived storage {record.name!r} to {path_markup(archive_path)}"
        )
