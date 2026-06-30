"""AppRC Typer bootstrap context helpers."""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.cli.bootstrap import bootstrap_cli_env
from apprc.runtime_config.bootstrap.result import (
    BootstrapLogger,
    EnvBootstrapResult,
)
from apprc.runtime_config.kit import AppConfigKit

APPRC_CONTEXT_META_KEY = "apprc.cli.bootstrap_context"


class CliBootstrapOptionsProtocol(Protocol):
    """Fields accepted by AppRC CLI bootstrap helpers."""

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
class CliBootstrapOptions:
    """Parsed AppRC host-level options for one Typer CLI run.

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
    ) -> CliBootstrapOptions:
        """Build normalized options from Typer callback parameters.

        :param env_files: Optional repeated ``--env-file`` values.
        :param env_file_overrides_os_environ: Parsed override policy flag.
        :param load_dotenv_layers: Whether dotenv values should be merged.
        :param storage: Parsed storage selector.
        :param log_level: Parsed logging level token.
        :return: Immutable AppRC bootstrap options.
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
        options: CliBootstrapOptionsProtocol,
    ) -> CliBootstrapOptions:
        """Return an immutable copy of an option-like object.

        :param options: Object exposing AppRC bootstrap option attributes.
        :return: Normalized bootstrap options.
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
class CliBootstrapContext:
    """AppRC state stored on Typer context metadata.

    :param options: Normalized AppRC host-level options.
    :param env_bootstrap: Bootstrap result when runtime bootstrap ran.
    :param skipped_runtime_bootstrap: Whether this CLI run intentionally
        avoided runtime bootstrap.
    """

    options: CliBootstrapOptions
    env_bootstrap: EnvBootstrapResult | None = None
    skipped_runtime_bootstrap: bool = False


def bootstrap_cli_options(
    kit: AppConfigKit,
    options: CliBootstrapOptionsProtocol,
    *,
    setup_logging: Callable[..., Any] | None = None,
    logger: BootstrapLogger | None = None,
) -> EnvBootstrapResult:
    """Run AppRC bootstrap from a parsed options object.

    :param kit: Application config facade.
    :param options: Parsed AppRC host-level options.
    :param setup_logging: Optional application logging setup callable.
    :param logger: Optional application logger for bootstrap status.
    :return: Bootstrap summary for diagnostics and command state.
    """
    parsed = CliBootstrapOptions.from_options(options)
    return bootstrap_cli_env(
        kit,
        env_files=parsed.env_files,
        env_file_overrides_os_environ=(parsed.env_file_overrides_os_environ),
        load_dotenv_layers=parsed.load_dotenv_layers,
        storage=parsed.storage,
        log_level=parsed.log_level,
        setup_logging=setup_logging,
        logger=logger,
    )


def prepare_typer_context(
    ctx: typer.Context,
    kit: AppConfigKit,
    options: CliBootstrapOptionsProtocol,
    *,
    skip_bootstrap: bool = False,
    setup_logging: Callable[..., Any] | None = None,
    logger: BootstrapLogger | None = None,
) -> CliBootstrapContext:
    """Store AppRC bootstrap context for a Typer CLI run.

    :param ctx: Active Typer context.
    :param kit: Application config facade.
    :param options: Parsed AppRC host-level options.
    :param skip_bootstrap: Whether runtime bootstrap should be skipped.
    :param setup_logging: Optional application logging setup callable.
    :param logger: Optional application logger for bootstrap status.
    :return: Context stored on ``ctx.meta`` for child commands.
    """
    parsed = CliBootstrapOptions.from_options(options)
    env_bootstrap = None
    if not skip_bootstrap:
        env_bootstrap = bootstrap_cli_options(
            kit,
            parsed,
            setup_logging=setup_logging,
            logger=logger,
        )
    context = CliBootstrapContext(
        options=parsed,
        env_bootstrap=env_bootstrap,
        skipped_runtime_bootstrap=skip_bootstrap,
    )
    _store_apprc_context(ctx, context)
    return context


def apprc_context_from(ctx: typer.Context) -> CliBootstrapContext | None:
    """Return the nearest AppRC bootstrap context for a Typer command.

    :param ctx: Active Typer context.
    :return: Stored bootstrap context, or ``None`` when the host app used the
        legacy ``ctx.obj`` integration only.
    """
    current: Any = ctx
    while current is not None:
        context = getattr(current, "meta", {}).get(APPRC_CONTEXT_META_KEY)
        if isinstance(context, CliBootstrapContext):
            return context
        current = getattr(current, "parent", None)
    return None


def apprc_options_to_args(
    options: CliBootstrapOptionsProtocol,
) -> list[str]:
    """Return CLI tokens that preserve AppRC host-level option values.

    :param options: Parsed AppRC host-level options.
    :return: Long-form CLI option tokens suitable for forwarding.
    """
    parsed = CliBootstrapOptions.from_options(options)
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
    context: CliBootstrapContext,
) -> None:
    """Attach AppRC context to Typer metadata for this CLI run."""
    ctx.meta[APPRC_CONTEXT_META_KEY] = context
