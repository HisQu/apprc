"""Load optional named-storage indexes by explicit intent."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from apprc.runtime_config.app_spec import AppConfigSpec
from apprc.runtime_config.config_home import ConfigHomeError
from apprc.runtime_config.contract.apprc_toml_env import ApprcTomlEnvError
from apprc.runtime_config.storage.registry import (
    StorageRegistry,
    load_storage_registry_or_empty,
)
from apprc.runtime_config.storage.selector import storage_selector_is_path_like


@dataclass(frozen=True, slots=True)
class StorageRegistryInspection:
    """Named-storage index state discovered without creating files."""

    path: Path | None
    env_value: str | None
    exists: bool
    error: str | None
    registry: StorageRegistry | None
    storage_count: int
    issues: list[str]
    warnings: list[str]

    @property
    def parse_ok(self) -> bool:
        """Return whether the index was readable and parseable."""
        return self.error is None


def index_path_for_create(
    spec: AppConfigSpec,
    *,
    proc_env: Mapping[str, str] | None = None,
) -> Path:
    """Return the configured named-storage index path for write flows.

    Missing files are valid for this intent because the caller is about to
    create or update the storage table.

    :param spec: Application-specific config contract.
    :param proc_env: Optional environment mapping for bootstrap-time selection.
    :return: Override or default named-storage index path.
    """
    return spec.index_path(proc_env=proc_env)


def load_create_or_empty_storage_registry(path: Path) -> StorageRegistry:
    """Read an existing storage table or return an empty one for write flows.

    :param path: Named-storage index path that may not exist yet.
    :return: Parsed or empty storage table.
    :raises ValueError: If an existing index cannot be parsed.
    """
    try:
        return load_storage_registry_or_empty(path)
    except OSError as exc:
        raise _index_read_error(path, exc) from exc


def load_existing_storage_registry(
    spec: AppConfigSpec,
    *,
    proc_env: Mapping[str, str] | None = None,
) -> StorageRegistry:
    """Read a named-storage index that must already exist.

    :param spec: Application-specific config contract.
    :param proc_env: Optional environment mapping for bootstrap-time selection.
    :return: Parsed storage table.
    :raises ApprcTomlEnvError: If the index file is missing.
    :raises ValueError: If the index cannot be parsed.
    """
    _require_named_storage_allowed(spec)
    index_path = spec.index_path(proc_env=proc_env)
    if not index_path.is_file():
        raise ApprcTomlEnvError(
            f"{spec.index_env_key} points to a missing named-storage index: "
            f"{index_path}. Create one with "
            f"`{spec.config_command_name()} config storage add NAME PATH` "
            "or unset the variable to use path selectors only."
        )
    try:
        return load_storage_registry_or_empty(index_path)
    except OSError as exc:
        raise _index_read_error(index_path, exc) from exc


def load_optional_runtime_storage_registry(
    spec: AppConfigSpec,
    *,
    proc_env: Mapping[str, str] | None = None,
) -> StorageRegistry | None:
    """Read the named-storage index only when it is allowed and present.

    :param spec: Application-specific config contract.
    :param proc_env: Optional environment mapping for bootstrap-time selection.
    :return: Parsed storage table, or ``None`` for path-only selection.
    :raises ValueError: If an existing index cannot be parsed.
    """
    if not spec.named_storage_allowed():
        return None
    index_path = spec.index_path(proc_env=proc_env)
    if not index_path.is_file():
        return None
    try:
        return load_storage_registry_or_empty(index_path)
    except OSError as exc:
        raise _index_read_error(index_path, exc) from exc


def load_runtime_storage_registry_for_selector(
    spec: AppConfigSpec,
    *,
    raw_selector: str,
    proc_env: Mapping[str, str] | None = None,
) -> StorageRegistry | None:
    """Read the named-storage index only when a selector may need it.

    Path-like selectors are the storage-only happy path and must not be blocked
    by a missing or invalid optional index. Bare selectors use an existing
    index when available; without an index they remain valid path selectors.

    :param spec: Application-specific config contract.
    :param raw_selector: Selected storage value before resolution.
    :param proc_env: Optional environment mapping for bootstrap-time selection.
    :return: Parsed storage table, or ``None`` for path-only selection.
    :raises ValueError: If a bare selector needs an existing invalid index.
    """
    if not spec.named_storage_allowed() or storage_selector_is_path_like(
        raw_selector
    ):
        return None
    index_path = spec.index_path(proc_env=proc_env)
    if not index_path.is_file():
        return None
    try:
        return load_storage_registry_or_empty(index_path)
    except OSError as exc:
        raise _index_read_error(index_path, exc) from exc


def inspect_storage_registry(
    spec: AppConfigSpec,
    *,
    raw_selector: str | None = None,
    proc_env: Mapping[str, str] | None = None,
) -> StorageRegistryInspection:
    """Inspect optional named-storage index state without raising.

    :param spec: Application-specific config contract.
    :param raw_selector: Selected storage value before resolution, if any.
    :param proc_env: Optional environment mapping for bootstrap-time selection.
    :return: Named-storage index diagnosis for ``config doctor`` and paths.
    """
    env = os.environ if proc_env is None else proc_env
    raw_index_env_value = env.get(spec.index_env_key, "").strip()
    index_path = spec.index_path(proc_env=proc_env)
    index_exists = index_path.is_file()
    if not spec.named_storage_allowed():
        warning = (
            [
                f"Named-storage index ignored because the layer is disabled: {index_path}"
            ]
            if index_exists
            else []
        )
        return StorageRegistryInspection(
            path=index_path,
            env_value=raw_index_env_value or None,
            exists=index_exists,
            error=None,
            registry=None,
            storage_count=0,
            issues=[],
            warnings=warning,
        )
    if not index_exists:
        issue = (
            [f"Named-storage index does not exist: {index_path}"]
            if spec.named_storage_default()
            else []
        )
        return StorageRegistryInspection(
            path=index_path,
            env_value=raw_index_env_value or None,
            exists=False,
            error=None,
            registry=None,
            storage_count=0,
            issues=issue,
            warnings=[],
        )

    path_like_selector = (
        raw_selector is not None and storage_selector_is_path_like(raw_selector)
    )
    index_error_is_fatal = spec.named_storage_default() or (
        raw_selector is not None and not path_like_selector
    )
    try:
        registry = load_storage_registry_or_empty(index_path)
    except OSError as exc:
        index_error = str(exc)
        message = (
            "Named-storage index could not be read: "
            f"{index_path}: {index_error}"
        )
        return StorageRegistryInspection(
            path=index_path,
            env_value=raw_index_env_value or None,
            exists=True,
            error=index_error,
            registry=None,
            storage_count=0,
            issues=[message] if index_error_is_fatal else [],
            warnings=[] if index_error_is_fatal else [message],
        )
    except ValueError as exc:
        index_error = str(exc)
        message = f"Named-storage index is invalid: {index_error}"
        return StorageRegistryInspection(
            path=index_path,
            env_value=raw_index_env_value or None,
            exists=True,
            error=index_error,
            registry=None,
            storage_count=0,
            issues=[message] if index_error_is_fatal else [],
            warnings=[] if index_error_is_fatal else [message],
        )

    return StorageRegistryInspection(
        path=index_path,
        env_value=raw_index_env_value or None,
        exists=True,
        error=None,
        registry=registry,
        storage_count=len(registry.storages),
        issues=[],
        warnings=[],
    )


def _require_named_storage_allowed(spec: AppConfigSpec) -> None:
    """Raise when a named-storage command is unavailable for this app.

    :param spec: Application-specific config contract.
    :raises ValueError: If named storage is disabled.
    """
    if not spec.named_storage_allowed():
        raise ValueError(f"{spec.display_name} does not enable named storage.")


def _index_read_error(path: Path, exc: OSError) -> ConfigHomeError:
    """Return a config-home error for unreadable index files.

    :param path: Named-storage index path that could not be read.
    :param exc: Filesystem read failure.
    :return: Config-home error suitable for CLI adapters.
    """
    return ConfigHomeError(
        f"AppRC-managed file could not be read: {Path(path).expanduser()}: {exc}"
    )
