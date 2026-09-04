"""Read-only AppRC diagnosis behind the public doctor payload."""

from __future__ import annotations

# == Standard Library ===========================================
import os
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

# == Internal ===================================================
from apprc.runtime._dotenv_layers import read_dotenv_file
from apprc.runtime.diagnostics.messages import _missing_storage_issue
from apprc.runtime.diagnostics.status import ConfigDoctorStatus
from apprc.user_files.app_home.locations import AppRCDirectoryPaths
from apprc.user_files.storage_roots._loading import (
    StorageRegistryInspection,
    inspect_storage_registry,
)
from apprc.user_files.storage_roots.selector import (
    StorageSelection,
    StorageSelectorError,
    resolve_active_storage_selection,
)

if TYPE_CHECKING:
    from apprc.definition.app_config.kit import AppConfigKit
    from apprc.definition.app_config.spec import AppConfigSpec


@dataclass(frozen=True, slots=True)
class StorageDiagnosis:
    """Active storage state discovered for one doctor run."""

    selection: StorageSelection | None
    storage_root_exists: bool | None
    storage_dotenv: Path | None
    storage_dotenv_exists: bool | None
    selection_missing: bool
    selector_error: bool
    issues: list[str]
    registry: StorageRegistryInspection


@dataclass(frozen=True, slots=True)
class UserDotenvDiagnosis:
    """Per-user dotenv state discovered for one doctor run."""

    active: bool
    issues: list[str]


def diagnose_user_dotenv(
    kit: "AppConfigKit",
    *,
    paths: AppRCDirectoryPaths,
) -> UserDotenvDiagnosis:
    """Return per-user dotenv readiness without creating files.

    :param kit: Application config facade.
    :param paths: Fixed paths below the selected AppRC directory.
    :return: Per-user dotenv diagnosis.
    """
    del kit
    if not paths.user_dotenv.is_file():
        return UserDotenvDiagnosis(
            active=True,
            issues=[f"User dotenv file does not exist: {paths.user_dotenv}"],
        )
    try:
        read_dotenv_file(paths.user_dotenv)
    except OSError as exc:
        return UserDotenvDiagnosis(
            active=True,
            issues=[
                f"User dotenv file could not be read: {paths.user_dotenv}: {exc}"
            ],
        )
    return UserDotenvDiagnosis(active=True, issues=[])


def diagnose_storage(
    kit: "AppConfigKit",
    *,
    storage: str | None,
    explicit_values: Mapping[str, str],
    env_file_overrides_os_environ: bool,
    selector_env: Mapping[str, str],
    config_group_name: str,
) -> StorageDiagnosis:
    """Return active named-storage state for diagnostics.

    :param kit: Application config facade.
    :param storage: Optional name passed by ``--storage``.
    :param explicit_values: Values from explicit dotenv files.
    :param env_file_overrides_os_environ: Whether explicit values beat the
        process environment for storage selection.
    :param selector_env: Effective environment used to locate the AppRC dir.
    :param config_group_name: Config command name used in guidance.
    :return: Storage and registry diagnosis.
    """
    registry_inspection = inspect_storage_registry(
        kit.spec,
        proc_env=selector_env,
    )
    if not kit.spec.uses_storage():
        return StorageDiagnosis(
            selection=None,
            storage_root_exists=None,
            storage_dotenv=None,
            storage_dotenv_exists=None,
            selection_missing=False,
            selector_error=False,
            issues=[],
            registry=registry_inspection,
        )

    issues: list[str] = []
    selection: StorageSelection | None = None
    selector_error = False
    registry = registry_inspection.registry
    selector_key = kit.spec.require_storage_selector_env_key()
    try:
        selection = resolve_active_storage_selection(
            registry=registry,
            apprc_toml_path=registry_inspection.path,
            storage=storage,
            storage_selector_env_key=selector_key,
            original_env=os.environ,
            explicit_values=explicit_values,
            env_file_overrides_os_environ=(env_file_overrides_os_environ),
        )
    except StorageSelectorError as exc:
        selector_error = True
        issues.append(str(exc))
    if selection is not None and selection.selector_kind == "path":
        registry_inspection = replace(
            registry_inspection,
            issues=[],
            warnings=[
                *registry_inspection.warnings,
                *registry_inspection.issues,
            ],
        )
    else:
        issues = [*registry_inspection.issues, *issues]
    selection_missing = selection is None and not selector_error
    if selection_missing:
        issues.append(
            _missing_storage_issue(
                kit,
                selector_key=selector_key,
                config_group_name=config_group_name,
            )
        )

    root = selection.root if selection is not None else None
    storage_dotenv = kit.spec.storage_dotenv_path(root) if root else None
    root_exists = root.is_dir() if root is not None else None
    dotenv_exists = storage_dotenv.is_file() if storage_dotenv else None
    if root is not None and not root_exists:
        issues.append(f"Selected storage root does not exist: {root}")
    if storage_dotenv is not None and not dotenv_exists:
        issues.append(
            f"Selected storage dotenv file does not exist: {storage_dotenv}"
        )
    return StorageDiagnosis(
        selection=selection,
        storage_root_exists=root_exists,
        storage_dotenv=storage_dotenv,
        storage_dotenv_exists=dotenv_exists,
        selection_missing=selection_missing,
        selector_error=selector_error,
        issues=issues,
        registry=registry_inspection,
    )


