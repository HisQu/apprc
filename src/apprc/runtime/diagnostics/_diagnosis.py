"""Read-only AppRC diagnosis helpers behind the public doctor payload."""

from __future__ import annotations

# == Standard Library ========================
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

# == Internal ================================
from apprc.runtime._dotenv_layers import (
    read_dotenv_file,
    read_storage_selector_fallback_values,
)
from apprc.runtime.diagnostics.messages import _missing_env_issue
from apprc.runtime.diagnostics.status import ConfigDoctorStatus
from apprc.user_files.app_home.locations import AppConfigHome
from apprc.user_files.storage_roots._loading import (
    StorageRegistryInspection,
    inspect_storage_registry,
)
from apprc.user_files.storage_roots.selector import (
    StorageSelection,
    StorageSelectorError,
    resolve_storage_selector_value,
    select_storage_selector,
)

if TYPE_CHECKING:
    from apprc.definition.app_config.kit import AppConfigKit


@dataclass(frozen=True, slots=True)
class StorageDiagnosis:
    """Active storage state discovered for one doctor run."""

    selection: StorageSelection | None
    storage_root_exists: bool | None
    storage_env: Path | None
    storage_env_exists: bool | None
    missing_env_keys: list[str]
    issues: list[str]
    registry: StorageRegistryInspection


@dataclass(frozen=True, slots=True)
class AppWideDiagnosis:
    """App-wide dotenv state discovered for one doctor run."""

    active: bool
    issues: list[str]


def diagnose_app_wide(
    kit: "AppConfigKit",
    *,
    paths: AppConfigHome,
) -> AppWideDiagnosis:
    """Return app-wide dotenv readiness without creating files.

    :param kit: Application config facade.
    :param paths: Resolved app-wide and index paths.
    :return: App-wide diagnosis.
    """
    if not kit.spec.app_wide_allowed():
        return AppWideDiagnosis(active=False, issues=[])
    exists = paths.app_wide_env.is_file()
    active = kit.spec.app_wide_default() or exists
    if kit.spec.app_wide_default() and not exists:
        return AppWideDiagnosis(
            active=active,
            issues=[f"App-wide env file does not exist: {paths.app_wide_env}"],
        )
    if exists:
        try:
            read_dotenv_file(paths.app_wide_env)
        except OSError as exc:
            return AppWideDiagnosis(
                active=active,
                issues=[
                    "App-wide env file could not be read: "
                    f"{paths.app_wide_env}: {exc}"
                ],
            )
    return AppWideDiagnosis(active=active, issues=[])


