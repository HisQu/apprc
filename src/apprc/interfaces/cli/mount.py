"""High-level Typer integration helpers for AppRC config commands."""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar, overload

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.interfaces.cli.bridge import (
    CliArgvProvider,
    ConfigCliBridge,
    HostCliBootstrapPolicy,
    MountConfigCliStateFactory,
    ensure_config_group_name_available,
)
from apprc.interfaces.cli.config_command.state import (
    ConfigBootstrapPolicy,
    DefaultConfigCliState,
)
from apprc.interfaces.cli.context import (
    CliBootstrapContext,
    CliBootstrapOptions,
)
from apprc.interfaces.cli.options import (
    EnvFileOverridesOption,
    EnvFilesOption,
    LogLevelOption,
    SkipDotenvLayersOption,
    StorageOption,
)
from apprc.runtime.result import BootstrapLogger
from apprc.definition.app_config.kit import AppConfigKit

if TYPE_CHECKING:
    from apprc.interfaces.cli.config_command import ConfigSelectorContext
    from apprc.interfaces.tui import ConfigEditorApp

StateT = TypeVar("StateT")


@overload
def mount_config_cli(
    app: typer.Typer,
    kit: AppConfigKit,
    *,
    config_group_name: str = "config",
    state_type: type[DefaultConfigCliState] = DefaultConfigCliState,
    state_factory: MountConfigCliStateFactory[DefaultConfigCliState]
    | None = None,
    args_provider: CliArgvProvider | None = None,
    bootstrap_policy: ConfigBootstrapPolicy | HostCliBootstrapPolicy | None = (
        None
    ),
    runtime_payload: (
        Callable[[DefaultConfigCliState], Mapping[str, Any]] | None
    ) = None,
    active_storage_root: (
        Callable[[DefaultConfigCliState], Path | None] | None
    ) = None,
    active_storage_root_with_context: (
        Callable[
            [DefaultConfigCliState, "ConfigSelectorContext"],
            Path | None,
        ]
        | None
    ) = None,
    initial_storage: Callable[[DefaultConfigCliState], str | None]
    | None = None,
    initial_storage_with_context: (
        Callable[[DefaultConfigCliState, "ConfigSelectorContext"], str | None]
        | None
    ) = None,
    editor_app_cls: type["ConfigEditorApp"] | None = None,
    help: str | None = None,
    setup_message: str | None = None,
    runtime_error_param_hint: str = "CONFIG",
    setup_logging: Callable[..., Any] | None = None,
    logger: BootstrapLogger | None = None,
) -> typer.Typer: ...


@overload
def mount_config_cli(
    app: typer.Typer,
    kit: AppConfigKit,
    *,
    config_group_name: str = "config",
    state_type: type[StateT],
    state_factory: MountConfigCliStateFactory[StateT],
    args_provider: CliArgvProvider | None = None,
    bootstrap_policy: ConfigBootstrapPolicy | HostCliBootstrapPolicy | None = (
        None
    ),
    runtime_payload: Callable[[StateT], Mapping[str, Any]] | None = None,
    active_storage_root: Callable[[StateT], Path | None] | None = None,
    active_storage_root_with_context: (
        Callable[[StateT, "ConfigSelectorContext"], Path | None] | None
    ) = None,
    initial_storage: Callable[[StateT], str | None] | None = None,
    initial_storage_with_context: (
        Callable[[StateT, "ConfigSelectorContext"], str | None] | None
    ) = None,
    editor_app_cls: type["ConfigEditorApp"] | None = None,
    help: str | None = None,
    setup_message: str | None = None,
    runtime_error_param_hint: str = "CONFIG",
    setup_logging: Callable[..., Any] | None = None,
    logger: BootstrapLogger | None = None,
) -> typer.Typer: ...


