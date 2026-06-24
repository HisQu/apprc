"""Application-level configuration contract."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# == Internal ================================
from apprc.runtime_config.contract.paths import normalize_apprc_toml_path
from apprc.runtime_config.contract.apprc_toml_env import (
    ApprcTomlEnvError,
    missing_apprc_toml_env_message,
)
from apprc.runtime_config.fields.env_authoring import config_owner_for
from apprc.runtime_config.fields.env_config import EnvConfig
from apprc.runtime_config.contract.schema import ConfigOwner
from apprc.runtime_config.contract.schema_validation import (
    validate_config_owner_inventory,
)


@dataclass(frozen=True, slots=True, init=False)
class AppConfigSpec:
    """Complete reusable configuration contract for one application.

    Applications declare this once. The spec owns naming rules such as env
    keys and AppRC TOML paths, while :class:`AppConfigKit` delegates runtime
    workflows to the focused config modules.

    :param app_name: Lowercase application name used in env var derivation.
    :param display_name: Human-readable application name for terminal output.
    :param config_package: Package containing the packaged shared dotenv file.
    :param envs: ``EnvConfig`` classes decorated with ``@env_owner``. AppRC
        derives the normalized owner inventory from these classes.
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
    envs: tuple[type[EnvConfig], ...]
    storage_env_key: str
    apprc_toml_filename: str
    command_name: str | None = None
    shared_env_filename: str = ".env.shared"
    local_env_filename: str = ".env.local"

    def __init__(
        self,
        *,
        app_name: str,
        display_name: str,
        config_package: str,
        storage_env_key: str,
        apprc_toml_filename: str,
        envs: tuple[type[EnvConfig], ...] = (),
        command_name: str | None = None,
        shared_env_filename: str = ".env.shared",
        local_env_filename: str = ".env.local",
    ) -> None:
        """Store one application config contract.

        :param app_name: Lowercase application name used in env var derivation.
        :param display_name: Human-readable application name.
        :param config_package: Package containing the packaged shared dotenv.
        :param storage_env_key: Env key that stores the active storage selector.
        :param apprc_toml_filename: Per-user AppRC TOML filename.
        :param envs: ``EnvConfig`` classes decorated with ``@env_owner``.
        :param command_name: Optional executable name shown in CLI copy.
        :param shared_env_filename: Packaged shared dotenv filename.
        :param local_env_filename: Storage-local dotenv override filename.
        """
        resolved_owners = tuple(config_owner_for(env_cls) for env_cls in envs)
        validate_config_owner_inventory(resolved_owners)
        object.__setattr__(self, "app_name", app_name)
        object.__setattr__(self, "display_name", display_name)
        object.__setattr__(self, "config_package", config_package)
        object.__setattr__(self, "owners", resolved_owners)
        object.__setattr__(self, "envs", tuple(envs))
        object.__setattr__(self, "storage_env_key", storage_env_key)
        object.__setattr__(self, "apprc_toml_filename", apprc_toml_filename)
        object.__setattr__(self, "command_name", command_name)
        object.__setattr__(self, "shared_env_filename", shared_env_filename)
        object.__setattr__(self, "local_env_filename", local_env_filename)

    def config_command_name(self) -> str:
        """Return the executable name shown in generated config commands."""
        return self.command_name or self.app_name

    @staticmethod
    def derive_apprc_toml_filename(app_name: str) -> str:
        """Return the conventional AppRC TOML basename for one application.

        :param app_name: Application name from the AppRC integration spec.
        :return: Host-specific TOML filename ending in ``.apprc.toml``.
        """
        normalized = re.sub(r"[^A-Za-z0-9_-]+", "_", app_name).strip("_-")
        base_name = normalized or "app"
        return f"{base_name}.apprc.toml"

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
        raise ApprcTomlEnvError(
            missing_apprc_toml_env_message(
                apprc_toml_env_key=self.apprc_toml_env_key,
                apprc_toml_filename=self.apprc_toml_filename,
                command_name=self.config_command_name(),
            )
        )

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


def _apprc_toml_env_key(app_name: str) -> str:
    """Return the environment variable that selects the AppRC TOML."""
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", app_name).strip("_").upper()
    if not normalized:
        normalized = "APP"
    return f"{normalized}_APPRC_TOML"
