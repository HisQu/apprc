"""Workspace workflow orchestration for the config editor TUI."""

from __future__ import annotations

# == Standard Library ========================
import asyncio
from pathlib import Path

# == Internal ================================
from apprc.interfaces.tui._primitives import (
    ConfirmScreen,
    PathInputScreen,
    WorkspaceNameScreen,
)
from apprc.interfaces.tui._styles import lines_text, path_markup, path_text
from apprc.interfaces.tui.editor.workspace_archive import (
    WorkspaceArchiveWorkflows,
)
from apprc.interfaces.tui.editor.workspace_base import (
    WorkspaceActionResult,
)
from apprc.interfaces.tui.editor.workspace_editing import (
    WorkspaceEditingWorkflows,
)
from apprc.interfaces.tui.editor.workspace_registration import (
    WorkspaceRegistrationWorkflows,
)
from apprc.interfaces.tui.editor.workspace_removal import (
    WorkspaceRemovalWorkflows,
)
from apprc.interfaces.tui.modals import ArchiveOptionsScreen
from apprc.interfaces.tui.workspaces.selection import LiveWorkspaceSelection
from apprc.user_files.workspace_roots.archive import (
    is_workspace_archive_path,
    workspace_archive_default_path,
    workspace_root_name_from_archive,
)
from apprc.user_files.workspace_roots.paths import normalize_workspace_root_path


class ConfigEditorWorkspaceWorkflows(
    WorkspaceArchiveWorkflows,
    WorkspaceEditingWorkflows,
    WorkspaceRegistrationWorkflows,
    WorkspaceRemovalWorkflows,
):
    """Coordinate workspace registration, editing, removal, and archives."""

    async def open_new_workspace_flow(self) -> WorkspaceActionResult | None:
        """Prompt for a workspace directory or archive to restore."""
        if self.require_workspace_registry() is None:
            return None
        result = await self.context.app.push_screen_wait(
            PathInputScreen(
                title="New workspace",
                message="Enter a directory or an archived *.apprc.tar.xz.",
                placeholder="Directory or archive path",
            )
        )
        if result is None:
            return None
        path = result.path.expanduser()
        if is_workspace_archive_path(path):
            return await self.open_workspace_archive_flow(path)
        return await self.register_workspace_directory_flow(
            path,
            default_name=self.suggest_workspace_name(path),
        )

    async def open_workspace_archive_flow(
        self,
        archive_path: Path,
        *,
        default_name: str | None = None,
        default_destination: Path | None = None,
    ) -> WorkspaceActionResult | None:
        """Restore an archive and register its workspace destination."""
        archive = archive_path.expanduser()
        if not archive.is_file():
            self.context.app.notify(
                f"Workspace archive does not exist: {path_markup(archive)}",
                severity="error",
            )
            return None
        registry = self.require_workspace_registry()
        if registry is None:
            return None
        proposed = default_name or workspace_root_name_from_archive(archive)
        name_result = await self.context.app.push_screen_wait(
            WorkspaceNameScreen(
                default_name=self.suggest_workspace_name(Path(proposed)),
                message="Choose the restored workspace name.",
            )
        )
        if name_result is None:
            return None
        name = name_result.name
        if name in registry.workspaces or (
            name in registry.archived_workspaces and name != default_name
        ):
            self.context.app.notify(
                f"Workspace name {name!r} is already in use.",
                severity="error",
                markup=False,
            )
            return None
        destination = default_destination or archive.parent / proposed
        result = await self.context.app.push_screen_wait(
            PathInputScreen(
                title="Restore archived workspace",
                message="Enter destination directory for the restored workspace.",
                placeholder="Destination directory",
                value=str(destination),
            )
        )
        if result is None:
            return None
        try:
            root = normalize_workspace_root_path(result.path).resolve()
            replace_existing = root.exists() and any(root.iterdir())
        except (OSError, ValueError) as exc:
            self.context.app.notify(str(exc), severity="error", markup=False)
            return None
        if replace_existing:
            action = await self.context.app.push_screen_wait(
                ConfirmScreen(
                    title="Destination is not empty",
                    message=lines_text(
                        "Restoring the archive will replace files in:",
                        path_text(root),
                        "",
                        "Proceed?",
                    ),
                    actions=(("confirm", "Proceed", "warning"),),
                )
            )
            if action != "confirm":
                return None
        try:
            await self.run_extract_progress(
                archive_path=archive,
                destination_root=root,
                replace_existing=replace_existing,
                name=name,
                archived_name=default_name,
            )
        except (OSError, ValueError) as exc:
            self.context.app.notify(str(exc), severity="error", markup=False)
            return None
        self.context.app.notify(f"Restored workspace {name!r}")
        return WorkspaceActionResult(select_name=name)

    async def restore_or_prune_archived_workspace(
        self,
        name: str,
    ) -> WorkspaceActionResult | None:
        """Restore an archived row or remove metadata for a missing archive."""
        registry = self.require_workspace_registry()
        if registry is None:
            return None
        record = registry.archived_workspaces.get(name)
        if record is None:
            return None
        if not record.archive.is_file():
            try:
                await asyncio.to_thread(
                    self.require_workspace_manager().remove_archive_record,
                    name=name,
                )
            except (OSError, ValueError) as exc:
                self.context.app.notify(
                    str(exc), severity="error", markup=False
                )
                return None
            self.context.app.notify(
                f"Removed stale archive entry {name!r}; file was not found.",
                severity="warning",
            )
            return WorkspaceActionResult(use_fallback=True)
        return await self.open_workspace_archive_flow(
            record.archive,
            default_name=record.name,
            default_destination=record.source_root,
        )

    async def open_archive_workspace_flow(
        self,
    ) -> WorkspaceActionResult | None:
        """Prompt for archive options and compress the selected workspace."""
        if self.require_workspace_registry() is None:
            return None
        selection = self.context.selection
        if not isinstance(selection, LiveWorkspaceSelection):
            return None
        record = selection.record
        options = await self.context.app.push_screen_wait(
            ArchiveOptionsScreen(
                workspace_name=record.name,
                source_root=record.root,
                default_archive=workspace_archive_default_path(record.root),
            )
        )
        if options is None:
            return None
        try:
            archive_path = await self.run_archive_progress(
                name=record.name,
                archive_path=options.archive_path,
            )
        except (OSError, ValueError) as exc:
            self.context.app.notify(str(exc), severity="error", markup=False)
            return None
        self.context.app.notify(
            f"Archived workspace {record.name!r} to {path_markup(archive_path)}"
        )
        return WorkspaceActionResult(select_name=record.name)
