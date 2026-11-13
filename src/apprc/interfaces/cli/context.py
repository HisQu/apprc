"""AppRC Typer runtime context helpers."""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from os import environ
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Generic, TypeVar

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.definition.app_config.spec import AppConfigSpec
from apprc.definition.installation import InstallationInspection
from apprc.definition.paths import AppPaths, Layout
from apprc.definition.resolution import (
    CliRuntimeOptions,
    CliRuntimeOptionsProtocol,
    ResolveOptions,
    _BridgeRuntimeOptions,
)
from apprc.interfaces.cli._resolution import resolve_cli_config
from apprc.public.app_rc import AppRC
from apprc.runtime.logging import ResolutionLogger
from apprc.runtime.resolution import ResolvedConfig
from apprc.services.installation import InstallationManager

if TYPE_CHECKING:
    from apprc.distribution.models import NativeBinding


APPRC_CONTEXT_META_KEY = "apprc.interfaces.cli.runtime_context"
OptionsT = TypeVar("OptionsT", bound="CliRuntimeOptionsProtocol")


_AUTHENTICATED_NATIVE_MANAGER: ContextVar[Path | None] = ContextVar(
    "apprc_authenticated_native_manager", default=None
)


@dataclass(frozen=True, slots=True)
class InstallationCommandContext:
    """Captured installation authority for recovery commands without paths.

    :param runtime_options: Parsed invocation controls.
    :param cli_options: Host-owned CLI options, preserved without storing them
        in ``ctx.obj``.
    :param environment: Immutable process environment captured at callback time.
    :param inspection: Read-only installation inspection, including invalid or
        pending authority diagnostics.
    :param manager: Host-bound manager used for explicit recovery operations.
    :param path_error: Original placement failure retained by diagnostic doctor.
    :param native_binding: Authenticated native product declaration, when present.
    :param _native_manager_executable: Authenticated executable available only
        during the native manager's own CLI invocation.
    """

    runtime_options: CliRuntimeOptions
    cli_options: Any
    environment: Mapping[str, str]
    inspection: InstallationInspection
    manager: InstallationManager
    runtime_setup_skipped: bool = True
    path_error: str | None = None
    native_binding: NativeBinding | None = None
    _native_manager_executable: Path | None = None


@contextmanager
def _authenticated_native_manager_scope(executable: Path) -> Iterator[None]:
    """Expose an authenticated manager path only while its own CLI runs.

    :param executable: Absolute executable currently running the native CLI.
    :return: Context manager that restores the previous authenticated scope.
    """
    token = _AUTHENTICATED_NATIVE_MANAGER.set(executable)
    try:
        yield
    finally:
        _AUTHENTICATED_NATIVE_MANAGER.reset(token)


def installation_command_context_from(
    ctx: typer.Context,
) -> InstallationCommandContext | None:
    """Return nearest diagnostic/recovery installation context."""
    current: Any = ctx
    while current is not None:
        context = getattr(current, "meta", {}).get(APPRC_CONTEXT_META_KEY)
        if isinstance(context, InstallationCommandContext):
            return context
        current = getattr(current, "parent", None)
    return None


def prepare_installation_command_context(
    ctx: typer.Context,
    apprc: AppRC,
    options: CliRuntimeOptionsProtocol,
    *,
    path_error: str | None = None,
) -> InstallationCommandContext:
    """Capture host installation authority without resolving business paths.

    :param ctx: Active Typer context receiving recovery metadata.
    :param apprc: Host declaration, not resolved business settings.
    :param options: Captured invocation controls.
    :param path_error: Placement failure that caused diagnostic fallback.
    :return: Installation-only context with the original failure preserved.
    """

    parsed = CliRuntimeOptions.from_options(options)
    environment = MappingProxyType(dict(environ))
    manager = apprc.installation(environment=environment)
    context = InstallationCommandContext(
        runtime_options=parsed,
        cli_options=options,
        environment=environment,
        inspection=manager.inspect(),
        manager=manager,
        path_error=path_error,
    )
    _store_apprc_context(ctx, context)
    return context


def prepare_native_installation_context(
    ctx: typer.Context,
    binding: NativeBinding,
    options: CliRuntimeOptionsProtocol,
    *,
    environment: Mapping[str, str],
) -> InstallationCommandContext:
    """Prepare core recovery from immutable native declarations only.

    The empty configuration-owner declaration is intentional: native recovery
    must not import an application package before it has located a runtime.
    """
    parsed = CliRuntimeOptions.from_options(options)
    captured = MappingProxyType(dict(environment))
    spec = AppConfigSpec(
        app_id=binding.identity.app_id,
        display_name=binding.display_name,
        paths=binding.capabilities.paths,
        layout=binding.layout,
        bootstrap_env_prefix=binding.bootstrap_env_prefix,
        command_name=binding.command_name,
    )
    manager = InstallationManager(spec, environment=captured)
    context = InstallationCommandContext(
        runtime_options=parsed,
        cli_options=options,
        environment=captured,
        inspection=manager.inspect(),
        manager=manager,
        native_binding=binding,
        _native_manager_executable=_AUTHENTICATED_NATIVE_MANAGER.get(),
    )
    _store_apprc_context(ctx, context)
    return context


@dataclass(slots=True)
class CliRuntimeContext(Generic[OptionsT]):
    """Captured bootstrap state stored on Typer context metadata."""

    runtime_options: CliRuntimeOptions
    cli_options: OptionsT
    paths: AppPaths
    environment: Mapping[str, str]
    resolved: ResolvedConfig | None = None
    runtime_setup_skipped: bool = False
    workspace_required: bool = False


