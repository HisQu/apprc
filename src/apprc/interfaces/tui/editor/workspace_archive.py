"""Workspace archive import and progress workflows for the config editor TUI."""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Callable
from pathlib import Path

from apprc.interfaces.tui.editor.workspace_base import WorkspaceWorkflowBase
from apprc.interfaces.tui.modals import ProgressScreen

# == Internal ================================
from apprc.user_files.workspace_roots.archive import WorkspaceArchiveProgress


class WorkspaceArchiveWorkflows(WorkspaceWorkflowBase):
    """Run workspace archive and extraction progress modals."""

    async def run_archive_progress(
        self,
        *,
        name: str,
        archive_path: Path,
    ) -> Path:
        """Run archive compression with a progress modal.

        :param name: Registered workspace to compress.
        :param archive_path: Archive path to write.
        :return: Written archive path.
        """
        return await self.run_workspace_progress(
            title="Compressing workspace",
            operation=lambda progress: (
                self.require_workspace_manager().archive_workspace(
                    name=name,
                    destination=archive_path,
                    progress=progress,
                )
            ),
        )

    async def run_extract_progress(
        self,
        *,
        archive_path: Path,
        destination_root: Path,
        replace_existing: bool = False,
        name: str,
        archived_name: str | None = None,
    ) -> Path:
        """Run archive extraction with a progress modal.

        :param archive_path: Existing archive to extract.
        :param destination_root: Directory that receives archive contents.
        :param replace_existing: Whether a non-empty destination may be
            replaced.
        :param name: Restored workspace name.
        :param archived_name: Archive record to consume.
        :return: Destination directory.
        """
        return await self.run_workspace_progress(
            title="Decompressing workspace",
            operation=lambda progress: (
                self.require_workspace_manager().restore_workspace(
                    name=name,
                    archived_name=archived_name,
                    archive=archive_path,
                    destination=destination_root,
                    progress=progress,
                    replace_existing=replace_existing,
                )
            ),
        )

    async def run_workspace_progress(
        self,
        *,
        title: str,
        operation: Callable[[Callable[[WorkspaceArchiveProgress], None]], Path],
    ) -> Path:
        """Run one workspace archive operation with a progress modal.

        :param title: Modal title shown above the progress bar.
        :param operation: Blocking workspace operation that accepts progress
            callbacks and returns the final path.
        :return: Path returned by the workspace operation.
        """
        progress_screen = ProgressScreen(title=title)
        await self.editor.push_screen(progress_screen)

        def progress(progress_update: WorkspaceArchiveProgress) -> None:
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
