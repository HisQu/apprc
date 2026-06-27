"""Build AppRC setup diagnostics independent of CLI rendering."""

from __future__ import annotations

# == Standard Library ========================
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

# == Internal ================================
from apprc.runtime_config.app_spec import StorageMode
from apprc.runtime_config.config_home import AppConfigHome, ConfigHomeError
from apprc.runtime_config.doctor.status import ConfigDoctorStatus
from apprc.runtime_config.storage.loading import (
    StorageRegistryInspection,
    inspect_storage_registry,
)
from apprc.runtime_config.storage.registry import StorageRegistry
from apprc.runtime_config.storage.selector import (
    StorageSelection,
    StorageSelectorError,
    resolve_active_storage_selection,
)
from apprc.runtime_config.storage.selector_fallbacks import (
    read_storage_selector_fallback_values,
)

if TYPE_CHECKING:
    from apprc.runtime_config.kit import AppConfigKit


class ConfigDoctorPayload(TypedDict):
    """Machine-readable diagnostics emitted by ``config doctor``."""

    status: str
    config_home: str
    config_home_exists: bool
    global_env: str
    global_env_exists: bool
    apprc_toml_env_key: str
    apprc_toml_env_value: str | None
    apprc_toml_path: str | None
    apprc_toml_exists: bool
    apprc_toml_parse_ok: bool
    apprc_toml_error: str | None
    storage_count: int
    selected_storage: str | None
    selected_storage_source: str | None
    selected_storage_selector: str | None
    selected_storage_root: str | None
    selected_storage_root_exists: bool | None
    selected_local_env: str | None
    selected_local_env_exists: bool | None
    missing_env_keys: list[str]
    issues: list[str]
    warnings: list[str]
    next_steps: list[str]


@dataclass(frozen=True, slots=True)
class _StorageDiagnosis:
    """Active storage state discovered for one doctor run."""

    selection: StorageSelection | None
    storage_root_exists: bool | None
    local_env: Path | None
    local_env_exists: bool | None
    missing_env_keys: list[str]
    issues: list[str]


@dataclass(frozen=True, slots=True)
class _ConfigHomeDiagnosis:
    """Config-home state discovered for one doctor run.

    :param paths: Intended AppRC-managed paths.
    :param issues: Readiness-affecting config-home problems.
    """

    paths: AppConfigHome
    issues: list[str]


def config_command_text(kit: "AppConfigKit", action: str) -> str:
    """Return one display command for this app's config group.

    :param kit: Application config facade.
    :param action: Command suffix after ``<app> config``.
    :return: Human-readable command text.
    """
    return f"{kit.spec.config_command_name()} config {action}"


def config_setup_message(kit: "AppConfigKit") -> str:
    """Return setup text shown when no storage is registered."""
    if kit.spec.storage_mode == StorageMode.DISABLED:
        return (
            f"{kit.spec.display_name} uses AppRC's app-global config home.\n\n"
            "Create or inspect the AppRC-managed files:\n"
            f"  {config_command_text(kit, 'setup')}\n\n"
            "Then inspect the setup:\n"
            f"  {config_command_text(kit, 'doctor')}\n"
            f"  {config_command_text(kit, 'show')}"
        )
    storage_key = kit.spec.require_storage_env_key()
    setup_action = "setup --yes --storage-root /absolute/path/to/storage-root"
    return (
        f"No active {kit.spec.display_name} storage is selected.\n\n"
        f"{storage_key} is required and points at the active storage root. "
        f"{kit.spec.apprc_toml_env_key} is optional; set it only when you want "
        "multi-storage features.\n"
        "Choose the storage root; setup will create the storage-local env "
        "file and print the export command:\n"
        f"  {config_command_text(kit, setup_action)}\n\n"
        "Keep the storage variable exported for future commands, then inspect "
        "the setup:\n"
        f"  {config_command_text(kit, 'doctor')}\n"
        f"  {config_command_text(kit, 'show')}\n\n"
        "Setup creates or checks:\n"
        f"  /absolute/path/to/storage-root/{kit.spec.local_env_filename}"
    )


