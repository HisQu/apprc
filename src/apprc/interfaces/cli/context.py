"""AppRC Typer runtime context helpers."""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from os import environ
from pathlib import Path
from types import MappingProxyType
from typing import Any, Generic, Protocol, TypeVar

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.definition.paths import AppPaths, Layout
from apprc.definition.resolution import ResolveOptions
from apprc.interfaces.cli._resolution import resolve_cli_config
from apprc.public.app_rc import AppRC
from apprc.runtime.logging import ResolutionLogger
from apprc.runtime.resolution import ResolvedConfig

APPRC_CONTEXT_META_KEY = "apprc.interfaces.cli.runtime_context"
OptionsT = TypeVar("OptionsT", bound="CliRuntimeOptionsProtocol")


class CliRuntimeOptionsProtocol(Protocol):
    """Fields accepted by AppRC CLI runtime helpers."""

    @property
    def env_files(self) -> Sequence[Path] | None: ...

    @property
    def env_file_overrides_os_environ(self) -> bool: ...

    @property
    def load_dotenv_layers(self) -> bool: ...

    @property
    def workspace(self) -> str | None: ...

    @property
    def layout(self) -> Layout | None: ...

    @property
    def log_level(self) -> str | None: ...


@dataclass(frozen=True, slots=True)
class CliRuntimeOptions:
    """Parsed AppRC runtime options for one Typer CLI run."""

    env_files: tuple[Path, ...] = ()
    env_file_overrides_os_environ: bool = False
    load_dotenv_layers: bool = True
    workspace: str | None = None
    layout: Layout | None = None
    log_level: str | None = None

    @classmethod
    def from_typer(
        cls,
        *,
        env_files: Sequence[Path] | None = None,
        env_file_overrides_os_environ: bool = False,
        load_dotenv_layers: bool = True,
        workspace: str | None = None,
        layout: str | None = None,
        app_root: Path | None = None,
        log_level: str | None = None,
    ) -> CliRuntimeOptions:
        """Normalize Typer runtime controls, including paired layout inputs."""
        selected_layout = None
        if layout is not None or app_root is not None:
            mode = layout or (
                "single-root" if app_root is not None else "native"
            )
            if mode == "native":
                if app_root is not None:
                    raise ValueError(
                        "--app-root cannot be combined with --layout native."
                    )
                selected_layout = Layout.native()
            elif mode == "single-root":
                if app_root is None:
                    raise ValueError(
                        "--layout single-root requires --app-root."
                    )
                selected_layout = Layout.single_root(app_root)
            else:
                raise ValueError(f"Unsupported AppRC layout: {mode!r}.")
        return cls(
            env_files=tuple(env_files or ()),
            env_file_overrides_os_environ=env_file_overrides_os_environ,
            load_dotenv_layers=load_dotenv_layers,
            workspace=workspace,
            layout=selected_layout,
            log_level=log_level,
        )

    @classmethod
    def from_options(
        cls,
        options: CliRuntimeOptionsProtocol,
    ) -> CliRuntimeOptions:
        """Return an immutable copy of an option-like object."""
        if isinstance(options, cls):
            return options
        return cls(
            env_files=tuple(options.env_files or ()),
            env_file_overrides_os_environ=options.env_file_overrides_os_environ,
            load_dotenv_layers=options.load_dotenv_layers,
            workspace=options.workspace,
            layout=options.layout,
            log_level=options.log_level,
        )


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


def _store_apprc_context(
    ctx: typer.Context,
    context: CliRuntimeContext[Any],
) -> None:
    """Attach AppRC context to Typer metadata for this CLI run."""
    ctx.meta[APPRC_CONTEXT_META_KEY] = context
