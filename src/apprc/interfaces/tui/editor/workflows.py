"""Storage workflow orchestration for the config editor TUI."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path

# == Internal ================================
from apprc.user_files.storage_roots.archive import (
    is_storage_archive_path,
    storage_archive_default_path,
    storage_root_name_from_archive,
)
from apprc.user_files.storage_roots.paths import normalize_storage_root_path
from apprc.user_files.storage_roots.registry import (
    record_archived_storage,
    remove_archived_storage,
)
from apprc.interfaces.tui._primitives import ConfirmScreen, PathInputScreen
from apprc.interfaces.tui._styles import (
    lines_text,
    path_markup,
    path_text,
)
from apprc.interfaces.tui.editor.storage_archive import StorageArchiveWorkflows
from apprc.interfaces.tui.editor.storage_editing import StorageEditingWorkflows
from apprc.interfaces.tui.editor.storage_registration import (
    StorageRegistrationWorkflows,
)
from apprc.interfaces.tui.editor.storage_removal import StorageRemovalWorkflows
from apprc.interfaces.tui.modals import ArchiveOptionsScreen
from apprc.interfaces.tui.storage.selection import LiveStorageSelection


class ConfigEditorStorageWorkflows(
    StorageArchiveWorkflows,
    StorageEditingWorkflows,
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

    async def open_archive_import_flow(
        self,
        archive_path: Path,
        *,
        default_name: str | None = None,
        default_destination: Path | None = None,
    ) -> None:
        """Restore an archive path, then register the destination.

        :param archive_path: Archive selected by the user or registry.
        :param default_name: Optional restored storage name.
        :param default_destination: Optional restored storage root path.
        """
        archive = archive_path.expanduser()
        if not archive.is_file():
            self.editor.notify(
                f"Storage archive does not exist: {path_markup(archive)}",
                severity="error",
            )
            return
        restored_name = default_name or storage_root_name_from_archive(archive)
        destination = default_destination or archive.parent / restored_name
        result = await self.editor.push_screen_wait(
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
            self.editor.notify(str(exc), severity="error", markup=False)
            return
        replace_existing = False
        if normalized_destination.exists() and any(
            normalized_destination.iterdir()
        ):
            action = await self.editor.push_screen_wait(
                ConfirmScreen(
                    title="Destination is not empty",
                    message=lines_text(
                        "Restoring the archive will replace files in:",
                        path_text(normalized_destination),
                        "",
                        "Proceed?",
                    ),
                    actions=(("confirm", "Proceed", "warning"),),
                )
            )
            if action != "confirm":
                return
            replace_existing = True
        try:
            await self.run_extract_progress(
                archive_path=archive,
                destination_root=normalized_destination,
                replace_existing=replace_existing,
            )
        except ValueError as exc:
            self.editor.notify(str(exc), severity="error", markup=False)
            return
        await self.register_storage_directory_flow(
            normalized_destination,
            default_name=self.editor._suggest_storage_name(Path(restored_name)),
        )

    async def restore_or_prune_archived_storage(self, name: str) -> None:
        """Restore an archived row or delete it when its file is gone.

        :param name: Archived storage selector.
        """
        registry = self.editor._require_storage_registry()
        if registry is None:
            return
        record = registry.archived_storages.get(name)
        if record is None:
            return
        if not record.archive.is_file():
            self.editor.storage_registry = remove_archived_storage(
                name=name,
                path=registry.path,
            )
            await self.editor._refresh_storage_list()
            self.editor.notify(
                f"Removed stale archive entry {name!r}; file was not found.",
                severity="warning",
            )
            return
        await self.open_archive_import_flow(
            record.archive,
            default_name=record.name,
            default_destination=record.source_root,
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
