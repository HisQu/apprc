"""High-level Typer integration helpers for AppRC config commands."""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Callable, Mapping
from typing import Any

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.cli.config.state import (
    ConfigBootstrapPolicy,
    DefaultConfigCliState,
)
from apprc.cli.context import (
    CliBootstrapOptions,
    prepare_typer_context,
)
from apprc.cli.options import (
    EnvFileOverridesOption,
    EnvFilesOption,
    LogLevelOption,
    SkipDotenvLayersOption,
    StorageOption,
)
from apprc.runtime_config.bootstrap.result import BootstrapLogger
from apprc.runtime_config.kit import AppConfigKit


def mount_config_cli(
    app: typer.Typer,
    kit: AppConfigKit,
    *,
    command_name: str = "config",
    state_type: type[Any] = DefaultConfigCliState,
    runtime_payload: Callable[[Any], Mapping[str, Any]] | None = None,
    setup_logging: Callable[..., Any] | None = None,
    logger: BootstrapLogger | None = None,
    config_kwargs: Mapping[str, Any] | None = None,
) -> typer.Typer:
    """Mount AppRC root bootstrap options and the generated config group.

    :param app: Host Typer application.
    :param kit: Application config facade.
    :param command_name: Name used for the mounted config command group.
    :param state_type: Root state type created by the standard callback.
    :param runtime_payload: Optional serializer for ``config show``.
    :param setup_logging: Optional application logging setup callable.
    :param logger: Optional application logger for bootstrap status.
    :param config_kwargs: Additional keyword arguments forwarded to
        :meth:`AppConfigKit.typer_app`.
    :return: Mounted generated config Typer application.
    """
    policy = ConfigBootstrapPolicy(command_name=command_name)

    @app.callback()
    def apprc_root_callback(
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
        should_skip = ctx.resilient_parsing or (
            policy.request_skips_runtime_bootstrap()
        )
        context = prepare_typer_context(
            ctx,
            kit,
            options,
            skip_bootstrap=should_skip,
            setup_logging=setup_logging,
            logger=logger,
        )
        state = state_type()
        state.env_bootstrap = context.env_bootstrap
        state.storage = storage
        ctx.obj = state

    kwargs = dict(config_kwargs or {})
    config_app = kit.typer_app(
        state_type=state_type,
        runtime_payload=runtime_payload,
        **kwargs,
    )
    app.add_typer(config_app, name=command_name)
    return config_app
