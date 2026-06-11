"""Resolve the AppRC TOML file selected for one application.

The AppRC TOML is the user-level state file selected by
``<APP>_APPRC_TOML``. Its storage tables are parsed by
:mod:`apprc.config.storage.registry`, while this module owns the file naming and
environment-variable contract so future non-storage AppRC settings can reuse the
same file without living in storage-specific code.
"""

from __future__ import annotations

# == Standard Library ========================
import os
import re
from collections.abc import Mapping
from pathlib import Path


class ApprcTomlEnvError(ValueError):
    """Raised when an app's AppRC TOML path cannot be resolved from the env."""


def default_apprc_toml_filename(app_name: str) -> str:
    """Return the conventional AppRC TOML basename for one application.

    :param app_name: Application name from the AppRC integration spec.
    :return: Host-specific TOML filename ending in ``.apprc.toml``.
    """
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "_", app_name).strip("_-")
    base_name = normalized or "app"
    return f"{base_name}.apprc.toml"


def apprc_toml_env_key(app_name: str) -> str:
    """Return the environment variable that selects the AppRC TOML.

    :param app_name: Application name from the AppRC integration spec.
    :return: Uppercase ``<APP>_APPRC_TOML`` variable name.
    """
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", app_name).strip("_").upper()
    if not normalized:
        normalized = "APP"
    return f"{normalized}_APPRC_TOML"


def configured_apprc_toml_path(
    *,
    app_name: str,
    apprc_toml_filename: str,
    proc_env: Mapping[str, str] | None = None,
) -> Path:
    """Return the required AppRC TOML path selected by the environment.

    :param app_name: Application name from the AppRC integration spec.
    :param apprc_toml_filename: Suggested TOML basename shown in setup guidance.
    :param proc_env: Environment mapping used for tests and subprocess setup.
    :return: The env-selected AppRC TOML path.
    :raises ApprcTomlEnvError: If the app-specific env var is missing.
    """
    path = optional_apprc_toml_path(
        app_name=app_name,
        proc_env=proc_env,
    )
    if path is not None:
        return path
    raise ApprcTomlEnvError(
        missing_apprc_toml_env_message(
            app_name=app_name,
            apprc_toml_filename=apprc_toml_filename,
        )
    )


def optional_apprc_toml_path(
    *,
    app_name: str,
    proc_env: Mapping[str, str] | None = None,
) -> Path | None:
    """Return the AppRC TOML path when the selector variable is set.

    :param app_name: Application name from the AppRC integration spec.
    :param proc_env: Environment mapping used for tests and subprocess setup.
    :return: The env-selected AppRC TOML path, or ``None``.
    """
    env = os.environ if proc_env is None else proc_env
    raw_path = env.get(apprc_toml_env_key(app_name), "").strip()
    if raw_path:
        return normalized_apprc_toml_path(raw_path)
    return None


def missing_apprc_toml_env_message(
    *,
    app_name: str,
    apprc_toml_filename: str,
) -> str:
    """Return guidance for a missing AppRC TOML env variable.

    :param app_name: Application name from the AppRC integration spec.
    :param apprc_toml_filename: Suggested TOML basename shown in setup guidance.
    :return: Human-facing setup guidance.
    """
    env_key = apprc_toml_env_key(app_name)
    command_name = app_name or "app"
    return (
        f"{env_key} is required and must point to this app's AppRC TOML. "
        "Choose where that file's directory should live, then run:\n"
        f"  {command_name} config setup --yes --apprc-dir "
        "/absolute/path/to/config-dir\n"
        f"Setup will use /absolute/path/to/config-dir/{apprc_toml_filename}. "
        "Keep the variable exported for future commands."
    )


def normalized_apprc_toml_path(path: str | Path) -> Path:
    """Return an absolute, user-expanded AppRC TOML path.

    :param path: User-provided TOML path.
    :return: Absolute path spelling.
    """
    return Path(path).expanduser().resolve()
