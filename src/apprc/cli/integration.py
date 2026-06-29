"""High-level Typer integration helpers for AppRC config commands."""

from __future__ import annotations

# == Standard Library ========================
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.cli.config.state import (
    ConfigBootstrapPolicy,
    DefaultConfigCliState,
)
from apprc.cli.context import (
    CliBootstrapContext,
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

type CliArgsProvider = Callable[[], Sequence[str]]
type CliStateFactory = Callable[[CliBootstrapContext], Any]


def mount_config_cli(
    app: typer.Typer,
    kit: AppConfigKit,
    *,
    command_name: str = "config",
    state_type: type[Any] = DefaultConfigCliState,
    state_factory: CliStateFactory | None = None,
    args_provider: CliArgsProvider | None = None,
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
    :param state_factory: Optional app-owned state factory used after runtime
        bootstrap has run.
    :param args_provider: Optional token provider for testing or forwarding.
        Returned tokens exclude the executable/program name.
    :param runtime_payload: Optional serializer for ``config show``.
    :param setup_logging: Optional application logging setup callable.
    :param logger: Optional application logger for bootstrap status.
    :param config_kwargs: Additional keyword arguments forwarded to
        :meth:`AppConfigKit.typer_app`.
    :return: Mounted generated config Typer application.
    """
    policy = ConfigBootstrapPolicy(command_name=command_name)
    provide_args = args_provider or _default_args_provider

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
        should_skip = ctx.resilient_parsing
        if not should_skip:
            should_skip = policy.request_skips_runtime_bootstrap(
                tokens=provide_args(),
            )
        context = prepare_typer_context(
            ctx,
            kit,
            options,
            skip_bootstrap=should_skip,
            setup_logging=setup_logging,
            logger=logger,
        )
        if context.skipped_runtime_bootstrap:
            ctx.obj = None
            return
        state = (
            state_factory(context)
            if state_factory is not None
            else _legacy_state_from_context(state_type, context)
        )
        if not isinstance(state, state_type):
            raise RuntimeError(
                "AppRC CLI state factory returned "
                f"{type(state).__name__}; expected {state_type.__name__}."
            )
        ctx.obj = state

    kwargs = dict(config_kwargs or {})
    kwargs["command_name"] = command_name
    config_app = kit.typer_app(
        state_type=state_type,
        runtime_payload=runtime_payload,
        **kwargs,
    )
    app.add_typer(config_app, name=command_name)
    return config_app


def _default_args_provider() -> Sequence[str]:
    """Read process command tokens for the default mount skip policy.

    :return: Command-line tokens without the executable name.
    """
    return sys.argv[1:]


def _legacy_state_from_context(
    state_type: type[Any],
    context: CliBootstrapContext,
) -> Any:
    """Create the backward-compatible default state object.

    :param state_type: Application state type with a zero-argument constructor.
    :param context: AppRC bootstrap context for this invocation.
    :return: Mutable state object populated with AppRC bootstrap fields.
    """
    state = state_type()
    state.env_bootstrap = context.env_bootstrap
    state.storage = context.options.storage
    return state