def doctor_status(
    *,
    user_dotenv: UserDotenvDiagnosis,
    registry: StorageRegistryInspection,
    storage: StorageDiagnosis,
) -> ConfigDoctorStatus:
    """Return the overall readiness status.

    :param user_dotenv: User dotenv diagnosis.
    :param registry: Storage registry diagnosis.
    :param storage: Active storage diagnosis.
    :return: Public status value.
    """
    if user_dotenv.issues:
        return ConfigDoctorStatus.USER_DOTENV_NOT_READY
    if registry.issues:
        return ConfigDoctorStatus.STORAGE_REGISTRY_NOT_READY
    if storage.selection_missing:
        return ConfigDoctorStatus.STORAGE_NOT_SELECTED
    if storage.issues:
        return ConfigDoctorStatus.STORAGE_NOT_READY
    return ConfigDoctorStatus.RUNNABLE


def config_package_convention_warnings(kit: "AppConfigKit") -> list[str]:
    """Return warnings for drift from the ``<app>.config`` convention.

    :param kit: Application config facade.
    :return: Human-readable warnings.
    """
    config_package = kit.spec.config_package
    warnings: list[str] = []
    if not config_package.endswith(".config"):
        warnings.append(
            "Config package convention warning: AppConfigSpec.config_package "
            f"is {config_package!r}; prefer '<app>.config'."
        )
    for env_cls in kit.spec.envs:
        module = env_cls.__module__
        if module == config_package or module.startswith(f"{config_package}."):
            continue
        warnings.append(
            "Config package convention warning: "
            f"{env_cls.__qualname__} lives in {module!r}, outside "
            f"{config_package!r}."
        )
    return warnings


def legacy_file_warnings(
    spec: "AppConfigSpec",
    *,
    storage_root: Path | None,
) -> list[str]:
    """Return warnings for released 0.19 filenames in current locations.

    Full cross-directory discovery belongs to ``config migrate``. Doctor keeps
    this check cheap and warns about immediately adjacent legacy files.

    :param spec: Current application declaration.
    :param storage_root: Selected storage root, if any.
    :return: Human-readable migration warnings.
    """
    candidates = [
        spec.apprc_dir() / ".env.apprc-app",
        *(
            [storage_root / ".env.apprc-storage"]
            if storage_root is not None
            else []
        ),
    ]
    return [
        f"Legacy AppRC file exists: {path}. Run `config migrate`."
        for path in candidates
        if path.is_file()
    ]
