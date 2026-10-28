"""Textual editor generated config command handler."""

from __future__ import annotations

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.interfaces.cli.config_command._base import ConfigCommandBase
from apprc.user_files.app_home.locations import AppRCDirectoryError
from apprc.user_files.workspace_roots.model import WorkspaceRegistry
from apprc.user_files.workspace_roots.selector import WorkspaceSelectorIssue


class EditorConfigCommands(ConfigCommandBase):
    """Textual editor command implementation."""

    def edit(self, ctx: typer.Context) -> None:
        """Open the Textual editor for AppRC dotenv override files."""
        selector_context = self.cli_selector_context(ctx)
        current_state = self.resolved_config_state(ctx)
        workspace_registry: WorkspaceRegistry | None = None
        workspace_registry_error: str | None = None
        workspace_selector_issue: WorkspaceSelectorIssue | None = None
        active_workspace_root = None
        workspace_manager = None
        if self.apprc.schema.uses_workspaces():
            workspace_manager = self.workspace_manager(ctx)
            if self.apprc.schema.require_workspaces().registry:
                try:
                    workspace_registry = workspace_manager.registry()
                except (OSError, ValueError) as exc:
                    workspace_registry_error = str(exc)
            try:
                active_workspace_root = self.active_workspace_root_for_editor(
                    current_state,
                    selector_context=selector_context,
                )
            except (OSError, ValueError) as exc:
                workspace_selector_issue = WorkspaceSelectorIssue(
                    selector=None,
                    message=str(exc),
                    configured_workspace=(
                        workspace_registry.selected_workspace
                        if workspace_registry is not None
                        else None
                    ),
                )
        try:
            self.launch_config_editor(
                current_state=current_state,
                workspace_registry=workspace_registry,
                workspace_registry_error=workspace_registry_error,
                active_workspace_root=active_workspace_root,
                workspace_selector_issue=workspace_selector_issue,
                selector_context=selector_context,
                workspace_manager=workspace_manager,
            )
        except AppRCDirectoryError as exc:
            raise self.app_path_bad_parameter(exc) from exc
