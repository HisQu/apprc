"""Workspace removal workflows for the config editor TUI."""

from __future__ import annotations

# == Standard Library ========================
import asyncio

# == Internal ================================
from apprc.interfaces.tui._primitives import ConfirmScreen
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


class WorkspaceRemovalWorkflows(WorkspaceWorkflowBase):
    """Unregister live or missing workspace entries from the editor."""

    async def open_delete_workspace_flow(self) -> None:
        """Confirm removal of the named workspace entry."""
        selection = self.editor.selection
        if not isinstance(
            selection,
            LiveWorkspaceSelection | MissingWorkspaceSelection,
        ):
            return
        record = selection.record
        message = lines_text(
            label_value_text("Workspace", workspace_name_text(record.name)),
            label_value_text("Root", path_text(record.root)),
            "",
            "The named workspace entry will be removed. Its directory and "
            "files will remain untouched.",
        )
        action = await self.editor.app.push_screen_wait(
            ConfirmScreen(
                title="Remove workspace",
                message=message,
                actions=(("remove", "Remove", "warning"),),
            )
        )
        if action == "remove":
            await self.remove_live_workspace(record.name)

    async def remove_live_workspace(self, name: str) -> bool:
        """Remove one live named-workspace registry row.

        :param name: Workspace selector to remove.
        :return: Whether the removal completed.
        """
        registry = self.editor._require_workspace_registry()
        if registry is None:
            return False
        try:
            registry.selected(name)
        except ValueError as exc:
            self.editor.notify(str(exc), severity="error", markup=False)
            return False
        try:
            self.editor.workspace_registry = await asyncio.to_thread(
                self.require_workspace_manager().remove_workspace,
                name=name,
            )
        except (OSError, ValueError) as exc:
            self.editor.workspace_registry = (
                self.require_workspace_manager().registry()
            )
            await self.editor._refresh_workspace_list()
            self.editor.notify(str(exc), severity="error", markup=False)
            return False
        await self.editor._refresh_workspace_list(
            select_name=self.editor._registered_active_workspace_name()
        )
        self.editor.notify(f"Removed workspace {name!r}")
        return True