def mount_config_cli(
    app: typer.Typer,
    kit: AppConfigKit,
    *,
    config_group_name: str = "config",
    state_type: type[Any] = DefaultConfigCliState,
    state_factory: MountConfigCliStateFactory[Any] | None = None,
    args_provider: CliArgvProvider | None = None,
    bootstrap_policy: ConfigBootstrapPolicy | HostCliBootstrapPolicy | None = (
        None
    ),
    runtime_payload: Callable[[Any], Mapping[str, Any]] | None = None,
    active_storage_root: Callable[[Any], Path | None] | None = None,
    active_storage_root_with_context: (
        Callable[[Any, "ConfigSelectorContext"], Path | None] | None
    ) = None,
    initial_storage: Callable[[Any], str | None] | None = None,
    initial_storage_with_context: (
        Callable[[Any, "ConfigSelectorContext"], str | None] | None
    ) = None,
    editor_app_cls: type["ConfigEditorApp"] | None = None,
    help: str | None = None,
    setup_message: str | None = None,
    runtime_error_param_hint: str = "CONFIG",
    setup_logging: Callable[..., Any] | None = None,
    logger: BootstrapLogger | None = None,
) -> typer.Typer:
    """Mount AppRC host-level bootstrap options and the generated config group.

    :param app: Host Typer application.
    :param kit: Application config facade.
    :param config_group_name: Name used for the mounted config command group.
    :param state_type: Host state type created by the standard callback.
    :param state_factory: Optional app-owned state factory used after runtime
        bootstrap has run.
    :param args_provider: Optional token provider for testing or forwarding.
        Returned tokens exclude the executable/program name.
    :param bootstrap_policy: Optional bootstrap skip policy. When omitted,
        AppRC skips runtime bootstrap for generated config setup/inspection and
        plain host command help.
    :param runtime_payload: Optional serializer for ``config show``.
    :param active_storage_root: Optional storage-root resolver for app state.
    :param active_storage_root_with_context: Optional storage-root resolver that
        can inspect explicit env-file selector context.
    :param initial_storage: Optional editor initial-selection resolver.
    :param initial_storage_with_context: Optional editor initial-selection
        resolver that can inspect explicit env-file selector context.
    :param editor_app_cls: Optional Textual subclass.
    :param help: Optional generated config group help text.
    :param setup_message: Optional setup text for missing storage.
    :param runtime_error_param_hint: Parameter hint for runtime-payload errors.
    :param setup_logging: Optional application logging setup callable.
    :param logger: Optional application logger for bootstrap status.
    :return: Mounted generated config Typer application.
    """
    if app.registered_callback is not None:
        raise RuntimeError(
            "mount_config_cli() cannot register AppRC host-level options "
            "because this Typer app already has a callback. Use "
            "ConfigCliBridge for host-owned callbacks, or use "
            "CliBootstrapOptions, prepare_typer_context(), and "
            "kit.typer_app(...) directly."
        )
    if state_factory is None and state_type is not DefaultConfigCliState:
        raise TypeError(
            "mount_config_cli() requires state_factory when state_type is "
            "custom. Pass state_factory=... or omit state_type to use "
            "DefaultConfigCliState."
        )
    ensure_config_group_name_available(app, config_group_name)

    resolved_state_factory: (
        Callable[[CliBootstrapContext, CliBootstrapOptions], Any] | None
    ) = None
    if state_factory is not None:

        def adapt_mount_state_factory(
            context: CliBootstrapContext,
            _options: CliBootstrapOptions,
        ) -> Any:
            """Build state through the mount helper factory contract."""
            return state_factory(context)

        resolved_state_factory = adapt_mount_state_factory

    bridge = ConfigCliBridge(
        kit,
        state_type=state_type,
        state_factory=resolved_state_factory,
        config_group_name=config_group_name,
        args_provider=args_provider,
        bootstrap_policy=bootstrap_policy,
        runtime_payload=runtime_payload,
        active_storage_root=active_storage_root,
        active_storage_root_with_context=active_storage_root_with_context,
        initial_storage=initial_storage,
        initial_storage_with_context=initial_storage_with_context,
        editor_app_cls=editor_app_cls,
        help=help,
        setup_message=setup_message,
        runtime_error_param_hint=runtime_error_param_hint,
        setup_logging=setup_logging,
        logger=logger,
    )

    @app.callback()
    def apprc_host_callback(
        ctx: typer.Context,
        env_files: EnvFilesOption = None,
        env_file_overrides_os_environ: EnvFileOverridesOption = False,
        skip_dotenv_layers: SkipDotenvLayersOption = False,
        storage: StorageOption = None,
        log_level: LogLevelOption = None,
    ) -> None:
        """Bootstrap AppRC state for commands that need runtime config."""
        options = CliBootstrapOptions.from_typer(
            env_files=env_files,
            env_file_overrides_os_environ=env_file_overrides_os_environ,
            load_dotenv_layers=not skip_dotenv_layers,
            storage=storage,
            log_level=log_level,
        )
        bridge.prepare(ctx, options)

    return bridge.mount_config_group(app)
