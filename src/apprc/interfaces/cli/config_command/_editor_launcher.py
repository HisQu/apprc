"""Config editor launch helpers for generated config commands."""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.definition.resolution import ResolveOptions
from apprc.interfaces.cli.config_command._selector_context import (
    ConfigSelectorContext,
    ResolvedConfigState,
    _empty_selector_context,
)
from apprc.interfaces.cli.config_command.state import (
    DefaultConfigCliState,
    initial_workspace_from_state,
)
from apprc.public.app_rc import AppRC
from apprc.services.manager import ConfigManager
from apprc.services.workspaces import WorkspaceManager
from apprc.user_files.workspace_roots.model import WorkspaceRegistry
from apprc.user_files.workspace_roots.selector import WorkspaceSelectorIssue

if TYPE_CHECKING:
    from apprc.interfaces.tui import ConfigEditorApp

MISSING_TUI_EXTRA_MESSAGE = (
    "The Textual editor requires the terminal distribution. "
    "Install it with: python -m pip install apprc"
)


@dataclass(slots=True)
class ConfigEditorLauncher:
    """Resolve editor startup state and launch the Textual editor."""

    apprc: AppRC
    editor_app_cls: type["ConfigEditorApp"] | None
    config_group_name: str
    initial_workspace_with_context_hook: (
        Callable[[Any, ConfigSelectorContext], str | None] | None
    )

    def launch(
        self,
        *,
        current_state: ResolvedConfigState | None,
        workspace_registry: WorkspaceRegistry | None,
        workspace_registry_error: str | None = None,
        active_workspace_root: Path | None,
        workspace_selector_issue: WorkspaceSelectorIssue | None = None,
        selector_context: ConfigSelectorContext | None = None,
        workspace_manager: WorkspaceManager | None = None,
    ) -> None:
        """Create and run the Textual config editor."""
        context = selector_context or _empty_selector_context()
        options = ResolveOptions(
            workspace=context.workspace,
            env_files=context.env_files,
            env_file_overrides_os_environ=(
                context.env_file_overrides_os_environ
            ),
            load_dotenv_layers=context.load_dotenv_layers,
            layout=context.layout,
        )
        paths = context.paths or self.apprc.paths(
            options, environment=context.environment
        )
        manager = self.apprc._manage_with_paths(
            options, context.environment, paths
        )
        selected_workspace = self.initial_workspace(
            current_state,
            workspace_registry=workspace_registry,
            selector_context=context,
            manager=manager,
        )
        if self.apprc.schema.uses_workspaces() and workspace_manager is None:
            workspace_manager = self.apprc.workspaces(
                manager.options, environment=manager.environment
            )
        editor_app_cls = self.editor_app_cls
        if editor_app_cls is None:
            try:
                from apprc.interfaces.tui import ConfigEditorApp
            except ModuleNotFoundError as exc:
                if _module_not_found_is_textual(exc):
                    raise typer.BadParameter(MISSING_TUI_EXTRA_MESSAGE) from exc
                raise
            editor_app_cls = ConfigEditorApp
        editor_app = editor_app_cls(
            manager=manager,
            apprc=self.apprc,
            workspace_manager=workspace_manager,
            workspace_registry_error=workspace_registry_error,
            initial_workspace=selected_workspace,
            active_workspace_root=active_workspace_root,
            workspace_selector_issue=workspace_selector_issue,
            config_group_name=self.config_group_name,
        )
        editor_app.run()

    def initial_workspace(
        self,
        resolved_state: ResolvedConfigState | None,
        *,
        workspace_registry: WorkspaceRegistry | None,
        selector_context: ConfigSelectorContext | None = None,
        manager: ConfigManager | None = None,
    ) -> str | None:
        """Return the workspace name the editor should select on startup."""
        context = selector_context or _empty_selector_context()
        if not self.apprc.schema.uses_workspaces():
            return None
        if (
            resolved_state is not None
            and resolved_state.app_owned
            and self.initial_workspace_with_context_hook is not None
        ):
            return self.initial_workspace_with_context_hook(
                resolved_state.state, context
            )
        if resolved_state is not None:
            state = resolved_state.state
            if not isinstance(state, DefaultConfigCliState):
                state = DefaultConfigCliState(
                    resolved=getattr(state, "resolved", None),
                    workspace=context.workspace,
                )
            if state.resolved is not None:
                return initial_workspace_from_state(
                    self.apprc,
                    state,
                    explicit_values=context.explicit_values,
                    env_file_overrides_os_environ=(
                        context.env_file_overrides_os_environ
                    ),
                )
        resolved = (manager or self.apprc.manage()).resolve()
        return (
            resolved.workspace.workspace_name
            if resolved.workspace is not None
            else (
                workspace_registry.selected_workspace
                if workspace_registry is not None
                else None
            )
        )


def _module_not_found_is_textual(exc: ModuleNotFoundError) -> bool:
    """Return whether an import failure came from the optional TUI stack."""
    missing_name = exc.name
    return missing_name == "textual" or (
        missing_name is not None and missing_name.startswith("textual.")
    )
