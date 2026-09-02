"""AppRC TOML environment validation messages.

The ``<APP>_APPRC_TOML`` env var relocates the optional storage registry.
:mod:`apprc.definition.app_config.spec` derives the env key and filename; this
module owns the errors shown when that env contract points at unusable state.
"""

from __future__ import annotations

from pathlib import Path

from apprc.user_files.app_home._paths import normalize_apprc_toml_path


class ApprcTomlEnvError(ValueError):
    """Raised when the optional AppRC TOML env contract is unusable."""


def missing_apprc_toml_env_message(
    *,
    apprc_toml_env_key: str,
    apprc_toml_filename: str,
    command_name: str,
    config_group_name: str = "config",
) -> str:
    """Return guidance when no AppRC TOML relocation is configured.

    :param apprc_toml_env_key: App-specific env var that relocates AppRC TOML.
    :param apprc_toml_filename: Filename from the application declaration.
    :param command_name: Executable name shown in setup guidance.
    :param config_group_name: Config command group name shown in setup
        guidance.
    :return: Human-facing setup instructions.
    """
    return (
        f"{apprc_toml_env_key} is optional. Set it only to relocate the "
        "AppRC TOML file from the platform config home default:\n"
        f"  <config-home>/{apprc_toml_filename}\n"
        "Create named storage entries with:\n"
        f"  {command_name} {config_group_name} storage add NAME "
        "/absolute/path/to/storage"
    )


def missing_apprc_toml_file_message(
    *,
    apprc_toml_env_key: str,
    command_name: str,
    config_group_name: str = "config",
    path: str | Path,
) -> str:
    """Return guidance when configured AppRC TOML is missing.

    :param apprc_toml_env_key: App-specific env var that relocates AppRC TOML.
    :param command_name: Executable name shown in setup guidance.
    :param config_group_name: Config command group name shown in setup
        guidance.
    :param path: Missing AppRC TOML path.
    :return: Human-facing recovery instructions.
    """
    resolved_path = normalize_apprc_toml_path(path)
    return (
        f"{apprc_toml_env_key} points to missing AppRC TOML: "
        f"{resolved_path}. Remove {apprc_toml_env_key} to use the default "
        "path, or create a storage entry with "
        f"{command_name} {config_group_name} storage add NAME "
        "/absolute/path/to/storage."
    )