def build_config_doctor_payload(
    kit: "AppConfigKit",
    *,
    storage: str | None,
) -> ConfigDoctorPayload:
    """Return local setup diagnostics for one app's selected storage.

    :param kit: Application config facade.
    :param storage: Optional selector passed by ``--storage``.
    :return: Stable JSON-friendly diagnostic payload.
    """
    config_home_diagnosis = _diagnose_config_home(kit)
    storage_registry_diagnosis = inspect_storage_registry(kit.spec)
    storage_diagnosis = _diagnose_storage(
        kit,
        registry=storage_registry_diagnosis.registry,
        storage=storage,
    )
    issues = [
        *config_home_diagnosis.issues,
        *storage_registry_diagnosis.issues,
        *storage_diagnosis.issues,
    ]
    warnings = _config_package_convention_warnings(kit)
    status = _doctor_status(
        kit,
        config_home_issues=config_home_diagnosis.issues,
        registry=storage_registry_diagnosis,
        storage=storage_diagnosis,
    )
    return _doctor_payload(
        kit,
        config_home=config_home_diagnosis.paths,
        registry=storage_registry_diagnosis,
        storage=storage_diagnosis,
        status=status,
        issues=issues,
        warnings=warnings,
    )


def _diagnose_config_home(kit: "AppConfigKit") -> _ConfigHomeDiagnosis:
    """Create AppRC-managed files or capture path-level failures.

    :param kit: Application config facade.
    :return: Intended config-home paths plus any creation issue.
    """
    intended_paths = AppConfigHome(
        root=kit.spec.config_home(),
        global_env=kit.spec.global_env_path(),
        apprc_toml=kit.spec.apprc_toml_path(),
    )
    try:
        ensured_paths = kit.spec.ensure_config_home()
    except (ConfigHomeError, OSError) as exc:
        return _ConfigHomeDiagnosis(
            paths=intended_paths,
            issues=[str(exc)],
        )
    return _ConfigHomeDiagnosis(paths=ensured_paths, issues=[])


def _doctor_payload(
    kit: "AppConfigKit",
    *,
    config_home: AppConfigHome,
    registry: StorageRegistryInspection,
    storage: _StorageDiagnosis,
    status: ConfigDoctorStatus,
    issues: list[str],
    warnings: list[str],
) -> ConfigDoctorPayload:
    """Serialize diagnosis objects into the public doctor payload.

    :param kit: Application config facade.
    :param registry: Optional AppRC TOML and storage-table diagnosis.
    :param storage: Active storage diagnosis.
    :param status: Public readiness status.
    :param issues: Readiness-affecting problems.
    :param warnings: Non-fatal convention or quality diagnostics.
    :return: Stable JSON-friendly diagnostic payload.
    """
    selection = storage.selection
    selected_storage_root = selection.root if selection is not None else None
    return {
        "status": status.value,
        "config_home": str(config_home.root),
        "config_home_exists": config_home.root.is_dir(),
        "global_env": str(config_home.global_env),
        "global_env_exists": config_home.global_env.is_file(),
        "apprc_toml_env_key": kit.spec.apprc_toml_env_key,
        "apprc_toml_env_value": registry.env_value,
        "apprc_toml_path": str(registry.path)
        if registry.path is not None
        else None,
        "apprc_toml_exists": registry.exists,
        "apprc_toml_parse_ok": registry.parse_ok,
        "apprc_toml_error": registry.error,
        "storage_count": registry.storage_count,
        "selected_storage": (
            selection.storage_name if selection is not None else None
        ),
        "selected_storage_source": (
            selection.source if selection is not None else None
        ),
        "selected_storage_selector": (
            selection.raw_value if selection is not None else None
        ),
        "selected_storage_root": (
            str(selected_storage_root)
            if selected_storage_root is not None
            else None
        ),
        "selected_storage_root_exists": storage.storage_root_exists,
        "selected_local_env": (
            str(storage.local_env) if storage.local_env is not None else None
        ),
        "selected_local_env_exists": storage.local_env_exists,
        "missing_env_keys": storage.missing_env_keys,
        "issues": issues,
        "warnings": warnings,
        "next_steps": _doctor_next_steps(kit, status),
    }


