"""Grouped high-level Typer integration for AppRC applications."""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.definition.maintenance import MaintenanceHandlers
from apprc.interfaces.cli.config_command.state import (
    ConfigRuntimePolicy,
    DefaultConfigCliState,
)
from apprc.interfaces.cli.context import CliRuntimeOptions
from apprc.interfaces.cli.options import (
    AppRootOption,
    EnvFileOverridesOption,
    EnvFilesOption,
    LayoutOption,
    LogLevelOption,
    SkipDotenvLayersOption,
    WorkspaceOption,
)
from apprc.interfaces.cli.runtime import (
    CliArgvProvider,
    CliRuntime,
    CliRuntimePolicy,
    MountCliRuntimeStateFactory,
)
from apprc.public.app_rc import AppRC
from apprc.runtime.logging import ResolutionLogger


def mount_app_cli(
    app: typer.Typer,
    apprc: AppRC,
    *,
    config_group_name: str = "config",
    state_type: type[Any] = DefaultConfigCliState,
    state_factory: MountCliRuntimeStateFactory[Any] | None = None,
    args_provider: CliArgvProvider | None = None,
    runtime_policy: ConfigRuntimePolicy | CliRuntimePolicy | None = None,
    workspace_required: bool = False,
    handlers: MaintenanceHandlers = MaintenanceHandlers(),
    maintenance_help_panel: str = "Maintenance",
    runtime_payload: Callable[[Any], Mapping[str, Any]] | None = None,
    active_workspace_root_with_context: Callable[..., Path | None]
    | None = None,
    initial_workspace_with_context: Callable[..., str | None] | None = None,
    editor_app_cls: type[Any] | None = None,
    help: str | None = None,
    setup_message: str | None = None,
    runtime_error_param_hint: str = "CONFIG",
    setup_logging: Callable[..., Any] | None = None,
    logger: ResolutionLogger | None = None,
) -> dict[str, typer.Typer]:
    """Mount AppRC runtime options and all declared fixed command groups.

    :param app: Host Typer application; it must not already have a callback.
    :param apprc: Application declaration whose enabled groups are mounted.
    :param config_group_name: Name of the optional generated config group.
    :param state_type: Type expected from the host runtime state factory.
    :param state_factory: Optional host state builder used after config resolution.
    :param args_provider: Optional argument provider for forwarded CLI execution.
    :param runtime_policy: Optional policy for skipping host business setup.
    :param workspace_required: Whether business commands require a workspace.
    :param handlers: Explicit application maintenance operations.
    :param maintenance_help_panel: Rich help panel for AppRC maintenance groups.
    :param runtime_payload: Optional serializer for config show.
    :param active_workspace_root_with_context: Optional workspace root resolver.
    :param initial_workspace_with_context: Optional initial workspace selector.
    :param editor_app_cls: Optional Textual config editor subclass.
    :param help: Optional generated config group help.
    :param setup_message: Optional setup text for unavailable runtime config.
    :param runtime_error_param_hint: Parameter hint for runtime payload errors.
    :param setup_logging: Optional application logging setup callable.
    :param logger: Optional application logger.
    :return: Mounted subgroups keyed by their public command names.
    """
    if not isinstance(app, typer.Typer):
        raise TypeError("mount_app_cli supports typer.Typer instances only.")
    if app.registered_callback is not None:
        raise RuntimeError(
            "mount_app_cli() cannot register AppRC runtime options because "
            "this Typer app already has a callback. Use CliRuntime with your "
            "callback and mount_app_groups(app, ...)."
        )
    if state_factory is None and state_type is not DefaultConfigCliState:
        raise TypeError("state_factory is required when state_type is custom.")
    runtime = CliRuntime(
        apprc,
        state_type=state_type,
        state_factory=(
            (lambda context, _options: state_factory(context))
            if state_factory is not None
            else None
        ),
        config_group_name=config_group_name,
        runtime_policy=runtime_policy,
        workspace_required=workspace_required,
        args_provider=args_provider,
        runtime_payload=runtime_payload,
        active_workspace_root_with_context=active_workspace_root_with_context,
        initial_workspace_with_context=initial_workspace_with_context,
        editor_app_cls=editor_app_cls,
        help=help,
        setup_message=setup_message,
        runtime_error_param_hint=runtime_error_param_hint,
        setup_logging=setup_logging,
        logger=logger,
    )
    _ensure_mount_names(app, apprc, config_group_name)

    @app.callback()
    def apprc_app_callback(
        ctx: typer.Context,
        env_files: EnvFilesOption = None,
        env_file_overrides_os_environ: EnvFileOverridesOption = False,
        skip_dotenv_layers: SkipDotenvLayersOption = False,
        workspace: WorkspaceOption = None,
        layout: LayoutOption = None,
        app_root: AppRootOption = None,
        log_level: LogLevelOption = None,
    ) -> None:
        """Capture AppRC bootstrap inputs before optional runtime setup."""
        try:
            options = CliRuntimeOptions.from_typer(
                env_files=env_files,
                env_file_overrides_os_environ=env_file_overrides_os_environ,
                load_dotenv_layers=not skip_dotenv_layers,
                workspace=workspace,
                layout=layout,
                app_root=app_root,
                log_level=log_level,
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        runtime.prepare(ctx, options)

    return runtime.mount_app_groups(
        app,
        handlers=handlers,
        maintenance_help_panel=maintenance_help_panel,
    )


def _ensure_mount_names(
    app: typer.Typer, apprc: AppRC, config_group_name: str
) -> None:
    """Reject fixed command collisions before callbacks or groups are added."""
    reserved = {"paths", "doctor", "purge"}
    reserved.update(
        kind
        for kind in ("appdata", "cache", "state")
        if getattr(apprc.schema.paths, kind)
    )
    if apprc.schema.workspaces is not None:
        reserved.add("workspace")
    if (
        apprc.schema.paths.config
        or apprc.schema.owners
        or apprc.schema.user_dotenv
    ):
        reserved.add(config_group_name)
    existing = {group.name for group in app.registered_groups if group.name}
    for command in app.registered_commands:
        if command.name:
            existing.add(command.name)
        elif command.callback is not None:
            existing.add(typer.main.get_command_name(command.callback.__name__))
    collisions = reserved & existing
    if collisions:
        raise RuntimeError(
            "AppRC cannot mount because these command names are already in use: "
            + ", ".join(sorted(collisions))
        )
