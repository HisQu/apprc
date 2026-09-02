"""Load optional named-storage registries from AppRC TOML."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from apprc.definition.app_config.spec import AppConfigSpec
from apprc.user_files.app_home.locations import ConfigHomeError
from apprc.user_files.app_home.index import ApprcTomlEnvError
from apprc.user_files.storage_roots.registry import (
    StorageRegistry,
    load_storage_registry_or_empty,
)
from apprc.user_files.storage_roots.selector import (
    storage_selector_is_path_like,
)


@dataclass(frozen=True, slots=True)
class StorageRegistryInspection:
    """Named-storage TOML state discovered without creating files."""

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
        """Return whether the AppRC TOML was readable and parseable."""
        return self.error is None


def apprc_toml_path_for_create(
    spec: AppConfigSpec,
    *,
    proc_env: Mapping[str, str] | None = None,
) -> Path:
    """Return the configured AppRC TOML path for storage writes.

    Missing files are valid for this intent because the caller is about to
    create or update the storage table.

    :param spec: Application-specific config contract.
    :param proc_env: Optional environment mapping for bootstrap-time selection.
    :return: Override or default AppRC TOML path.
    """
    return spec.apprc_toml_path(proc_env=proc_env)


def index_path_for_create(
    spec: AppConfigSpec,
    *,
    proc_env: Mapping[str, str] | None = None,
) -> Path:
    """Return the AppRC TOML path through the deprecated 0.19 name."""
    return apprc_toml_path_for_create(spec, proc_env=proc_env)


def load_create_or_empty_storage_registry(path: Path) -> StorageRegistry:
    """Read an existing storage table or return an empty one for write flows.

    :param path: AppRC TOML path that may not exist yet.
    :return: Parsed or empty storage table.
    :raises ValueError: If existing AppRC TOML cannot be parsed.
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
    """Read an AppRC TOML storage registry that must already exist.

    :param spec: Application-specific config contract.
    :param proc_env: Optional environment mapping for bootstrap-time selection.
    :param config_group_name: Config command group name used in generated
        guidance.
    :return: Parsed storage table.
    :raises ApprcTomlEnvError: If the AppRC TOML file is missing.
    :raises ValueError: If the AppRC TOML file cannot be parsed.
    """
    _require_named_storage_enabled(spec)
    apprc_toml_path = spec.apprc_toml_path(proc_env=proc_env)
    if not apprc_toml_path.is_file():
        raise ApprcTomlEnvError(
            f"{spec.apprc_toml_env_key} points to a missing AppRC TOML file: "
            f"{apprc_toml_path}. Create one with "
            f"`{spec.config_command_name()} {config_group_name} "
            "storage add NAME PATH` "
            "or unset the variable to use path selectors only."
        )
    try:
        return load_storage_registry_or_empty(apprc_toml_path)
    except OSError as exc:
        raise _apprc_toml_read_error(apprc_toml_path, exc) from exc


def load_optional_runtime_storage_registry(
    spec: AppConfigSpec,
    *,
    proc_env: Mapping[str, str] | None = None,
) -> StorageRegistry | None:
    """Read the storage registry only when AppRC TOML is present.

    :param spec: Application-specific config contract.
    :param proc_env: Optional environment mapping for bootstrap-time selection.
    :return: Parsed storage table, or ``None`` for path-only selection.
    :raises ValueError: If existing AppRC TOML cannot be parsed.
    """
    if not spec.named_storage_enabled():
        return None
    apprc_toml_path = spec.apprc_toml_path(proc_env=proc_env)
    if not apprc_toml_path.is_file():
        return None
    try:
        return load_storage_registry_or_empty(apprc_toml_path)
    except OSError as exc:
        raise _apprc_toml_read_error(apprc_toml_path, exc) from exc


def load_runtime_storage_registry_for_selector(
    spec: AppConfigSpec,
    *,
    raw_selector: str,
    proc_env: Mapping[str, str] | None = None,
) -> StorageRegistry | None:
    """Read AppRC TOML only when a selector may need its registry.

    Path-like selectors are the storage-only happy path and must not be blocked
    by missing or invalid optional AppRC TOML. Bare selectors use an existing
    registry when available; without one they remain valid path selectors.

    :param spec: Application-specific config contract.
    :param raw_selector: Selected storage value before resolution.
    :param proc_env: Optional environment mapping for bootstrap-time selection.
    :return: Parsed storage table, or ``None`` for path-only selection.
    :raises ValueError: If a bare selector needs invalid AppRC TOML.
    """
    if not spec.named_storage_enabled() or storage_selector_is_path_like(
        raw_selector
    ):
        return None
    apprc_toml_path = spec.apprc_toml_path(proc_env=proc_env)
    if not apprc_toml_path.is_file():
        return None
    try:
        return load_storage_registry_or_empty(apprc_toml_path)
    except OSError as exc:
        raise _apprc_toml_read_error(apprc_toml_path, exc) from exc


