"""Workspace and user-dotenv setup workflow embedded in the config editor."""

from __future__ import annotations

# == Standard Library ========================
import asyncio

# == Internal ================================
from apprc.interfaces.tui._primitives import ConfirmScreen, PathInputScreen
from apprc.interfaces.tui._styles import lines_text, path_text
from apprc.interfaces.tui.editor.workspace_base import (
    WorkspaceActionContext,
    WorkspaceActionResult,
)
from apprc.interfaces.tui.editor.workspace_registration import (
    WorkspaceRegistrationWorkflows,
)


class ConfigEditorSetupWorkflow:
    """Initialize enabled user and workspace files without changing process state."""

    def __init__(self, context: WorkspaceActionContext) -> None:
        """Store the fresh service and selection inputs for one action."""
        self.context = context

    async def open_setup_flow(self) -> WorkspaceActionResult | None:
        """Initialize a direct workspace, register one, or create user settings."""
        context = self.context
        action_result = WorkspaceActionResult()
        if context.workspace_enabled:
            root = context.active_workspace_root
            if root is None:
                result = await context.app.push_screen_wait(
                    PathInputScreen(
                        title="Initialize workspace",
                        message="Choose an explicit workspace directory.",
                        placeholder="Workspace directory",
                    )
                )
                if result is None:
                    return None
                root = result.path
            manager = context.workspace_manager
            if manager is None:
                context.app.notify(
                    "Workspace setup requires a WorkspaceManager.",
                    severity="error",
                    markup=False,
                )
                return None
            try:
                if context.registry_enabled:
                    registration = WorkspaceRegistrationWorkflows(context)
                    registration_result = (
                        await registration.register_workspace_directory_flow(
                            root,
                            default_name=registration.suggest_workspace_name(
                                root
                            ),
                        )
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
                context.app.notify(str(exc), severity="error", markup=False)
                return action_result
        if context.user_dotenv_enabled and not context.user_dotenv_active:
            try:
                await asyncio.to_thread(context.manager.setup)
            except (OSError, ValueError) as exc:
                context.app.notify(str(exc), severity="error", markup=False)
                return action_result
        await context.app.push_screen_wait(
            ConfirmScreen(
                title="Setup complete",
                message=lines_text(
                    "AppRC initialized the declared setup files.",
                    path_text(context.manager.paths.config_dir)
                    if context.manager.paths.config_dir is not None
                    else "",
                ),
                actions=(("done", "Done", "primary"),),
                cancel_label=None,
            )
        )
        return action_result
