"""Root CLI bootstrap helpers."""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Callable
from pathlib import Path
from typing import Any

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.config.environment import BootstrapLogger, EnvBootstrapResult
from apprc.config.kit import AppConfigKit


def parse_log_level(log_level: str) -> str | int:
    """Convert a CLI log-level token into the logging backend value.

    :param log_level: User-provided Typer option value.
    :return: Integer level for decimal strings, otherwise the original token.
    """
    return int(log_level) if log_level.isdecimal() else log_level


def bootstrap_cli_env(
    kit: AppConfigKit,
    *,
    env_file: Path | None,
    env_file_overrides_shell: bool,
    load_dotenv_layers: bool,
    storage_name: str | None,
    log_level: str | None = None,
    setup_logging: Callable[..., Any] | None = None,
    logger: BootstrapLogger | None = None,
) -> EnvBootstrapResult:
    """Initialize logging and dotenv layers for one CLI process.

    :param kit: Application config facade.
    :param env_file: Optional explicit dotenv file.
    :param env_file_overrides_shell: Whether explicit dotenv values beat
        already exported variables inside this process.
    :param load_dotenv_layers: Whether packaged ``.env.shared``, active
        storage-local ``.env.local``, and explicit ``env_file`` values should
        be merged into this process. Registry selection still runs when this
        is ``False``, and explicit ``env_file`` values may still provide the
        storage root used for selection.
    :param storage_name: Optional named storage selector.
    :param log_level: Optional CLI log-level token.
    :param setup_logging: Optional application logging setup callable.
    :param logger: Optional application logger for bootstrap status messages.
    :return: Bootstrap summary for diagnostics and tests.
    :raises typer.BadParameter: If the explicit env file or storage selector
        is invalid.
    """
    if setup_logging is not None and log_level is not None:
        setup_logging(level=parse_log_level(log_level))
    try:
        return kit.bootstrap(
            env_file=env_file,
            env_file_overrides_shell=env_file_overrides_shell,
            load_dotenv_layers=load_dotenv_layers,
            storage_name=storage_name,
            logger=logger,
        )
    except FileNotFoundError as exc:
        raise typer.BadParameter(str(exc), param_hint="--env-file") from exc
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--storage") from exc
