"""Load AppRC storage registries by explicit intent."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from apprc.config.app_spec import AppConfigSpec
from apprc.config.registry_env import (
    RegistryEnvError,
    missing_registry_file_message,
)
from apprc.config.storage.registry import (
    StorageRegistry,
    load_storage_registry_or_empty,
)


@dataclass(frozen=True, slots=True)
class RegistryInspection:
    """Registry state discovered without raising on missing or invalid files."""

    path: Path | None
    env_value: str | None
    exists: bool
    error: str | None
    registry: StorageRegistry | None
    storage_count: int
    issues: list[str]

    @property
    def parse_ok(self) -> bool:
        """Return whether the optional registry is absent or parseable."""
        if self.path is None:
            return True
        return self.exists and self.error is None


def registry_path_for_create(spec: AppConfigSpec) -> Path:
    """Return the configured registry path for setup/init write flows.

    Missing files are valid for this intent because the caller is about to
    create or update the registry.

    :param spec: Application-specific config contract.
    :return: Env-selected registry path.
    :raises RegistryEnvError: If the registry env var is missing.
    """
    return spec.required_apprc_toml_path()


def load_create_or_empty_registry(path: Path) -> StorageRegistry:
    """Read an existing registry or return an empty one for write flows.

    :param path: Registry file path that may not exist yet.
    :return: Parsed or empty registry.
    :raises ValueError: If an existing registry cannot be parsed.
    """
    return load_storage_registry_or_empty(path)


def load_existing_registry(spec: AppConfigSpec) -> StorageRegistry:
    """Read a configured registry that must already exist.

    :param spec: Application-specific config contract.
    :return: Parsed storage registry.
    :raises RegistryEnvError: If the env var is missing or points at a missing
        file.
    :raises ValueError: If the registry cannot be parsed.
    """
    registry_path = spec.required_apprc_toml_path()
    if not registry_path.is_file():
        raise RegistryEnvError(
            missing_registry_file_message(
                apprc_toml_env_key=spec.apprc_toml_env_key,
                command_name=spec.config_command_name(),
                path=registry_path,
            )
        )
    return load_storage_registry_or_empty(registry_path)


def load_optional_runtime_registry(
    spec: AppConfigSpec,
) -> StorageRegistry | None:
    """Read the registry only when runtime multi-storage mode is enabled.

    :param spec: Application-specific config contract.
    :return: Parsed registry, or ``None`` in single-storage mode.
    :raises RegistryEnvError: If the env var points at a missing file.
    :raises ValueError: If the registry cannot be parsed.
    """
    if spec.optional_apprc_toml_path() is None:
        return None
    return load_existing_registry(spec)


def inspect_registry(spec: AppConfigSpec) -> RegistryInspection:
    """Inspect optional registry state for diagnostics without raising.

    :param spec: Application-specific config contract.
    :return: Registry diagnosis for ``config doctor``.
    """
    raw_registry_env_value = os.environ.get(spec.apprc_toml_env_key, "").strip()
    registry_path = spec.optional_apprc_toml_path()
    if registry_path is None:
        return RegistryInspection(
            path=None,
            env_value=raw_registry_env_value or None,
            exists=False,
            error=None,
            registry=None,
            storage_count=0,
            issues=[],
        )

    registry_exists = registry_path.is_file()
    if not registry_exists:
        return RegistryInspection(
            path=registry_path,
            env_value=raw_registry_env_value or None,
            exists=False,
            error=None,
            registry=None,
            storage_count=0,
            issues=[f"Registry file does not exist: {registry_path}"],
        )

    try:
        registry = load_storage_registry_or_empty(registry_path)
    except ValueError as exc:
        registry_error = str(exc)
        return RegistryInspection(
            path=registry_path,
            env_value=raw_registry_env_value or None,
            exists=True,
            error=registry_error,
            registry=None,
            storage_count=0,
            issues=[f"Registry file is invalid: {registry_error}"],
        )

    return RegistryInspection(
        path=registry_path,
        env_value=raw_registry_env_value or None,
        exists=True,
        error=None,
        registry=registry,
        storage_count=len(registry.storages),
        issues=[],
    )
