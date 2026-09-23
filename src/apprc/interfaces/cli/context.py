"""AppRC Typer runtime context helpers."""

from __future__ import annotations

from apprc.runtime.resolution import ResolvedConfig

# == Standard Library ========================
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, Protocol, TypeVar

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.interfaces.cli._resolution import resolve_cli_config
from apprc.runtime.logging import (
    ResolutionLogger,
)
from apprc.public.app_rc import AppRC

APPRC_CONTEXT_META_KEY = "apprc.interfaces.cli.runtime_context"
OptionsT = TypeVar("OptionsT", bound="CliRuntimeOptionsProtocol")


class CliRuntimeOptionsProtocol(Protocol):
    """Fields accepted by AppRC CLI runtime helpers."""

    @property
    def env_files(self) -> Sequence[Path] | None:
        """Explicit dotenv files passed to the CLI."""
        ...

    @property
    def env_file_overrides_os_environ(self) -> bool:
        """Whether explicit dotenv values beat process env values."""
        ...

    @property
    def load_dotenv_layers(self) -> bool:
        """Whether configured dotenv layers should be merged."""
        ...

    @property
    def storage(self) -> str | None:
        """Optional active storage selector."""
        ...

    @property
    def log_level(self) -> str | None:
        """Optional logging level token."""
        ...


@dataclass(frozen=True, slots=True)
class CliRuntimeOptions:
    """Parsed AppRC runtime options for one Typer CLI run.

    :param env_files: Explicit dotenv files passed to the CLI.
    :param env_file_overrides_os_environ: Whether explicit dotenv values beat
        values already present in ``os.environ``.
    :param load_dotenv_layers: Whether AppRC should merge configured dotenv
        layers into this Python process.
    :param storage: Optional active storage selector.
    :param log_level: Optional logging level token passed to the app logging
        setup callable.
    """

    env_files: tuple[Path, ...] = ()
    env_file_overrides_os_environ: bool = False
    load_dotenv_layers: bool = True
    storage: str | None = None
    log_level: str | None = None

    @classmethod
    def from_typer(
        cls,
        *,
        env_files: Sequence[Path] | None = None,
        env_file_overrides_os_environ: bool = False,
        load_dotenv_layers: bool = True,
        storage: str | None = None,
        log_level: str | None = None,
    ) -> CliRuntimeOptions:
        """Build normalized options from Typer callback parameters.

        :param env_files: Optional repeated ``--env-file`` values.
        :param env_file_overrides_os_environ: Parsed override policy flag.
        :param load_dotenv_layers: Whether dotenv values should be merged.
        :param storage: Parsed storage selector.
        :param log_level: Parsed logging level token.
        :return: Immutable AppRC runtime options.
        """
        return cls(
            env_files=tuple(env_files or ()),
            env_file_overrides_os_environ=env_file_overrides_os_environ,
            load_dotenv_layers=load_dotenv_layers,
            storage=storage,
            log_level=log_level,
        )

    @classmethod
    def from_options(
        cls,
        options: CliRuntimeOptionsProtocol,
    ) -> CliRuntimeOptions:
        """Return an immutable copy of an option-like object.

        :param options: Object exposing AppRC runtime option attributes.
        :return: Normalized runtime options.
        """
        if isinstance(options, cls):
            return options
        return cls(
            env_files=tuple(options.env_files or ()),
            env_file_overrides_os_environ=(
                options.env_file_overrides_os_environ
            ),
            load_dotenv_layers=options.load_dotenv_layers,
            storage=options.storage,
            log_level=options.log_level,
        )


@dataclass(slots=True)
class CliRuntimeContext(Generic[OptionsT]):
    """AppRC state stored on Typer context metadata.

    :param runtime_options: Normalized AppRC runtime options.
    :param cli_options: Original app CLI options passed to the runtime.
    :param resolved: Resolved snapshot when runtime setup ran.
    :param runtime_setup_skipped: Whether this CLI run intentionally
        avoided runtime setup.
    """

    runtime_options: CliRuntimeOptions
    cli_options: OptionsT
    resolved: ResolvedConfig | None = None
    runtime_setup_skipped: bool = False
    storage_required: bool = False


