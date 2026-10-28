"""Workspace and user-dotenv setup workflow embedded in the config editor."""

from __future__ import annotations

# == Standard Library ========================
import asyncio
from typing import TYPE_CHECKING

# == Internal ================================
from apprc.interfaces.tui._primitives import ConfirmScreen, PathInputScreen
from apprc.interfaces.tui._styles import lines_text, path_text
from apprc.interfaces.tui.editor.workspace_registration import (
    WorkspaceRegistrationWorkflows,
)

if TYPE_CHECKING:
    from apprc.interfaces.tui.editor.app import ConfigEditorApp


class ConfigEditorSetupWorkflow:
    """Initialize enabled user and workspace files without changing process state."""

    def __init__(self, editor: ConfigEditorApp) -> None:
        """Store the editor that owns setup controls."""
        self.editor = editor

    async def open_setup_flow(self) -> None:
        """Initialize a direct workspace, register one, or create user settings."""
        editor = self.editor
        if editor.workspace_enabled:
            root = editor.active_workspace_root
            if root is None:
                result = await editor.push_screen_wait(
                    PathInputScreen(
                        title="Initialize workspace",
                        message="Choose an explicit workspace directory.",
                        placeholder="Workspace directory",
                    )
                )
                if result is None:
                    return
                root = result.path
            manager = editor.workspace_manager
            if manager is None:
                editor.notify(
                    "Workspace setup requires a WorkspaceManager.",
                    severity="error",
                    markup=False,
                )
                return
            try:
                if editor.registry_enabled:
                    await WorkspaceRegistrationWorkflows(
                        editor
                    ).register_workspace_directory_flow(
                        root,
                        default_name=editor._suggest_workspace_name(root),
                    )
                else:
                    initialized = await asyncio.to_thread(
                        manager.initialize_workspace, root
                    )
                    editor.active_workspace_root = initialized
                    await editor._refresh_workspace_list()
            except (OSError, TypeError, ValueError) as exc:
                editor.notify(str(exc), severity="error", markup=False)
                return
        if editor.user_dotenv_enabled and not editor.user_dotenv_active:
            try:
                await asyncio.to_thread(editor.manager.setup)
            except (OSError, ValueError) as exc:
                editor.notify(str(exc), severity="error", markup=False)
                return
            editor.user_dotenv_active = editor._user_dotenv_is_active()
            await editor._refresh_workspace_list()
        await editor.clear_setup_status()
        await editor.push_screen_wait(
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
