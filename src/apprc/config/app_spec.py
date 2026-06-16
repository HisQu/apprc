"""Application-level configuration contract."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# == Internal ================================
from apprc.config.paths import normalize_apprc_toml_path
from apprc.config.schema import ConfigOwner


class ApprcTomlEnvError(ValueError):
    """Raised when an app's AppRC TOML path cannot be resolved from the env."""


@dataclass(frozen=True, slots=True)
class AppConfigSpec:
    """Complete reusable configuration contract for one application.

    Applications declare this once. The spec owns naming rules such as env
    keys and AppRC TOML paths, while :class:`AppConfigKit` delegates runtime
    workflows to the focused config modules.

    :param app_name: Lowercase application name used in env var derivation.
    :param display_name: Human-readable application name for terminal output.
    :param config_package: Package containing the packaged shared dotenv file.
    :param owners: Config owner inventory for editable and documented fields.
    :param storage_env_key: Env key that stores the active storage selector.
    :param command_name: Optional executable name shown in generated CLI copy.
    :param apprc_toml_filename: Per-user AppRC TOML filename. Empty values use
        the host-specific ``<app>.apprc.toml`` default.
    :param shared_env_filename: Packaged shared dotenv filename.
    :param local_env_filename: Storage-local dotenv override filename.
    """

    app_name: str
    display_name: str
    config_package: str
    owners: tuple[ConfigOwner, ...]
    storage_env_key: str
    command_name: str | None = None
    apprc_toml_filename: str = ""
    shared_env_filename: str = ".env.shared"
    local_env_filename: str = ".env.local"

    def __post_init__(self) -> None:
        """Fill derived app-specific defaults after dataclass initialization."""
        if not self.apprc_toml_filename:
            object.__setattr__(
                self,
                "apprc_toml_filename",
                _derive_apprc_toml_filename(self.app_name),
            )

    def config_command_name(self) -> str:
        """Return the executable name shown in generated config commands."""
        return self.command_name or self.app_name

    @property
    def apprc_toml_env_key(self) -> str:
        """Return the env var that selects this app's AppRC TOML."""
        return _apprc_toml_env_key(self.app_name)

    def required_apprc_toml_path(
        self,
        proc_env: Mapping[str, str] | None = None,
    ) -> Path:
        """Return the configured multi-storage AppRC TOML path.

        :param proc_env: Optional environment mapping for tests.
        :return: Env-selected AppRC TOML path for this application.
        """
        path = self.optional_apprc_toml_path(proc_env=proc_env)
        if path is not None:
            return path
        raise ApprcTomlEnvError(self._missing_apprc_toml_env_message())

    def optional_apprc_toml_path(
        self,
        proc_env: Mapping[str, str] | None = None,
    ) -> Path | None:
        """Return the AppRC TOML path when multi-storage is configured.

        :param proc_env: Optional environment mapping for tests.
        :return: Env-selected AppRC TOML path, or ``None``.
        """
        env = os.environ if proc_env is None else proc_env
        raw_path = env.get(self.apprc_toml_env_key, "").strip()
        if raw_path:
            return normalize_apprc_toml_path(raw_path)
        return None

    def missing_apprc_toml_file_message(self, path: str | Path) -> str:
        """Return guidance when configured multi-storage state is missing.

        :param path: Missing AppRC TOML path.
        :return: Human-facing setup guidance.
        """
        resolved_path = normalize_apprc_toml_path(path)
        return (
            f"{self.apprc_toml_env_key} points to a missing AppRC TOML: "
            f"{resolved_path}. Remove {self.apprc_toml_env_key} for "
            "single-storage mode, or create the registry with "
            f"{self.config_command_name()} config setup --yes --multi-storage."
        )

    def _missing_apprc_toml_env_message(self) -> str:
        """Return guidance for registry commands without a TOML env var."""
        return (
            f"{self.apprc_toml_env_key} is required for multi-storage registry "
            "commands and must point to this app's AppRC TOML. Choose this "
            "app's directory (AppRC), then run:\n"
            f"  {self.config_command_name()} config setup --yes --apprc-dir "
            "/absolute/path/to/config-dir --multi-storage\n"
            "Setup will derive the AppRC TOML path:\n"
            f"  /absolute/path/to/config-dir/{self.apprc_toml_filename}\n"
            "For single-storage runtime commands, export only the storage env "
            "var."
        )


def _derive_apprc_toml_filename(app_name: str) -> str:
    """Return the conventional AppRC TOML basename for one application."""
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "_", app_name).strip("_-")
    base_name = normalized or "app"
    return f"{base_name}.apprc.toml"


def _apprc_toml_env_key(app_name: str) -> str:
    """Return the environment variable that selects the AppRC TOML."""
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", app_name).strip("_").upper()
    if not normalized:
        normalized = "APP"
    return f"{normalized}_APPRC_TOML"
