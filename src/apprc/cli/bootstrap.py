"""Root CLI bootstrap helpers."""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.cli.errors import config_home_bad_parameter
from apprc.runtime_config.bootstrap.dotenv_layers import ExplicitEnvFileError
from apprc.runtime_config.bootstrap.result import (
    BootstrapLogger,
    EnvBootstrapResult,
)
from apprc.runtime_config.config_home import ConfigHomeError
from apprc.runtime_config.kit import AppConfigKit
from apprc.runtime_config.contract.apprc_toml_env import ApprcTomlEnvError
from apprc.runtime_config.storage.selector import StorageSelectorError


def parse_log_level(log_level: str) -> str | int:
    """Convert a CLI log-level token into the logging backend value.

    :param log_level: User-provided Typer option value.
    :return: Integer level for decimal strings, otherwise the original token.
    """
    return int(log_level) if log_level.isdecimal() else log_level


def bootstrap_cli_env(
    kit: AppConfigKit,
    *,
    env_files: Sequence[Path],
    env_file_overrides_os_environ: bool,
    load_dotenv_layers: bool,
    storage: str | None,
    log_level: str | None = None,
    setup_logging: Callable[..., Any] | None = None,
    logger: BootstrapLogger | None = None,
) -> EnvBootstrapResult:
    """Initialize logging and dotenv layers for one CLI process.

    :param kit: Application config facade.
    :param env_files: Optional invocation-local dotenv files that outrank
        packaged ``.env.shared``, app-global ``.env.global``, and active
        storage-local ``.env.local``.
    :param env_file_overrides_os_environ: Whether explicit dotenv values beat
        existing values in ``os.environ`` inside this process. The parent shell
        is never mutated.
    :param load_dotenv_layers: Whether packaged ``.env.shared``, app-global
        ``.env.global``, active storage-local ``.env.local``, and explicit
        ``env_files`` values should be merged into this process. Registry
        selection still runs for storage-required apps when this is ``False``,
        and explicit values may still provide the storage selector used for
        selection.
    :param storage: Optional ``--storage`` selector for storage-required apps.
        With a registry it may be a registered storage name or path. Without a
        registry it is always interpreted as a path.
    :param log_level: Optional CLI log-level token.
    :param setup_logging: Optional application logging setup callable.
    :param logger: Optional application logger for bootstrap status messages.
    :return: Bootstrap summary for diagnostics and tests.
    :raises typer.BadParameter: If an explicit env file or storage selector
        is invalid.
    """
    if setup_logging is not None and log_level is not None:
        setup_logging(level=parse_log_level(log_level))
    try:
        return kit.bootstrap(
            env_files=env_files,
            env_file_overrides_os_environ=env_file_overrides_os_environ,
            load_dotenv_layers=load_dotenv_layers,
            storage=storage,
            logger=logger,
        )
    except FileNotFoundError as exc:
        raise typer.BadParameter(str(exc), param_hint="--env-file") from exc
    except ExplicitEnvFileError as exc:
        raise typer.BadParameter(str(exc), param_hint="--env-file") from exc
    except ApprcTomlEnvError as exc:
        raise typer.BadParameter(
            str(exc),
            param_hint=kit.spec.apprc_toml_env_key,
        ) from exc
    except StorageSelectorError as exc:
        raise typer.BadParameter(
            str(exc),
            param_hint=exc.param_hint,
        ) from exc
    except ConfigHomeError as exc:
        raise config_home_bad_parameter(exc) from exc
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--storage") from exc
