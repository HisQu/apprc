"""Storage archive import and progress workflows for the config editor TUI."""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Callable
from pathlib import Path

# == Internal ================================
from apprc.user_files.storage_roots.archive import (
    StorageArchiveProgress,
    archive_directory,
    extract_archive,
    storage_root_name_from_archive,
)
from apprc.user_files.storage_roots.paths import normalize_storage_root_path
from apprc.user_files.storage_roots.registry import remove_archived_storage
from apprc.interfaces.tui._primitives import ConfirmScreen, PathInputScreen
from apprc.interfaces.tui._styles import (
    lines_text,
    path_markup,
    path_text,
)
from apprc.interfaces.tui.editor.storage_base import StorageWorkflowBase
from apprc.interfaces.tui.modals import ProgressScreen


class StorageArchiveWorkflows(StorageWorkflowBase):
    """Restore archived storage roots and run archive progress modals."""

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

    async def run_archive_progress(
        self,
        *,
        source_root: Path,
        archive_path: Path,
    ) -> Path:
        """Run archive compression with a progress modal.

        :param source_root: Storage root to compress.
        :param archive_path: Archive path to write.
        :return: Written archive path.
        """
        return await self.run_storage_progress(
            title="Compressing storage",
            operation=lambda progress: archive_directory(
                source_root=source_root,
                archive_path=archive_path,
                progress=progress,
            ),
        )

    async def run_extract_progress(
        self,
        *,
        archive_path: Path,
        destination_root: Path,
        replace_existing: bool = False,
    ) -> Path:
        """Run archive extraction with a progress modal.

        :param archive_path: Existing archive to extract.
        :param destination_root: Directory that receives archive contents.
        :param replace_existing: Whether a non-empty destination may be
            replaced.
        :return: Destination directory.
        """
        return await self.run_storage_progress(
            title="Decompressing storage",
            operation=lambda progress: extract_archive(
                archive_path=archive_path,
                destination_root=destination_root,
                progress=progress,
                replace_existing=replace_existing,
            ),
        )

    async def run_storage_progress(
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
        await self.editor.push_screen(progress_screen)

        def progress(progress_update: StorageArchiveProgress) -> None:
            self.editor.call_from_thread(
                progress_screen.update_progress,
                progress_update,
            )

        worker = self.editor.run_worker(
            lambda: operation(progress),
            thread=True,
            exit_on_error=False,
        )
        try:
            return await worker.wait()
        finally:
            progress_screen.dismiss(None)
