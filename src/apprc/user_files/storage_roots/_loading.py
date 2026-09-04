"""Load named-storage registries from the fixed AppRC TOML path."""

from __future__ import annotations

# == Standard Library ===========================================
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# == Internal ===================================================
from apprc.definition.app_config.spec import AppConfigSpec
from apprc.user_files.app_home.locations import AppRCDirectoryError
from apprc.user_files.storage_roots.registry import (
    StorageRegistry,
    load_storage_registry_or_empty,
)
from apprc.user_files.storage_roots.paths import resolve_storage_root_path


class MissingStorageRegistryError(ValueError):
    """A storage-capable application has no ``apprc.toml`` file."""


@dataclass(frozen=True, slots=True)
class StorageRegistryInspection:
    """Storage TOML state discovered without filesystem writes.

    :param path: Fixed ``apprc.toml`` path.
    :param env_value: Active ``<APP>_APPRC_DIR`` override, if any.
    :param exists: Whether the TOML file exists.
    :param error: Read or schema error.
    :param registry: Parsed registry when valid.
    :param storage_count: Number of live records.
    :param issues: Runtime-blocking findings.
    :param warnings: Non-blocking findings.
    """

    path: Path
    env_value: str | None
    exists: bool
    error: str | None
    registry: StorageRegistry | None
    storage_count: int
    issues: list[str]
    warnings: list[str]

    @property
    def parse_ok(self) -> bool:
        """Return whether an existing AppRC TOML parsed successfully."""
        return self.error is None


def apprc_toml_path_for_create(
    spec: AppConfigSpec,
    *,
    proc_env: Mapping[str, str] | None = None,
) -> Path:
    """Return the fixed AppRC TOML path for a storage write.

    :param spec: Application declaration.
    :param proc_env: Optional environment mapping for directory selection.
    :return: ``<apprc-dir>/apprc.toml``.
    """
    spec.require_storage()
    return spec.preferred_apprc_toml_path(proc_env)


def load_create_or_empty_storage_registry(path: Path) -> StorageRegistry:
    """Read an existing registry or return an empty one for writes.

    :param path: AppRC TOML path that may not exist yet.
    :return: Parsed or empty storage registry.
    """
    try:
        return load_storage_registry_or_empty(path)
    except OSError as exc:
        raise _apprc_toml_read_error(path, exc) from exc


def load_existing_storage_registry(
    spec: AppConfigSpec,
    *,
    proc_env: Mapping[str, str] | None = None,
    config_group_name: str = "config",
) -> StorageRegistry:
    """Read the required registry for a storage-capable application.

    :param spec: Application declaration.
    :param proc_env: Optional environment mapping for directory selection.
    :param config_group_name: Mounted config command name for guidance.
    :return: Parsed registry.
    :raises MissingStorageRegistryError: If the registry is missing.
    """
    spec.require_storage()
    path = spec.preferred_apprc_toml_path(proc_env)
    if not path.is_file():
        raise MissingStorageRegistryError(
            f"Storage registry does not exist: {path}. Create it with `"
            f"{spec.config_command_name()} {config_group_name} setup` or `"
            f"{spec.config_command_name()} {config_group_name} storage add "
            "NAME ROOT`."
        )
    return load_create_or_empty_storage_registry(path)


def load_optional_runtime_storage_registry(
    spec: AppConfigSpec,
    *,
    proc_env: Mapping[str, str] | None = None,
) -> StorageRegistry | None:
    """Read the registry when storage is supported and the file exists.

    :param spec: Application declaration.
    :param proc_env: Optional environment mapping for directory selection.
    :return: Parsed registry, or ``None`` when absent or unsupported.
    """
    if not spec.uses_storage():
        return None
    path = spec.preferred_apprc_toml_path(proc_env)
    if not path.is_file():
        return None
    return load_create_or_empty_storage_registry(path)


def load_runtime_storage_registry_for_selector(
    spec: AppConfigSpec,
    *,
    raw_selector: str,
    proc_env: Mapping[str, str] | None = None,
) -> StorageRegistry | None:
    """Read the registry required to resolve a selector name.

    :param spec: Application declaration.
    :param raw_selector: Selector name; retained for call-site clarity.
    :param proc_env: Optional environment mapping for directory selection.
    :return: Parsed registry, or ``None`` when the file is absent.
    """
    del raw_selector
    return load_optional_runtime_storage_registry(spec, proc_env=proc_env)


def inspect_storage_registry(
    spec: AppConfigSpec,
    *,
    raw_selector: str | None = None,
    proc_env: Mapping[str, str] | None = None,
) -> StorageRegistryInspection:
    """Inspect AppRC TOML state without creating or modifying files.

    :param spec: Application declaration.
    :param raw_selector: Runtime selector, when diagnostics has one.
    :param proc_env: Optional environment mapping for directory selection.
    :return: Registry diagnosis.
    """
    del raw_selector
    env = os.environ if proc_env is None else proc_env
    path = spec.preferred_apprc_toml_path(proc_env)
    exists = path.is_file()
    directory_override = env.get(spec.apprc_dir_env_key, "").strip() or None

    if not spec.uses_storage():
        warnings = (
            [
                "Stale storage configuration is ignored because Python code "
                f"does not declare storage support: {path}"
            ]
            if exists
            else []
        )
        return StorageRegistryInspection(
            path=path,
            env_value=directory_override,
            exists=exists,
            error=None,
            registry=None,
            storage_count=0,
            issues=[],
            warnings=warnings,
        )

    if not exists:
        return StorageRegistryInspection(
            path=path,
            env_value=directory_override,
            exists=False,
            error=None,
            registry=None,
            storage_count=0,
            issues=[f"Storage registry does not exist: {path}"],
            warnings=[],
        )

    try:
        registry = load_storage_registry_or_empty(path)
    except (OSError, ValueError) as exc:
        message = f"AppRC TOML is invalid: {exc}"
        return StorageRegistryInspection(
            path=path,
            env_value=directory_override,
            exists=True,
            error=str(exc),
            registry=None,
            storage_count=0,
            issues=[message],
            warnings=[],
        )

    return StorageRegistryInspection(
        path=path,
        env_value=directory_override,
        exists=True,
        error=None,
        registry=registry,
        storage_count=len(registry.storages),
        issues=[],
        warnings=_duplicate_storage_root_warnings(registry),
    )


def _duplicate_storage_root_warnings(
    registry: StorageRegistry,
) -> list[str]:
    """Return warnings for ambiguous aliases retained from older registries.

    :param registry: Parsed storage registry.
    :return: One warning per root owned by multiple names.
    """
    names_by_root: dict[Path, list[str]] = {}
    for name, record in registry.storages.items():
        root = resolve_storage_root_path(
            record.root,
            base=registry.path.parent,
        )
        names_by_root.setdefault(root, []).append(name)
    return [
        "Duplicate storage root is registered under multiple names "
        f"({', '.join(sorted(names))}): {root}. Repoint or remove an alias."
        for root, names in sorted(
            names_by_root.items(), key=lambda item: item[0]
        )
        if len(names) > 1
    ]


def _apprc_toml_read_error(path: Path, exc: OSError) -> AppRCDirectoryError:
    """Return a domain error for an unreadable registry.

    :param path: Registry path that could not be read.
    :param exc: Filesystem failure.
    :return: Error suitable for CLI adapters.
    """
    return AppRCDirectoryError(
        f"AppRC-managed file could not be read: {Path(path).expanduser()}: {exc}"
    )
