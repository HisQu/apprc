"""Application-level configuration contract."""

from __future__ import annotations

# == Standard Library ========================
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

# == Internal ================================
from apprc.config.environment import EnvBootstrapSpec
from apprc.config.schema import ConfigOwner
from apprc.config.storage_registry import (
    config_file_env_key,
    configured_storage_registry_path,
    default_storage_registry_path,
)


@dataclass(frozen=True, slots=True)
class AppConfigSpec:
    """Complete reusable configuration contract for one application.

    Applications declare this once, then :class:`AppConfigKit` derives the
    storage registry path, dotenv bootstrap spec, local-env behavior, config
    doctor diagnostics, and optional config CLI from it.

    :param app_name: Lowercase application name used below ``~/.config``.
    :param display_name: Human-readable application name for terminal output.
    :param config_package: Package containing the packaged shared dotenv file.
    :param owners: Config owner inventory for editable and documented fields.
    :param storage_root_env_key: Env key that stores the active storage root.
    :param registry_filename: Per-user TOML registry filename.
    :param shared_env_filename: Packaged shared dotenv filename.
    :param local_env_filename: Storage-local dotenv override filename.
    """

    app_name: str
    display_name: str
    config_package: str
    owners: tuple[ConfigOwner, ...]
    storage_root_env_key: str
    registry_filename: str = "app.toml"
    shared_env_filename: str = ".env.shared"
    local_env_filename: str = ".env.local"

    def config_file_env_key(self) -> str:
        """Return the env var that overrides the registry file path."""
        return config_file_env_key(self.app_name)

    def default_registry_path(
        self,
        proc_env: Mapping[str, str] | None = None,
    ) -> Path:
        """Return the default user storage registry path.

        :param proc_env: Optional environment mapping for tests.
        :return: ``$XDG_CONFIG_HOME/<app>/<registry_filename>`` or the
            ``~/.config`` fallback.
        """
        return default_storage_registry_path(
            app_name=self.app_name,
            registry_filename=self.registry_filename,
            proc_env=proc_env,
        )

    def registry_path(
        self,
        proc_env: Mapping[str, str] | None = None,
    ) -> Path:
        """Return the active user storage registry path.

        :param proc_env: Optional environment mapping for tests.
        :return: ``<APP>_CONFIG_FILE`` when set, otherwise the default path.
        """
        return configured_storage_registry_path(
            app_name=self.app_name,
            registry_filename=self.registry_filename,
            proc_env=proc_env,
        )

    def env_bootstrap_spec(self) -> EnvBootstrapSpec:
        """Return the narrower dotenv bootstrap contract."""
        return EnvBootstrapSpec(
            app_name=self.app_name,
            display_name=self.display_name,
            config_package=self.config_package,
            storage_root_env_key=self.storage_root_env_key,
            registry_filename=self.registry_filename,
            shared_env_filename=self.shared_env_filename,
            local_env_filename=self.local_env_filename,
        )
