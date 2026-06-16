"""Application-level configuration contract."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# == Internal ================================
from apprc.config.apprc_toml import (
    apprc_toml_env_key,
    apprc_toml_path,
    optional_apprc_toml_path,
)
from apprc.config.schema import ConfigOwner


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
    :param apprc_toml_filename: Per-user AppRC TOML filename.
    :param shared_env_filename: Packaged shared dotenv filename.
    :param local_env_filename: Storage-local dotenv override filename.
    """

    app_name: str
    display_name: str
    config_package: str
    owners: tuple[ConfigOwner, ...]
    storage_env_key: str
    command_name: str | None = None
    apprc_toml_filename: str = "app.apprc.toml"
    shared_env_filename: str = ".env.shared"
    local_env_filename: str = ".env.local"

    def config_command_name(self) -> str:
        """Return the executable name shown in generated config commands."""
        return self.command_name or self.app_name

    def apprc_toml_env_key(self) -> str:
        """Return the env var that selects this app's AppRC TOML."""
        return apprc_toml_env_key(self.app_name)

    def apprc_toml_path(
        self,
        proc_env: Mapping[str, str] | None = None,
    ) -> Path:
        """Return the configured multi-storage AppRC TOML path.

        :param proc_env: Optional environment mapping for tests.
        :return: Env-selected AppRC TOML path for this application.
        """
        return apprc_toml_path(
            app_name=self.app_name,
            apprc_toml_filename=self.apprc_toml_filename,
            proc_env=proc_env,
        )

    def optional_apprc_toml_path(
        self,
        proc_env: Mapping[str, str] | None = None,
    ) -> Path | None:
        """Return the AppRC TOML path when multi-storage is configured.

        :param proc_env: Optional environment mapping for tests.
        :return: Env-selected AppRC TOML path, or ``None``.
        """
        return optional_apprc_toml_path(
            app_name=self.app_name,
            proc_env=proc_env,
        )