def resolve_cli_options(
    apprc: AppRC,
    options: CliRuntimeOptionsProtocol,
    *,
    workspace_required: bool = False,
    environment: Mapping[str, str] | None = None,
    app_paths: AppPaths | None = None,
    setup_logging: Callable[..., Any] | None = None,
    logger: ResolutionLogger | None = None,
) -> ResolvedConfig:
    """Resolve configuration using a captured environment/path snapshot."""
    parsed = CliRuntimeOptions.from_options(options)
    return resolve_cli_config(
        apprc,
        env_files=parsed.env_files,
        env_file_overrides_os_environ=parsed.env_file_overrides_os_environ,
        load_dotenv_layers=parsed.load_dotenv_layers,
        workspace=parsed.workspace,
        workspace_required=workspace_required,
        layout=parsed.layout,
        environment=environment,
        app_paths=app_paths,
        log_level=parsed.log_level,
        setup_logging=setup_logging,
        logger=logger,
    )


def prepare_cli_runtime_context(
    ctx: typer.Context,
    apprc: AppRC,
    options: OptionsT,
    *,
    skip_runtime_setup: bool = False,
    workspace_required: bool = False,
    setup_logging: Callable[..., Any] | None = None,
    logger: ResolutionLogger | None = None,
) -> CliRuntimeContext[OptionsT]:
    """Capture bootstrap paths/environment before optional runtime setup."""
    parsed = CliRuntimeOptions.from_options(options)
    environment = MappingProxyType(dict(environ))
    resolve_options = ResolveOptions(
        env_files=parsed.env_files,
        env_file_overrides_os_environ=parsed.env_file_overrides_os_environ,
        load_dotenv_layers=parsed.load_dotenv_layers,
        workspace=parsed.workspace,
        layout=parsed.layout,
    )
    paths = apprc.paths(resolve_options, environment=environment)
    resolved = None
    if not skip_runtime_setup:
        resolved = resolve_cli_options(
            apprc,
            parsed,
            workspace_required=workspace_required,
            environment=environment,
            app_paths=paths,
            setup_logging=setup_logging,
            logger=logger,
        )
    context = CliRuntimeContext(
        runtime_options=parsed,
        cli_options=options,
        paths=paths,
        environment=environment,
        resolved=resolved,
        runtime_setup_skipped=skip_runtime_setup,
        workspace_required=workspace_required,
    )
    _store_apprc_context(ctx, context)
    return context


def cli_runtime_context_from(
    ctx: typer.Context,
) -> CliRuntimeContext[Any] | None:
    """Return the nearest AppRC resolution context for a Typer command."""
    current: Any = ctx
    while current is not None:
        context = getattr(current, "meta", {}).get(APPRC_CONTEXT_META_KEY)
        if isinstance(context, CliRuntimeContext):
            return context
        current = getattr(current, "parent", None)
    return None


def cli_options_from(
    ctx: typer.Context,
    expected_type: type[OptionsT],
) -> OptionsT:
    """Return the typed app CLI options stored on Typer metadata."""
    context = cli_runtime_context_from(ctx)
    if context is None:
        raise RuntimeError("AppRC CLI runtime context is not initialized.")
    cli_options = context.cli_options
    if not isinstance(cli_options, expected_type):
        raise TypeError(
            "AppRC CLI options have type "
            f"{type(cli_options).__name__}; expected {expected_type.__name__}."
        )
    return cli_options


def cli_runtime_options_to_args(
    options: CliRuntimeOptionsProtocol,
) -> list[str]:
    """Return CLI tokens that preserve AppRC runtime option values."""
    parsed = CliRuntimeOptions.from_options(options)
    args: list[str] = []
    if parsed.log_level is not None:
        args.extend(["--log-level", parsed.log_level])
    for env_file in parsed.env_files:
        args.extend(["--env-file", str(env_file)])
    if parsed.env_file_overrides_os_environ:
        args.append("--env-file-overrides-os-environ")
    if not parsed.load_dotenv_layers:
        args.append("--skip-dotenv-layers")
    if parsed.workspace is not None:
        args.extend(["--workspace", parsed.workspace])
    if parsed.layout is not None:
        args.extend(["--layout", parsed.layout.mode])
        if parsed.layout.root is not None:
            args.extend(["--app-root", str(parsed.layout.root)])
    return args


def _cli_runtime_options_payload(
    options: CliRuntimeOptionsProtocol,
    maintenance_group_name: str = "app",
) -> dict[str, object]:
    """Encode captured CLI options for the isolated application bridge."""
    from apprc.user_files.installation.codec import _encode

    captured = CliRuntimeOptions.from_options(options)
    runtime = replace(
        captured,
        env_files=tuple(
            path.expanduser().absolute() for path in captured.env_files
        ),
    )
    payload = _encode(
        _BridgeRuntimeOptions(runtime, maintenance_group_name)
    )
    if not isinstance(payload, dict):
        raise TypeError("Bridge runtime options did not encode as an object.")
    return payload


def _store_apprc_context(
    ctx: typer.Context,
    context: CliRuntimeContext[Any] | InstallationCommandContext,
) -> None:
    """Attach AppRC context to Typer metadata for this CLI run."""
    ctx.meta[APPRC_CONTEXT_META_KEY] = context
