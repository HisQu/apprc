"""Load AppRC storage registries by explicit intent."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from apprc.runtime_config.app_spec import AppConfigSpec, StorageMode
from apprc.runtime_config.contract.apprc_toml_env import (
    ApprcTomlEnvError,
    missing_apprc_toml_file_message,
)
from apprc.runtime_config.storage.registry import (
    StorageRegistry,
    load_storage_registry_or_empty,
)


@dataclass(frozen=True, slots=True)
class StorageRegistryInspection:
    """Storage table state discovered without raising on file problems."""

    path: Path | None
    env_value: str | None
    exists: bool
    error: str | None
    registry: StorageRegistry | None
    storage_count: int
    issues: list[str]
    parse_ok_override: bool | None = None

    @property
    def parse_ok(self) -> bool:
        """Return whether the optional AppRC TOML is absent or parseable."""
        if self.parse_ok_override is not None:
            return self.parse_ok_override
        if self.path is None:
            return True
        return self.exists and self.error is None


def apprc_toml_path_for_create(spec: AppConfigSpec) -> Path:
    """Return the configured AppRC TOML path for setup/init write flows.

    Missing files are valid for this intent because the caller is about to
    create or update the storage table.

    :param spec: Application-specific config contract.
    :return: Override or default AppRC TOML path.
    """
    return spec.apprc_toml_path()


def load_create_or_empty_storage_registry(path: Path) -> StorageRegistry:
    """Read an existing storage table or return an empty one for write flows.

    :param path: AppRC TOML path that may not exist yet.
    :return: Parsed or empty storage table.
    :raises ValueError: If an existing AppRC TOML cannot be parsed.
    """
    return load_storage_registry_or_empty(path)


def load_existing_storage_registry(
    spec: AppConfigSpec,
    *,
    proc_env: Mapping[str, str] | None = None,
) -> StorageRegistry:
    """Read a configured storage table that must already exist.

    :param spec: Application-specific config contract.
    :param proc_env: Optional environment mapping for bootstrap-time selection.
    :return: Parsed storage table.
    :raises ApprcTomlEnvError: If the AppRC TOML file is missing.
    :raises ValueError: If the AppRC TOML cannot be parsed.
    """
    apprc_toml_path = spec.apprc_toml_path(proc_env=proc_env)
    if not apprc_toml_path.is_file():
        raise ApprcTomlEnvError(
            missing_apprc_toml_file_message(
                apprc_toml_env_key=spec.apprc_toml_env_key,
                command_name=spec.config_command_name(),
                path=apprc_toml_path,
            )
        )
    return load_storage_registry_or_empty(apprc_toml_path)


def load_optional_runtime_storage_registry(
    spec: AppConfigSpec,
    *,
    proc_env: Mapping[str, str] | None = None,
) -> StorageRegistry | None:
    """Read the storage table only when the app uses storage.

    :param spec: Application-specific config contract.
    :param proc_env: Optional environment mapping for bootstrap-time selection.
    :return: Parsed storage table, or ``None`` when storage is disabled.
    :raises ApprcTomlEnvError: If the AppRC TOML file is missing.
    :raises ValueError: If the AppRC TOML cannot be parsed.
    """
    if spec.storage_mode == StorageMode.DISABLED:
        return None
    return load_existing_storage_registry(spec, proc_env=proc_env)


def inspect_storage_registry(spec: AppConfigSpec) -> StorageRegistryInspection:
    """Inspect optional AppRC TOML state for diagnostics without raising.

    :param spec: Application-specific config contract.
    :return: AppRC TOML and storage-table diagnosis for ``config doctor``.
    """
    raw_apprc_toml_env_value = os.environ.get(
        spec.apprc_toml_env_key, ""
    ).strip()
    apprc_toml_path = spec.apprc_toml_path()
    apprc_toml_exists = apprc_toml_path.is_file()
    if not apprc_toml_exists:
        return StorageRegistryInspection(
            path=apprc_toml_path,
            env_value=raw_apprc_toml_env_value or None,
            exists=False,
            error=None,
            registry=None,
            storage_count=0,
            issues=[f"AppRC TOML file does not exist: {apprc_toml_path}"],
        )

    try:
        registry = load_storage_registry_or_empty(apprc_toml_path)
    except ValueError as exc:
        apprc_toml_error = str(exc)
        return StorageRegistryInspection(
            path=apprc_toml_path,
            env_value=raw_apprc_toml_env_value or None,
            exists=True,
            error=apprc_toml_error,
            registry=None,
            storage_count=0,
            issues=[f"AppRC TOML file is invalid: {apprc_toml_error}"],
        )

    return StorageRegistryInspection(
        path=apprc_toml_path,
        env_value=raw_apprc_toml_env_value or None,
        exists=True,
        error=None,
        registry=registry,
        storage_count=len(registry.storages),
        issues=[],
    )