def _diagnose_storage(
    kit: "AppConfigKit",
    *,
    registry: StorageRegistry | None,
    storage: str | None,
) -> _StorageDiagnosis:
    """Return active storage state for diagnostics.

    :param kit: Application config facade.
    :param registry: Optional multi-storage table diagnosis result.
    :param storage: Optional selector passed by ``--storage``.
    :return: Storage diagnosis with missing-env and local-env issues.
    """
    if kit.spec.storage_mode == StorageMode.DISABLED:
        return _StorageDiagnosis(
            selection=None,
            storage_root_exists=None,
            local_env=None,
            local_env_exists=None,
            missing_env_keys=[],
            issues=[],
        )
    storage_env_key = kit.spec.require_storage_env_key()
    issues: list[str] = []
    fallback_values = read_storage_selector_fallback_values(kit.spec)
    issues.extend(fallback_values.issues)
    missing_env_keys: list[str] = []
    selection: StorageSelection | None = None
    selector_error = False

    try:
        selection = resolve_active_storage_selection(
            registry=registry,
            storage=storage,
            storage_env_key=storage_env_key,
            original_env=os.environ,
            global_values=fallback_values.global_values,
            shared_values=fallback_values.shared_values,
        )
    except StorageSelectorError as exc:
        selector_error = True
        issues.append(str(exc))
    if selection is None and not selector_error:
        missing_env_keys.append(storage_env_key)
        issues.append(_missing_env_issue(kit, missing_env_keys))

    selected_storage_root = selection.root if selection is not None else None
    local_env = (
        selected_storage_root / kit.spec.local_env_filename
        if selected_storage_root is not None
        else None
    )
    storage_root_exists = (
        selected_storage_root.is_dir()
        if selected_storage_root is not None
        else None
    )
    local_env_exists = local_env.is_file() if local_env is not None else None
    if selected_storage_root is not None and not storage_root_exists:
        issues.append(
            f"Selected storage root does not exist: {selected_storage_root}"
        )
    if local_env is not None and not local_env_exists:
        issues.append(
            f"Selected storage local env file does not exist: {local_env}"
        )
    return _StorageDiagnosis(
        selection=selection,
        storage_root_exists=storage_root_exists,
        local_env=local_env,
        local_env_exists=local_env_exists,
        missing_env_keys=missing_env_keys,
        issues=issues,
    )


def _doctor_status(
    kit: "AppConfigKit",
    *,
    config_home_issues: list[str],
    registry: StorageRegistryInspection,
    storage: _StorageDiagnosis,
) -> ConfigDoctorStatus:
    """Return readiness status while keeping missing storage env decisive.

    :param registry: Optional AppRC TOML and storage-table diagnosis.
    :param storage: Active storage diagnosis.
    :return: Public doctor status.
    """
    if config_home_issues:
        return ConfigDoctorStatus.CONFIG_NOT_READY
    if storage.missing_env_keys:
        return ConfigDoctorStatus.ENV_NOT_SET
    if registry.issues:
        if kit.spec.storage_mode == StorageMode.DISABLED:
            return ConfigDoctorStatus.CONFIG_NOT_READY
        return ConfigDoctorStatus.MULTI_STORAGE_NOT_READY
    if storage.issues:
        return ConfigDoctorStatus.STORAGE_NOT_READY
    return ConfigDoctorStatus.RUNNABLE


def _config_package_convention_warnings(kit: "AppConfigKit") -> list[str]:
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


def _doctor_next_steps(
    kit: "AppConfigKit",
    status: ConfigDoctorStatus,
) -> list[str]:
    """Return recovery steps tailored to one doctor status.

    :param kit: Application config facade.
    :param status: Public readiness status.
    :return: Ordered actions for human and JSON output.
    """
    if status == ConfigDoctorStatus.RUNNABLE:
        return []
    if status == ConfigDoctorStatus.CONFIG_NOT_READY:
        return [
            config_command_text(kit, "setup"),
            config_command_text(kit, "doctor"),
        ]
    if status == ConfigDoctorStatus.ENV_NOT_SET:
        return [
            config_command_text(
                kit,
                "setup --yes --storage-root /absolute/path/to/storage-root",
            ),
            config_command_text(kit, "doctor"),
            config_command_text(kit, "show"),
        ]
    if status == ConfigDoctorStatus.MULTI_STORAGE_NOT_READY:
        return [
            "Fix the AppRC TOML file or choose a different AppRC TOML path "
            f"with {kit.spec.apprc_toml_env_key}:",
            config_command_text(
                kit,
                "setup --yes --storage-root /absolute/path/to/storage-root "
                "--multi-storage",
            ),
            config_command_text(kit, "doctor"),
        ]
    return [
        "Ensure the selected storage root exists and contains "
        f"{kit.spec.local_env_filename}.",
        config_command_text(
            kit,
            "setup --yes --storage-root /absolute/path/to/storage-root",
        ),
        config_command_text(kit, "doctor"),
    ]


def _missing_env_issue(
    kit: "AppConfigKit",
    missing_env_keys: list[str],
) -> str:
    """Return one readable issue for missing bootstrap env keys.

    :param kit: Application config facade.
    :param missing_env_keys: Required env keys absent from this process.
    :return: Human-facing doctor issue.
    """
    keys = ", ".join(missing_env_keys)
    return (
        f"Env not set. {kit.spec.display_name} requires {keys}. Add the setup "
        "handoff values to your shell or dotenv file, then run "
        f"{config_command_text(kit, 'doctor')}."
    )
