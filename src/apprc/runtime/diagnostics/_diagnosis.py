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
    from apprc.definition.app_config.spec import AppConfigSpec
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
class AppConfigDiagnosis:
    """Per-user app dotenv state discovered for one doctor run."""

    active: bool
    issues: list[str]


def diagnose_app_config(
    kit: "AppConfigKit",
    *,
    paths: AppConfigHome,
) -> AppConfigDiagnosis:
    """Return per-user app dotenv readiness without creating files.

    :param kit: Application config facade.
    :param paths: Resolved app and AppRC TOML paths.
    :return: Per-user app config diagnosis.
    """
    if not kit.spec.app_env_enabled():
        return AppConfigDiagnosis(active=False, issues=[])
    exists = paths.app_env.is_file()
    active = not kit.spec.uses_legacy_constructor() or (
        kit.spec.setup_creates_app_env() or exists
    )
    if kit.spec.setup_creates_app_env() and not exists:
        return AppConfigDiagnosis(
            active=active,
            issues=[f"App env file does not exist: {paths.app_env}"],
        )
    if exists:
        try:
            read_dotenv_file(paths.app_env)
        except OSError as exc:
            return AppConfigDiagnosis(
                active=active,
                issues=[
                    f"App env file could not be read: {paths.app_env}: {exc}"
                ],
            )
    return AppConfigDiagnosis(active=active, issues=[])


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
    if not kit.spec.uses_storage():
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
    storage_env_key = kit.spec.require_storage_selector_env_key()
    issues: list[str] = []
    fallback_values = read_storage_selector_fallback_values(
        kit.spec,
        collect_app_issues=True,
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
        app_values=fallback_values.app_values,
        defaults_values=fallback_values.defaults_values,
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
    app_config: AppConfigDiagnosis,
    registry: StorageRegistryInspection,
    storage: StorageDiagnosis,
) -> ConfigDoctorStatus:
    """Return readiness status with a missing storage selector as decisive.

    :param app_config: Per-user app dotenv diagnosis.
    :param registry: Optional AppRC TOML diagnosis.
    :param storage: Active storage diagnosis.
    :return: Public doctor status.
    """
    if storage.missing_env_keys:
        return ConfigDoctorStatus.ENV_NOT_SET
    if app_config.issues:
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
    spec: "AppConfigSpec",
    *,
    storage_root: Path | None,
) -> list[str]:
    """Return migration warnings for old dotenv filenames.

    :param spec: Current application declaration.
    :param storage_root: Selected storage root, if any.
    :return: Human-readable legacy-file warnings.
    """
    warnings: list[str] = []
    app_resolution = spec.app_env_resolution()
    if app_resolution.uses_legacy_path:
        warnings.append(
            f"Legacy app dotenv filename is active: {app_resolution.selected}. "
            "Run `config migrate` to use the current filename."
        )
    older_app_env = app_resolution.selected.with_name(".env.global")
    if older_app_env.is_file() and older_app_env != app_resolution.selected:
        warnings.append(
            f"Legacy app dotenv file exists: {older_app_env}. Move its "
            f"values into {app_resolution.selected}."
        )
    toml_resolution = spec.apprc_toml_resolution()
    if toml_resolution.uses_legacy_path:
        warnings.append(
            "Legacy AppRC TOML filename is active: "
            f"{toml_resolution.selected}. Run `config migrate` to use the "
            "current filename."
        )
    if storage_root is not None:
        storage_resolution = spec.storage_env_resolution(storage_root)
        if storage_resolution.uses_legacy_path:
            warnings.append(
                "Legacy storage dotenv filename is active: "
                f"{storage_resolution.selected}. Run `config migrate` to use "
                "the current filename."
            )
        older_storage_env = storage_resolution.selected.with_name(".env.local")
        if (
            older_storage_env.is_file()
            and older_storage_env != storage_resolution.selected
        ):
            warnings.append(
                f"Legacy storage dotenv file exists: {older_storage_env}. "
                f"Move its values into {storage_resolution.selected}."
            )
    return warnings
