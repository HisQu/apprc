"""AppRC TOML environment validation messages.

The AppRC TOML env var is the literal file selector for optional
multi-storage behavior. :mod:`apprc.runtime_config.contract.app_spec` derives the env key and
filename; this module owns the errors shown when that env contract is missing
or points at unusable state.
"""

from __future__ import annotations

from pathlib import Path

from apprc.runtime_config.contract.paths import normalize_apprc_toml_path


class ApprcTomlEnvError(ValueError):
    """Raised when the optional AppRC TOML env contract is unusable."""


def missing_apprc_toml_env_message(
    *,
    apprc_toml_env_key: str,
    apprc_toml_filename: str,
    command_name: str,
) -> str:
    """Return guidance for multi-storage commands without an AppRC TOML env var.

    :param apprc_toml_env_key: App-specific env var that points at the TOML.
    :param apprc_toml_filename: Filename derived from the AppRC TOML contract.
    :param command_name: Executable name shown in setup guidance.
    :return: Human-facing setup instructions.
    """
    return (
        f"{apprc_toml_env_key} is required for multi-storage commands and "
        "must point to this app's AppRC TOML file. Choose this app's AppRC "
        "directory, then run:\n"
        f"  {command_name} config setup --yes --apprc-dir "
        "/absolute/path/to/config-dir --multi-storage\n"
        "Setup will derive the AppRC TOML path:\n"
        f"  /absolute/path/to/config-dir/{apprc_toml_filename}\n"
        "For single-storage runtime commands, export only the storage env var."
    )


def missing_apprc_toml_file_message(
    *,
    apprc_toml_env_key: str,
    command_name: str,
    path: str | Path,
) -> str:
    """Return guidance when a configured AppRC TOML file is missing.

    :param apprc_toml_env_key: App-specific env var that points at the TOML.
    :param command_name: Executable name shown in setup guidance.
    :param path: Missing AppRC TOML path.
    :return: Human-facing recovery instructions.
    """
    resolved_path = normalize_apprc_toml_path(path)
    return (
        f"{apprc_toml_env_key} points to a missing AppRC TOML file: "
        f"{resolved_path}. Remove {apprc_toml_env_key} for single-storage "
        "mode, or create it with "
        f"{command_name} config setup --yes --multi-storage."
    )
