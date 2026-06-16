"""Registry environment validation messages.

The AppRC TOML env var is the literal file selector for optional
multi-storage behavior. :mod:`apprc.config.app_spec` derives the env key and
filename; this module owns the registry-specific errors shown when that env
contract is missing or points at unusable state.
"""

from __future__ import annotations

from pathlib import Path

from apprc.config.paths import normalize_apprc_toml_path


class RegistryEnvError(ValueError):
    """Raised when the optional registry env contract is missing or unusable."""


def missing_registry_env_message(
    *,
    apprc_toml_env_key: str,
    apprc_toml_filename: str,
    command_name: str,
) -> str:
    """Return guidance for registry commands without a registry env var.

    :param apprc_toml_env_key: App-specific env var that points at the registry.
    :param apprc_toml_filename: Filename derived from the AppRC TOML contract.
    :param command_name: Executable name shown in setup guidance.
    :return: Human-facing setup instructions.
    """
    return (
        f"{apprc_toml_env_key} is required for multi-storage registry "
        "commands and must point to this app's registry file. Choose this "
        "app's registry directory, then run:\n"
        f"  {command_name} config setup --yes --apprc-dir "
        "/absolute/path/to/config-dir --multi-storage\n"
        "Setup will derive the registry file path:\n"
        f"  /absolute/path/to/config-dir/{apprc_toml_filename}\n"
        "For single-storage runtime commands, export only the storage env var."
    )


def missing_registry_file_message(
    *,
    apprc_toml_env_key: str,
    command_name: str,
    path: str | Path,
) -> str:
    """Return guidance when a configured registry file is missing.

    :param apprc_toml_env_key: App-specific env var that points at the registry.
    :param command_name: Executable name shown in setup guidance.
    :param path: Missing registry file path.
    :return: Human-facing recovery instructions.
    """
    resolved_path = normalize_apprc_toml_path(path)
    return (
        f"{apprc_toml_env_key} points to a missing registry file: "
        f"{resolved_path}. Remove {apprc_toml_env_key} for single-storage "
        "mode, or create the registry with "
        f"{command_name} config setup --yes --multi-storage."
    )
