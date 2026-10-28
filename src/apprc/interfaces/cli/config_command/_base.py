"""Shared base class for generated config command handlers."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path
from typing import Any

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.definition.resolution import ResolveOptions
from apprc.interfaces.cli._errors import app_path_bad_parameter
from apprc.interfaces.cli.config_command._editor_launcher import (
    ConfigEditorLauncher,
)
from apprc.interfaces.cli.config_command._runtime_payload import (
    default_runtime_payload,
)
from apprc.interfaces.cli.config_command._selector_context import (
    ConfigSelectorContext,
    ConfigStateResolver,
    ResolvedConfigState,
    SelectorContextReader,
    _empty_selector_context,
)
from apprc.interfaces.cli.config_command.group_options import ConfigGroupOptions
from apprc.interfaces.cli.config_command.state import DefaultConfigCliState
from apprc.public.app_rc import AppRC
from apprc.runtime.resolution import ResolvedConfig
from apprc.services.manager import ConfigManager
from apprc.services.workspaces import WorkspaceManager
from apprc.user_files.app_home.locations import AppRCDirectoryError
from apprc.user_files.workspace_roots.model import WorkspaceRegistry
from apprc.user_files.workspace_roots.selector import WorkspaceSelectorIssue


class ConfigCommandBase:
    """Shared dependencies and adapters for generated config commands."""

    def __init__(
        self,
        apprc: AppRC,
        *,
        options: ConfigGroupOptions,
        missing_setup: str,
    ) -> None:
        """Store config command dependencies and extension hooks.

        :param apprc: Application config facade.
        :param options: Generated config command hook bundle.
        :param missing_setup: Message shown when config setup is absent.
        """
        self.apprc = apprc
        self.state_type = options.state_type
        self.runtime_payload = options.runtime_payload
        self.active_workspace_root_with_context_hook = (
            options.active_workspace_root_with_context
        )
        self.missing_setup = missing_setup
        self.runtime_error_param_hint = options.runtime_error_param_hint
        self.config_group_name = options.config_group_name
        self.state_resolver = ConfigStateResolver(options.state_type)
        self.selector_context_reader = SelectorContextReader()
        self.editor_launcher = ConfigEditorLauncher(
            apprc=apprc,
            editor_app_cls=options.editor_app_cls,
            config_group_name=options.config_group_name,
            initial_workspace_with_context_hook=(
                options.initial_workspace_with_context
            ),
        )

    def state(self, ctx: typer.Context) -> Any:
        """Return the application CLI state stored by the parent CLI."""
        return self.state_resolver.state(ctx)

    def manager(self, ctx: typer.Context) -> ConfigManager:
        """Capture selection and source inputs from the active CLI invocation.

        :param ctx: Generated command context.
        :return: Manager using this invocation's workspace and path snapshot.
        """
        source = self.cli_selector_context(ctx)
        workspace = self.cli_context_param(ctx, "workspace")
        runtime_context = self.selector_context_reader.runtime_context(ctx)
        runtime_options = (
            runtime_context.runtime_options
            if runtime_context is not None
            else None
        )
        options = ResolveOptions(
            workspace=workspace if isinstance(workspace, str) else None,
            workspace_required=(
                runtime_context.workspace_required
                if runtime_context is not None
                else False
            ),
            env_files=source.env_files,
            env_file_overrides_os_environ=source.env_file_overrides_os_environ,
            load_dotenv_layers=source.load_dotenv_layers,
            layout=runtime_options.layout
            if runtime_options is not None
            else None,
        )
        if source.paths is None:
            return self.apprc.manage(options, environment=source.environment)
        return self.apprc._manage_with_paths(
            options, source.environment, source.paths
        )

    def workspace_manager(self, ctx: typer.Context) -> WorkspaceManager:
        """Return workspace operations bound to the CLI's captured inputs."""
        manager = self.manager(ctx)
        return self.apprc.workspaces(
            manager.options,
            environment=manager.environment,
        )

    def context_state(self, ctx: typer.Context) -> DefaultConfigCliState | None:
        """Return AppRC context as generic config state when available."""
        return self.state_resolver.context_state(ctx)

    def resolved_config_state(
        self,
        ctx: typer.Context,
    ) -> ResolvedConfigState | None:
        """Return state plus whether app-owned hooks may inspect it."""
        return self.state_resolver.resolved_config_state(ctx)

    def runtime_payload_state(
        self,
        resolved_state: ResolvedConfigState | None,
    ) -> Any | None:
        """Return state that is valid for app-owned runtime payload hooks."""
        return self.state_resolver.runtime_payload_state(resolved_state)

    def config_command_text(self, action: str) -> str:
        """Return one CLI command line for generated CLI guidance."""
        return (
            f"{self.apprc.schema.config_command_name()} "
            f"{self.config_group_name} {action}"
        )

    def cli_context_param(
        self,
        ctx: typer.Context,
        name: str,
    ) -> object | None:
        """Read one option value from the parent command context."""
        return self.selector_context_reader.cli_context_param(ctx, name)

    def cli_selector_context(self, ctx: typer.Context) -> ConfigSelectorContext:
        """Return explicit env-file values and captured environment."""
        return self.selector_context_reader.cli_selector_context(ctx)

    def app_path_bad_parameter(
        self,
        exc: AppRCDirectoryError | OSError,
    ) -> typer.BadParameter:
        """Adapt a managed AppRC path failure to Typer's error type."""
        return app_path_bad_parameter(exc)

    def require_workspace_support(self) -> None:
        """Raise a CLI error when workspace selection is not declared."""
        if not self.apprc.schema.uses_workspaces():
            raise typer.BadParameter(
                f"{self.apprc.schema.display_name} does not use AppRC workspaces.",
                param_hint="workspace",
            )

    def require_workspace_registry_support(self) -> None:
        """Raise a CLI error when the declaration does not enable a registry."""
        self.require_workspace_support()
        if not self.apprc.schema.require_workspaces().registry:
            raise typer.BadParameter(
                f"{self.apprc.schema.display_name} uses direct workspace paths, "
                "not a registry.",
                param_hint="workspace",
            )

    def active_workspace_root_for_cli(
        self,
        resolved_state: ResolvedConfigState | None,
        *,
        selector_context: ConfigSelectorContext | None = None,
    ) -> Path | None:
        """Return the selected workspace root from the current resolution."""
        if resolved_state is None:
            return None
        if (
            resolved_state.app_owned
            and self.active_workspace_root_with_context_hook is not None
        ):
            context = selector_context or _empty_selector_context()
            return self.active_workspace_root_with_context_hook(
                resolved_state.state, context
            )
        state = resolved_state.state
        resolved = getattr(state, "resolved", None)
        if resolved is not None and resolved.workspace is not None:
            return resolved.workspace.root
        return None

    def active_workspace_root_for_editor(
        self,
        current_state: ResolvedConfigState | None,
        *,
        selector_context: ConfigSelectorContext | None = None,
    ) -> Path | None:
        """Return the workspace root selected for zero-write editor reads."""
        if not self.apprc.schema.uses_workspaces():
            return None
        resolved = (
            current_state.state.resolved if current_state is not None else None
        )
        if resolved is None:
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
            manager = (
                self.apprc.manage(options, environment=context.environment)
                if context.paths is None
                else self.apprc._manage_with_paths(
                    options, context.environment, context.paths
                )
            )
            resolved = manager.resolve()
        return (
            resolved.workspace.root if resolved.workspace is not None else None
        )

    def cli_selector_context_empty(self) -> ConfigSelectorContext:
        """Return an empty selector context for non-Typer callers."""
        return _empty_selector_context()

    def default_runtime_payload(
        self,
        *,
        workspace_root: Path | None,
        resolved: ResolvedConfig,
    ) -> dict[str, Any]:
        """Return generic ``config show`` data when the app provides none."""
        return default_runtime_payload(
            self.apprc, workspace_root=workspace_root, resolved=resolved
        )

    def launch_config_editor(
        self,
        *,
        current_state: ResolvedConfigState | None,
        workspace_registry: WorkspaceRegistry | None,
        workspace_registry_error: str | None,
        active_workspace_root: Path | None,
        workspace_selector_issue: WorkspaceSelectorIssue | None = None,
        selector_context: ConfigSelectorContext | None = None,
        workspace_manager: WorkspaceManager | None = None,
    ) -> None:
        """Create and run the Textual config editor."""
        self.editor_launcher.launch(
            current_state=current_state,
            workspace_registry=workspace_registry,
            workspace_registry_error=workspace_registry_error,
            active_workspace_root=active_workspace_root,
            workspace_selector_issue=workspace_selector_issue,
            selector_context=selector_context,
            workspace_manager=workspace_manager,
        )

    def initial_workspace_for_editor(
        self,
        resolved_state: ResolvedConfigState,
        *,
        workspace_registry: WorkspaceRegistry | None,
        selector_context: ConfigSelectorContext | None = None,
    ) -> str | None:
        """Return the workspace name the editor should select on startup."""
        return self.editor_launcher.initial_workspace(
            resolved_state,
            workspace_registry=workspace_registry,
            selector_context=selector_context,
        )
