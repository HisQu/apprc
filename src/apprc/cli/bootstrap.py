"""Root CLI bootstrap helpers."""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Callable
from pathlib import Path
from typing import Any

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.config.app_spec import ApprcTomlEnvError
from apprc.config.environment import BootstrapLogger, EnvBootstrapResult
from apprc.config.kit import AppConfigKit
from apprc.config.storage.selector import StorageSelectorError


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
    env_file_overrides_os_environ: bool,
    load_dotenv_layers: bool,
    storage: str | None,
    log_level: str | None = None,
    setup_logging: Callable[..., Any] | None = None,
    logger: BootstrapLogger | None = None,
) -> EnvBootstrapResult:
    """Initialize logging and dotenv layers for one CLI process.

    :param kit: Application config facade.
    :param env_file: Optional invocation-local dotenv file that outranks the
        packaged ``.env.shared`` and active storage-local ``.env.local``.
    :param env_file_overrides_os_environ: Whether explicit dotenv values beat
        existing values in ``os.environ`` inside this process. The parent shell
        is never mutated.
    :param load_dotenv_layers: Whether packaged ``.env.shared``, active
        storage-local ``.env.local``, and explicit ``env_file`` values should
        be merged into this process. Registry selection still runs when this
        is ``False``, and explicit ``env_file`` values may still provide the
        storage selector used for selection.
    :param storage: Optional ``--storage`` selector. With an AppRC TOML it may
        be a registered storage name or path. Without an AppRC TOML it is
        always interpreted as a path.
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
            env_file_overrides_os_environ=env_file_overrides_os_environ,
            load_dotenv_layers=load_dotenv_layers,
            storage=storage,
            logger=logger,
        )
    except FileNotFoundError as exc:
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
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--storage") from exc
