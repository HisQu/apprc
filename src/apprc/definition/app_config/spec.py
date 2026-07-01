"""Application-level configuration contract."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# == Internal ================================
from apprc.definition.app_config._validation import (
    derive_index_env_key,
    resolve_storage_env_key,
    validate_capability_combination,
)
from apprc.definition.app_config.capabilities import (
    CapabilityState,
    StorageLayerState,
)
from apprc.user_files.app_home.locations import (
    AppConfigHome,
    app_config_file,
    app_config_home,
    ensure_text_file,
    require_config_filename,
    resolve_app_config_home,
)
from apprc.definition.env_config.env import EnvConfig
from apprc.definition.env_config.fields import config_owner_for
from apprc.user_files.app_home._paths import normalize_apprc_toml_path
from apprc.definition.env_config.schema import ConfigOwner
from apprc.definition.env_config._validation import (
    validate_config_owner_inventory,
)
from apprc.user_files.env_files.files import storage_env_path


@dataclass(frozen=True, slots=True, init=False)
class AppConfigSpec:
    """Complete reusable configuration contract for one application.

    Applications declare this once. The spec owns naming rules such as env
    keys, app-wide paths, storage dotenv paths, and named-storage index paths,
    while :class:`AppConfigKit` delegates runtime workflows to focused modules.

    :param app_name: Lowercase application name used in env var derivation.
    :param display_name: Human-readable application name for terminal output.
    :param config_package: Package containing the packaged shared dotenv file.
    :param envs: ``EnvConfig`` classes decorated with ``@env_owner``. AppRC
        derives the normalized owner inventory from these classes.
    :param storage_layer: Whether this app needs an active storage root.
    :param app_wide_layer: Whether the platform config-home dotenv is disabled,
        optionally activated by file presence, or expected by default.
    :param named_storage_layer: Whether the TOML named-storage index is
        disabled, optionally activated by file presence, or expected by default.
    :param storage_env_key: Env key that stores the active storage selector for
        storage-capable constructors.
    :param command_name: Optional executable name shown in generated CLI copy.
    :param index_filename: Per-app named-storage index filename.
    :param shared_env_filename: Packaged shared dotenv filename.
    :param app_wide_env_filename: App-wide dotenv override filename.
    :param storage_env_filename: Storage dotenv override filename.
    """

    app_name: str
    display_name: str
    config_package: str
    owners: tuple[ConfigOwner, ...]
    envs: tuple[type[EnvConfig], ...]
    storage_layer: StorageLayerState
    app_wide_layer: CapabilityState
    named_storage_layer: CapabilityState
    storage_env_key: str | None
    index_filename: str
    command_name: str | None = None
    shared_env_filename: str = ".env.shared"
    app_wide_env_filename: str = ".env.apprc-app"
    storage_env_filename: str = ".env.apprc-storage"

    def __init__(
        self,
        *,
        app_name: str,
        display_name: str,
        config_package: str,
        index_filename: str,
        envs: tuple[type[EnvConfig], ...] = (),
        storage_layer: StorageLayerState | str = StorageLayerState.DISABLED,
        app_wide_layer: CapabilityState | str = CapabilityState.OPTIONAL,
        named_storage_layer: CapabilityState | str = CapabilityState.DISABLED,
        storage_env_key: str | None = None,
        command_name: str | None = None,
        shared_env_filename: str = ".env.shared",
        app_wide_env_filename: str = ".env.apprc-app",
        storage_env_filename: str = ".env.apprc-storage",
    ) -> None:
        """Store one application config contract.

        :param app_name: Lowercase application name used in env var derivation.
        :param display_name: Human-readable application name.
        :param config_package: Package containing the packaged shared dotenv.
        :param index_filename: Per-app named-storage index filename.
        :param envs: ``EnvConfig`` classes decorated with ``@env_owner``.
        :param storage_layer: Whether an active storage root is required.
        :param app_wide_layer: Activation policy for the app-wide dotenv layer.
        :param named_storage_layer: Activation policy for the storage index.
        :param storage_env_key: Env key that stores the active storage selector.
        :param command_name: Optional executable name shown in CLI copy.
        :param shared_env_filename: Packaged shared dotenv filename.
        :param app_wide_env_filename: App-wide dotenv override filename.
        :param storage_env_filename: Storage dotenv override filename.
        """
        resolved_storage_layer = StorageLayerState(storage_layer)
        resolved_app_wide_layer = CapabilityState(app_wide_layer)
        resolved_named_storage_layer = CapabilityState(named_storage_layer)
        validate_capability_combination(
            storage_layer=resolved_storage_layer,
            named_storage_layer=resolved_named_storage_layer,
            storage_env_key=storage_env_key,
        )
        resolved_owners = tuple(config_owner_for(env_cls) for env_cls in envs)
        validate_config_owner_inventory(resolved_owners)
        resolved_storage_env_key = resolve_storage_env_key(
            app_name=app_name,
            storage_env_key=storage_env_key,
            storage_layer=resolved_storage_layer,
        )
        resolved_index_filename = require_config_filename(
            index_filename,
            field_name="index_filename",
        )
        resolved_shared_env_filename = require_config_filename(
            shared_env_filename,
            field_name="shared_env_filename",
        )
        resolved_app_wide_env_filename = require_config_filename(
            app_wide_env_filename,
            field_name="app_wide_env_filename",
        )
        resolved_storage_env_filename = require_config_filename(
            storage_env_filename,
            field_name="storage_env_filename",
        )
        object.__setattr__(self, "app_name", app_name)
        object.__setattr__(self, "display_name", display_name)
        object.__setattr__(self, "config_package", config_package)
        object.__setattr__(self, "owners", resolved_owners)
        object.__setattr__(self, "envs", tuple(envs))
        object.__setattr__(self, "storage_layer", resolved_storage_layer)
        object.__setattr__(self, "app_wide_layer", resolved_app_wide_layer)
        object.__setattr__(
            self,
            "named_storage_layer",
            resolved_named_storage_layer,
        )
        object.__setattr__(self, "storage_env_key", resolved_storage_env_key)
        object.__setattr__(self, "index_filename", resolved_index_filename)
        object.__setattr__(self, "command_name", command_name)
        object.__setattr__(
            self,
            "shared_env_filename",
            resolved_shared_env_filename,
        )
        object.__setattr__(
            self,
            "app_wide_env_filename",
            resolved_app_wide_env_filename,
        )
        object.__setattr__(
            self,
            "storage_env_filename",
            resolved_storage_env_filename,
        )

    def config_command_name(self) -> str:
        """Return the executable name shown in generated config commands."""
        return self.command_name or self.app_name

    @staticmethod
    def derive_index_filename(app_name: str) -> str:
        """Return the conventional named-storage index basename.

        :param app_name: Application name from the AppRC integration spec.
        :return: Host-specific TOML filename ending in ``.apprc.toml``.
        """
        normalized = re.sub(r"[^A-Za-z0-9_-]+", "_", app_name).strip("_-")
        base_name = normalized or "app"
        return f"{base_name}.apprc.toml"

    @property
    def index_env_key(self) -> str:
        """Return the env var that relocates this app's storage index."""
        return derive_index_env_key(self.app_name)

    def storage_required(self) -> bool:
        """Return whether runtime needs an active storage root."""
        return self.storage_layer == StorageLayerState.REQUIRED

    def app_wide_allowed(self) -> bool:
        """Return whether the app-wide dotenv layer may be used."""
        return self.app_wide_layer != CapabilityState.DISABLED

    def app_wide_default(self) -> bool:
        """Return whether the app-wide dotenv layer is expected by default."""
        return self.app_wide_layer == CapabilityState.DEFAULT

    def named_storage_allowed(self) -> bool:
        """Return whether named storage may use the TOML index."""
        return self.named_storage_layer != CapabilityState.DISABLED

    def named_storage_default(self) -> bool:
        """Return whether the named-storage index is expected by default."""
        return self.named_storage_layer == CapabilityState.DEFAULT

    def config_home(self) -> Path:
        """Return the platform-native AppRC config directory for this app."""
        return app_config_home(self.app_name)

    def app_config_file(self, filename: str) -> Path:
        """Return a host-owned config file path below the config home.

        :param filename: File basename owned by the host application.
        :return: Path below this app's platform-native config directory.
        """
        return app_config_file(self.app_name, filename)

    def default_index_path(self) -> Path:
        """Return the conventional named-storage index path for this app."""
        return self.config_home() / self.index_filename

    def app_wide_env_path(self) -> Path:
        """Return the app-wide dotenv override path for this app."""
        return self.config_home() / self.app_wide_env_filename

    def storage_env_path(self, storage_root: Path) -> Path:
        """Return the storage dotenv path for one storage root.

        :param storage_root: Active storage root.
        :return: Dotenv path below ``storage_root``.
        """
        return storage_env_path(
            storage_root, filename=self.storage_env_filename
        )

    def config_paths(
        self,
        proc_env: Mapping[str, str] | None = None,
    ) -> AppConfigHome:
        """Return AppRC-managed paths without creating files.

        :param proc_env: Optional environment mapping for tests and bootstrap.
        :return: Resolved app-wide and index paths.
        """
        return resolve_app_config_home(
            app_name=self.app_name,
            app_wide_env_filename=self.app_wide_env_filename,
            index_filename=self.index_filename,
            index_path=self.index_path(proc_env=proc_env),
        )

    def ensure_app_wide_env(self) -> Path:
        """Create the app-wide dotenv file for an explicit init command.

        :return: Resolved app-wide dotenv path.
        """
        return ensure_text_file(self.app_wide_env_path())

    def ensure_index_file(
        self,
        proc_env: Mapping[str, str] | None = None,
    ) -> Path:
        """Create the named-storage index for an explicit storage command.

        :param proc_env: Optional environment mapping for tests.
        :return: Resolved named-storage index path.
        """
        return ensure_text_file(self.index_path(proc_env=proc_env))

    def required_index_path(
        self,
        proc_env: Mapping[str, str] | None = None,
    ) -> Path:
        """Return the configured named-storage index path.

        :param proc_env: Optional environment mapping for tests.
        :return: Override or default index path for this application.
        """
        return self.index_path(proc_env=proc_env)

    def optional_index_path(
        self,
        proc_env: Mapping[str, str] | None = None,
    ) -> Path:
        """Return the configured named-storage index path.

        :param proc_env: Optional environment mapping for tests.
        :return: Override or default index path.
        """
        return self.index_path(proc_env=proc_env)

    def index_path(
        self,
        proc_env: Mapping[str, str] | None = None,
    ) -> Path:
        """Return the override or default named-storage index path.

        :param proc_env: Optional environment mapping for tests.
        :return: Index path selected by env or config-home convention.
        """
        env = os.environ if proc_env is None else proc_env
        raw_path = env.get(self.index_env_key, "").strip()
        if raw_path:
            return normalize_apprc_toml_path(raw_path)
        return self.default_index_path()

    def require_storage_env_key(self) -> str:
        """Return the storage env key or raise for storage-free apps.

        :return: Storage selector env key.
        :raises ValueError: If storage is disabled for this app.
        """
        if self.storage_env_key is None:
            raise ValueError(f"{self.display_name} does not use AppRC storage.")
        return self.storage_env_key