def diagnose_storage(
    kit: "AppConfigKit",
    *,
    storage: str | None,
    explicit_values: Mapping[str, str],
    env_file_overrides_os_environ: bool,
    selector_env: Mapping[str, str],
    config_group_name: str,
) -> StorageDiagnosis:
    """Return active storage state for diagnostics.

    :param kit: Application config facade.
    :param storage: Optional selector passed by ``--storage``.
    :param explicit_values: Parsed values from host-level ``--env-file``
        options.
    :param env_file_overrides_os_environ: Whether explicit dotenv values beat
        process env values during selector resolution.
    :param selector_env: Process plus explicit values used for selector paths.
    :param config_group_name: Config command group name used in generated
        guidance.
    :return: Storage diagnosis with missing-env and storage-env issues.
    """
    if not kit.spec.storage_required():
        registry = inspect_storage_registry(kit.spec, proc_env=selector_env)
        return StorageDiagnosis(
            selection=None,
            storage_root_exists=None,
            storage_env=None,
            storage_env_exists=None,
            missing_env_keys=[],
            issues=[],
            registry=registry,
        )
    storage_env_key = kit.spec.require_storage_env_key()
    issues: list[str] = []
    fallback_values = read_storage_selector_fallback_values(
        kit.spec,
        collect_app_wide_issues=True,
    )
    issues.extend(fallback_values.issues)
    missing_env_keys: list[str] = []
    selection: StorageSelection | None = None
    registry = inspect_storage_registry(kit.spec, proc_env=selector_env)

    storage_selector = select_storage_selector(
        storage=storage,
        storage_env_key=storage_env_key,
        original_env=os.environ,
        explicit_values=explicit_values,
        app_wide_values=fallback_values.app_wide_values,
        shared_values=fallback_values.shared_values,
        env_file_overrides_os_environ=env_file_overrides_os_environ,
    )
    if storage_selector is None:
        missing_env_keys.append(storage_env_key)
        issues.append(
            _missing_env_issue(
                kit,
                missing_env_keys,
                config_group_name=config_group_name,
            )
        )
    else:
        selector_source, selector_value = storage_selector
        registry = inspect_storage_registry(
            kit.spec,
            raw_selector=selector_value,
            proc_env=selector_env,
        )
        if not registry.issues:
            try:
                selection = resolve_storage_selector_value(
                    registry=registry.registry,
                    raw_value=selector_value,
                    storage_env_key=storage_env_key,
                    source=selector_source,
                )
            except StorageSelectorError as exc:
                issues.append(str(exc))

    selected_storage_root = selection.root if selection is not None else None
    storage_env = (
        kit.spec.storage_env_path(selected_storage_root)
        if selected_storage_root is not None
        else None
    )
    storage_root_exists = (
        selected_storage_root.is_dir()
        if selected_storage_root is not None
        else None
    )
    storage_env_exists = (
        storage_env.is_file() if storage_env is not None else None
    )
    if selected_storage_root is not None and not storage_root_exists:
        issues.append(
            f"Selected storage root does not exist: {selected_storage_root}"
        )
    if storage_env is not None and not storage_env_exists:
        issues.append(
            f"Selected storage env file does not exist: {storage_env}"
        )
    return StorageDiagnosis(
        selection=selection,
        storage_root_exists=storage_root_exists,
        storage_env=storage_env,
        storage_env_exists=storage_env_exists,
        missing_env_keys=missing_env_keys,
        issues=issues,
        registry=registry,
    )


def doctor_status(
    *,
    app_wide: AppWideDiagnosis,
    registry: StorageRegistryInspection,
    storage: StorageDiagnosis,
) -> ConfigDoctorStatus:
    """Return readiness status with missing storage env as decisive.

    :param app_wide: App-wide dotenv diagnosis.
    :param registry: Optional named-storage index diagnosis.
    :param storage: Active storage diagnosis.
    :return: Public doctor status.
    """
    if storage.missing_env_keys:
        return ConfigDoctorStatus.ENV_NOT_SET
    if app_wide.issues:
        return ConfigDoctorStatus.APP_CONFIG_NOT_READY
    if registry.issues:
        return ConfigDoctorStatus.NAMED_STORAGE_NOT_READY
    if storage.issues:
        return ConfigDoctorStatus.STORAGE_NOT_READY
    return ConfigDoctorStatus.RUNNABLE


def config_package_convention_warnings(kit: "AppConfigKit") -> list[str]:
    """Return non-fatal warnings for drift from ``<app>.config.*``.

    :param kit: Application config facade.
    :return: Human-readable convention warnings for doctor output.
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
    *,
    app_wide_path: Path,
    storage_env: Path | None,
) -> list[str]:
    """Return migration warnings for old dotenv filenames.

    :param app_wide_path: Current app-wide dotenv path.
    :param storage_env: Current selected storage dotenv path, if any.
    :return: Human-readable legacy-file warnings.
    """
    warnings: list[str] = []
    old_app_env = app_wide_path.with_name(".env.global")
    if old_app_env.is_file():
        warnings.append(
            f"Legacy app-wide dotenv file ignored: {old_app_env}. Move values "
            f"to {app_wide_path}."
        )
    if storage_env is not None:
        old_storage_env = storage_env.with_name(".env.local")
        if old_storage_env.is_file():
            warnings.append(
                "Legacy storage dotenv file ignored: "
                f"{old_storage_env}. Move values to {storage_env}."
            )
    return warnings
