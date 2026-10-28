"""Shared base for config editor workspace workflows."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apprc.interfaces.tui import ConfigEditorApp
    from apprc.services.workspaces import WorkspaceManager


class WorkspaceWorkflowBase:
    """Store the editor and its workspace manager for TUI workflows.

    :param editor: Mounted config editor app.
    """

    def __init__(self, editor: "ConfigEditorApp") -> None:
        """Capture the editor's explicitly configured workspace manager."""
        self.editor = editor

    def require_workspace_manager(self) -> WorkspaceManager:
        """Return workspace services or reject unavailable workspace controls.

        :return: The editor's explicitly configured workspace manager.
        :raises ValueError: If this editor has no workspace capability.
        """
        manager = self.editor.workspace_manager
        if manager is None:
            raise ValueError("Workspace controls require a WorkspaceManager.")
        return manager