def resolve_cli_options(
    apprc: AppRC,
    options: CliRuntimeOptionsProtocol,
    *,
    storage_required: bool = False,
    setup_logging: Callable[..., Any] | None = None,
    logger: ResolutionLogger | None = None,
) -> ResolvedConfig:
    """Run AppRC resolution from a parsed options object.

    :param apprc: Application config facade.
    :param options: Parsed AppRC runtime options.
    :param storage_required: Runtime storage policy, independent of the declaration.
    :param setup_logging: Optional application logging setup callable.
    :param logger: Optional application logger for resolution status.
    :return: Resolved snapshot for diagnostics and command state.
    """
    parsed = CliRuntimeOptions.from_options(options)
    return resolve_cli_config(
        apprc,
        env_files=parsed.env_files,
        env_file_overrides_os_environ=(parsed.env_file_overrides_os_environ),
        load_dotenv_layers=parsed.load_dotenv_layers,
        storage=parsed.storage,
        storage_required=storage_required,
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
    storage_required: bool = False,
    setup_logging: Callable[..., Any] | None = None,
    logger: ResolutionLogger | None = None,
) -> CliRuntimeContext[OptionsT]:
    """Store AppRC resolution context for a Typer CLI run.

    :param ctx: Active Typer context.
    :param apprc: Application config facade.
    :param options: Parsed AppRC runtime options.
    :param skip_runtime_setup: Whether runtime setup should be skipped.
    :param storage_required: Runtime storage policy, independent of the declaration.
    :param setup_logging: Optional application logging setup callable.
    :param logger: Optional application logger for resolution status.
    :return: Context stored on ``ctx.meta`` for child commands.
    """
    parsed = CliRuntimeOptions.from_options(options)
    resolved = None
    if not skip_runtime_setup:
        resolved = resolve_cli_options(
            apprc,
            parsed,
            storage_required=storage_required,
            setup_logging=setup_logging,
            logger=logger,
        )
    context = CliRuntimeContext(
        runtime_options=parsed,
        cli_options=options,
        resolved=resolved,
        runtime_setup_skipped=skip_runtime_setup,
        storage_required=storage_required,
    )
    _store_apprc_context(ctx, context)
    return context


def cli_runtime_context_from(
    ctx: typer.Context,
) -> CliRuntimeContext[Any] | None:
    """Return the nearest AppRC resolution context for a Typer command.

    :param ctx: Active Typer context.
    :return: Stored runtime context, or ``None`` when the app did not prepare
        AppRC runtime metadata.
    """
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
    """Return the typed app CLI options stored on Typer metadata.

    :param ctx: Active Typer context.
    :param expected_type: Runtime type expected for the original options.
    :return: The app CLI options passed to ``CliRuntime.prepare(...)``.
    :raises RuntimeError: If no AppRC CLI runtime context is present.
    :raises TypeError: If the stored options have another runtime type.
    """
    context = cli_runtime_context_from(ctx)
    if context is None:
        raise RuntimeError("AppRC CLI runtime context is not initialized.")
    cli_options = context.cli_options
    if not isinstance(cli_options, expected_type):
        raise TypeError(
            "AppRC CLI options have type "
            f"{type(cli_options).__name__}; expected "
            f"{expected_type.__name__}."
        )
    return cli_options


def cli_runtime_options_to_args(
    options: CliRuntimeOptionsProtocol,
) -> list[str]:
    """Return CLI tokens that preserve AppRC runtime option values.

    :param options: Parsed AppRC runtime options.
    :return: Long-form CLI option tokens suitable for forwarding.
    """
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
    if parsed.storage is not None:
        args.extend(["--storage", parsed.storage])
    return args


def _store_apprc_context(
    ctx: typer.Context,
    context: CliRuntimeContext[Any],
) -> None:
    """Attach AppRC context to Typer metadata for this CLI run."""
    ctx.meta[APPRC_CONTEXT_META_KEY] = context
