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
)
from apprc.interfaces.tui.editor.storage_base import StorageWorkflowBase
from apprc.interfaces.tui.modals import ProgressScreen


class StorageArchiveWorkflows(StorageWorkflowBase):
    """Run storage archive and extraction progress modals."""

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
