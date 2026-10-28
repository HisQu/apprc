"""Workspace rename, repoint, and move workflows for the config editor TUI."""

from __future__ import annotations

# == Standard Library ===========================================
import asyncio
from pathlib import Path

# == 3rd Party ==================================================
from rich.text import Text

# == Internal ===================================================
from apprc.interfaces.tui._primitives import (
    ConfirmScreen,
    PathInputScreen,
    WorkspaceNameScreen,
)
from apprc.interfaces.tui._styles import (
    label_value_text,
    lines_text,
    path_text,
    workspace_name_text,
)
from apprc.interfaces.tui.editor.workspace_base import WorkspaceWorkflowBase
from apprc.interfaces.tui.workspaces.selection import (
    LiveWorkspaceSelection,
    MissingWorkspaceSelection,
)
from apprc.user_files.workspace_roots.model import WorkspaceRecord
from apprc.user_files.workspace_roots.paths import (
    normalize_workspace_root_path,
    resolve_workspace_root_path,
)


class WorkspaceEditingWorkflows(WorkspaceWorkflowBase):
    """Edit workspace metadata and relocate live workspace directories."""

    async def open_rename_workspace_flow(self) -> None:
        """Prompt for a new selector and confirm its external migration.

        Renaming changes only registry metadata. Callers that select the
        workspace through ``--workspace`` or an environment variable continue
        to use the old selector until they are updated separately.
        """
        registry = self.editor._require_workspace_registry()
        record = self._selected_editable_workspace()
        if registry is None or record is None:
            return
        result = await self.editor.push_screen_wait(
            WorkspaceNameScreen(
                default_name=record.name,
                message="Choose the workspace name used by --workspace.",
            )
        )
        if result is None:
            return
        name = result.name
        if name == record.name:
            return
        if name in registry.workspaces or name in registry.archived_workspaces:
            self.editor.notify(
                f"Workspace name {name!r} is already in use.",
                severity="error",
                markup=False,
            )
            return
        action = await self.editor.push_screen_wait(
            ConfirmScreen(
                title="Rename workspace",
                message=lines_text(
                    Text.assemble(
                        "Rename ",
                        workspace_name_text(repr(record.name)),
                        " to ",
                        workspace_name_text(repr(name)),
                        "?",
                    ),
                    "",
                    "This changes only the workspace registry entry.",
                    Text.assemble(
                        "Update external --workspace arguments and "
                        "environment values that use ",
                        workspace_name_text(repr(record.name)),
                        ".",
                    ),
                ),
                actions=(("rename", "Rename", "warning"),),
            )
        )
        if action != "rename":
            return
        try:
            self.editor.workspace_registry = await asyncio.to_thread(
                self.require_workspace_manager().rename_workspace,
                old=record.name,
                new=name,
            )
        except (OSError, TypeError, ValueError) as exc:
            self.editor.notify(str(exc), severity="error", markup=False)
            return
        await self.editor._refresh_workspace_list(select_name=name)
        self.editor.notify(f"Renamed workspace {record.name!r} to {name!r}")

    async def open_workspace_reconnect_flow(self) -> None:
        """Connect a named workspace to its existing directory."""
        registry = self.editor._require_workspace_registry()
        record = self._selected_editable_workspace()
        if registry is None or record is None:
            return
        result = await self.editor.push_screen_wait(
            PathInputScreen(
                title="Reconnect workspace",
                message=(
                    "Enter the existing directory for this workspace. AppRC "
                    "will update only the registry entry; it will not create, "
                    "move, or delete files."
                ),
                placeholder="Existing workspace directory",
                value=str(record.root),
            )
        )
        if result is None:
            return
        root = self._existing_workspace_directory(result.path)
        if root is None or root == record.root:
            return
        action = await self.editor.push_screen_wait(
            ConfirmScreen(
                title="Reconnect workspace",
                message=lines_text(
                    label_value_text(
                        "Workspace",
                        workspace_name_text(record.name),
                    ),
                    label_value_text("Registered path", path_text(record.root)),
                    label_value_text("Existing directory", path_text(root)),
                    "",
                    "This changes only the workspace registry entry.",
                    "It does not create, move, or delete files.",
                    "External --workspace arguments and environment values "
                    "that use the current name are not changed.",
                ),
                actions=(("update", "Reconnect", "warning"),),
            )
        )
        if action != "update":
            return
        try:
            self.editor.workspace_registry = await asyncio.to_thread(
                self.require_workspace_manager().repoint_workspace,
                name=record.name,
                root=root,
            )
        except (OSError, TypeError, ValueError) as exc:
            self.editor.notify(str(exc), severity="error", markup=False)
            return
        await self.editor._refresh_workspace_list(select_name=record.name)
        self.editor.notify(f"Reconnected workspace {record.name!r}")

    async def open_move_workspace_flow(self) -> None:
        """Move the selected workspace through the transactional service."""
        registry = self.editor._require_workspace_registry()
        selection = self.editor.selection
        if registry is None or not isinstance(
            selection, LiveWorkspaceSelection
        ):
            return
        record = selection.record
        result = await self.editor.push_screen_wait(
            PathInputScreen(
                title="Move workspace",
                message=(
                    "Enter a new or empty destination directory for the "
                    "complete workspace. Existing files are never merged or "
                    "replaced."
                ),
                placeholder="New or empty workspace directory",
            )
        )
        if result is None:
            return
        try:
            destination = resolve_workspace_root_path(
                result.path,
                base=registry.path.parent,
            )
        except (OSError, ValueError) as exc:
            self.editor.notify(str(exc), severity="error", markup=False)
            return
        action = await self.editor.push_screen_wait(
            ConfirmScreen(
                title="Move workspace",
                message=lines_text(
                    label_value_text(
                        "Workspace", workspace_name_text(record.name)
                    ),
                    label_value_text("Source", path_text(record.root)),
                    label_value_text("Destination", path_text(destination)),
                    "",
                    "The complete workspace directory will be moved and its "
                    "registry root will be updated.",
                ),
                actions=(("move", "Move", "warning"),),
            )
        )
        if action != "move":
            return
        try:
            move_result = await asyncio.to_thread(
                self.require_workspace_manager().move_workspace,
                name=record.name,
                root=destination,
            )
        except (OSError, ValueError) as exc:
            self.editor.notify(str(exc), severity="error", markup=False)
            return
        self.editor.workspace_registry = (
            self.require_workspace_manager().registry()
        )
        await self.editor._refresh_workspace_list(select_name=record.name)
        for warning in move_result.warnings:
            self.editor.notify(warning, severity="warning", markup=False)
        self.editor.notify(f"Moved workspace {record.name!r}")

    def _selected_editable_workspace(self) -> WorkspaceRecord | None:
        """Return the selected live or missing workspace record."""
        selection = self.editor.selection
        if isinstance(
            selection,
            LiveWorkspaceSelection | MissingWorkspaceSelection,
        ):
            return selection.record
        return None

    def _existing_workspace_directory(self, candidate: Path) -> Path | None:
        """Validate a directory for a registry-only location update.

        :param candidate: Path entered through the location modal.
        :return: Absolute directory, or ``None`` after reporting a failure.
        """
        try:
            root = normalize_workspace_root_path(candidate).resolve()
        except (OSError, ValueError) as exc:
            self.editor.notify(str(exc), severity="error", markup=False)
            return None
        if not root.exists():
            self.editor.notify(
                f"Workspace location does not exist: {root}",
                severity="error",
                markup=False,
            )
            return None
        if not root.is_dir():
            self.editor.notify(
                f"Workspace location is not a directory: {root}",
                severity="error",
                markup=False,
            )
            return None
        return root