def inspect_storage_registry(
    spec: AppConfigSpec,
    *,
    raw_selector: str | None = None,
    proc_env: Mapping[str, str] | None = None,
) -> StorageRegistryInspection:
    """Inspect optional AppRC TOML storage state without raising.

    :param spec: Application-specific config contract.
    :param raw_selector: Selected storage value before resolution, if any.
    :param proc_env: Optional environment mapping for bootstrap-time selection.
    :return: AppRC TOML diagnosis for ``config doctor`` and paths.
    """
    env = os.environ if proc_env is None else proc_env
    raw_apprc_toml_env_value = env.get(spec.apprc_toml_env_key, "").strip()
    apprc_toml_path = spec.apprc_toml_path(proc_env=proc_env)
    apprc_toml_exists = apprc_toml_path.is_file()
    if not spec.named_storage_enabled():
        warning = (
            [
                "AppRC TOML ignored because named storage is disabled: "
                f"{apprc_toml_path}"
            ]
            if apprc_toml_exists
            else []
        )
        return StorageRegistryInspection(
            path=apprc_toml_path,
            env_value=raw_apprc_toml_env_value or None,
            exists=apprc_toml_exists,
            error=None,
            registry=None,
            storage_count=0,
            issues=[],
            warnings=warning,
        )
    if not apprc_toml_exists:
        issue = (
            [f"AppRC TOML does not exist: {apprc_toml_path}"]
            if spec.apprc_toml_required()
            else []
        )
        return StorageRegistryInspection(
            path=apprc_toml_path,
            env_value=raw_apprc_toml_env_value or None,
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
    apprc_toml_error_is_fatal = spec.apprc_toml_required() or (
        raw_selector is not None and not path_like_selector
    )
    try:
        registry = load_storage_registry_or_empty(apprc_toml_path)
    except OSError as exc:
        apprc_toml_error = str(exc)
        message = (
            "AppRC TOML could not be read: "
            f"{apprc_toml_path}: {apprc_toml_error}"
        )
        return StorageRegistryInspection(
            path=apprc_toml_path,
            env_value=raw_apprc_toml_env_value or None,
            exists=True,
            error=apprc_toml_error,
            registry=None,
            storage_count=0,
            issues=[message] if apprc_toml_error_is_fatal else [],
            warnings=[] if apprc_toml_error_is_fatal else [message],
        )
    except ValueError as exc:
        apprc_toml_error = str(exc)
        message = f"AppRC TOML is invalid: {apprc_toml_error}"
        return StorageRegistryInspection(
            path=apprc_toml_path,
            env_value=raw_apprc_toml_env_value or None,
            exists=True,
            error=apprc_toml_error,
            registry=None,
            storage_count=0,
            issues=[message] if apprc_toml_error_is_fatal else [],
            warnings=[] if apprc_toml_error_is_fatal else [message],
        )

    return StorageRegistryInspection(
        path=apprc_toml_path,
        env_value=raw_apprc_toml_env_value or None,
        exists=True,
        error=None,
        registry=registry,
        storage_count=len(registry.storages),
        issues=[],
        warnings=[],
    )


def _require_named_storage_enabled(spec: AppConfigSpec) -> None:
    """Raise when a named-storage command is unavailable for this app.

    :param spec: Application-specific config contract.
    :raises ValueError: If named storage is disabled.
    """
    if not spec.named_storage_enabled():
        raise ValueError(f"{spec.display_name} does not enable named storage.")


def _apprc_toml_read_error(path: Path, exc: OSError) -> ConfigHomeError:
    """Return a config-home error for unreadable AppRC TOML files.

    :param path: AppRC TOML path that could not be read.
    :param exc: Filesystem read failure.
    :return: Config-home error suitable for CLI adapters.
    """
    return ConfigHomeError(
        f"AppRC-managed file could not be read: {Path(path).expanduser()}: {exc}"
    )
