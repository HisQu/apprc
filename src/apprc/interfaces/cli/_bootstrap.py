"""Host CLI bootstrap helpers."""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.interfaces.cli._errors import apprc_dir_bad_parameter
from apprc.runtime._dotenv_layers import ExplicitEnvFileError
from apprc.runtime.result import (
    BootstrapLogger,
    EnvBootstrapResult,
)
from apprc.user_files.app_home.locations import AppRCDirectoryError
from apprc.definition.app_config.kit import AppConfigKit
from apprc.user_files.storage_roots._loading import MissingStorageRegistryError
from apprc.user_files.storage_roots.selector import StorageSelectorError
from apprc.user_files.storage_roots.selector import MissingStorageSelectorError


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
    :param env_files: Optional CLI-run-local dotenv files that outrank
        packaged ``apprc.defaults.env``, user ``apprc.user.env``, and active
        storage ``apprc.storage.env``.
    :param env_file_overrides_os_environ: Whether explicit dotenv values beat
        existing values in ``os.environ`` inside this process. The parent shell
        is never mutated.
    :param load_dotenv_layers: Whether packaged ``apprc.defaults.env``, app
        ``apprc.user.env``, active storage ``apprc.storage.env``, and
        explicit ``env_files`` values should be merged into this process. Registry
        selection still runs for storage apps when this is ``False``,
        and explicit values may still provide the storage selector used for
        selection.
    :param storage: Optional registered name from ``--storage``.
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
    except MissingStorageRegistryError as exc:
        raise typer.BadParameter(
            str(exc),
            param_hint=kit.spec.apprc_dir_env_key,
        ) from exc
    except MissingStorageSelectorError:
        raise
    except StorageSelectorError as exc:
        raise typer.BadParameter(
            str(exc),
            param_hint=exc.param_hint,
        ) from exc
    except AppRCDirectoryError as exc:
        raise apprc_dir_bad_parameter(exc) from exc
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--storage") from exc
