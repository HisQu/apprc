"""Workspace and user-dotenv setup workflow embedded in the config editor."""

from __future__ import annotations

# == Standard Library ========================
import asyncio
from typing import TYPE_CHECKING

# == Internal ================================
from apprc.interfaces.tui._primitives import ConfirmScreen, PathInputScreen
from apprc.interfaces.tui._styles import lines_text, path_text
from apprc.interfaces.tui.editor.workspace_base import WorkspaceActionResult
from apprc.interfaces.tui.editor.workspace_registration import (
    WorkspaceRegistrationWorkflows,
)

if TYPE_CHECKING:
    from apprc.interfaces.tui.editor.app import ConfigEditorScreen


class ConfigEditorSetupWorkflow:
    """Initialize enabled user and workspace files without changing process state."""

    def __init__(self, editor: ConfigEditorScreen) -> None:
        """Store the screen that owns setup controls."""
        self.editor = editor

    async def open_setup_flow(self) -> WorkspaceActionResult | None:
        """Initialize a direct workspace, register one, or create user settings."""
        editor = self.editor
        action_result = WorkspaceActionResult()
        if editor.workspace_enabled:
            root = editor.active_workspace_root
            if root is None:
                result = await editor.app.push_screen_wait(
                    PathInputScreen(
                        title="Initialize workspace",
                        message="Choose an explicit workspace directory.",
                        placeholder="Workspace directory",
                    )
                )
                if result is None:
                    return None
                root = result.path
            manager = editor.workspace_manager
            if manager is None:
                editor.notify(
                    "Workspace setup requires a WorkspaceManager.",
                    severity="error",
                    markup=False,
                )
                return None
            try:
                if editor.registry_enabled:
                    registration_result = await WorkspaceRegistrationWorkflows(
                        editor
                    ).register_workspace_directory_flow(
                        root,
                        default_name=editor._suggest_workspace_name(root),
                    )
                    if registration_result is None:
                        return None
                    action_result = registration_result
                else:
                    initialized = await asyncio.to_thread(
                        manager.initialize_workspace, root
                    )
                    action_result = WorkspaceActionResult(
                        active_root=initialized
                    )
            except (OSError, TypeError, ValueError) as exc:
                editor.notify(str(exc), severity="error", markup=False)
                return action_result
        if editor.user_dotenv_enabled and not editor.user_dotenv_active:
            try:
                await asyncio.to_thread(editor.manager.setup)
            except (OSError, ValueError) as exc:
                editor.notify(str(exc), severity="error", markup=False)
                return action_result
        await editor.app.push_screen_wait(
            ConfirmScreen(
                title="Setup complete",
                message=lines_text(
                    "AppRC initialized the declared setup files.",
                    path_text(editor.paths.config_dir)
                    if editor.paths.config_dir is not None
                    else "",
                ),
                actions=(("done", "Done", "primary"),),
                cancel_label=None,
            )
        )
        return action_result
