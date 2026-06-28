"""Build AppRC layer diagnostics independent of CLI rendering."""

from __future__ import annotations

# == Standard Library ========================
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

# == Internal ================================
from apprc.runtime_config.bootstrap.dotenv_layers import (
    read_dotenv_file,
    read_storage_selector_fallback_values,
)
from apprc.runtime_config.bootstrap.process_env import selection_env
from apprc.runtime_config.config_home import AppConfigHome
from apprc.runtime_config.doctor.status import ConfigDoctorStatus
from apprc.runtime_config.storage.loading import (
    StorageRegistryInspection,
    inspect_storage_registry,
)
from apprc.runtime_config.storage.selector import (
    StorageSelection,
    StorageSelectorError,
    resolve_storage_selector_value,
    select_storage_selector,
)

if TYPE_CHECKING:
    from apprc.runtime_config.kit import AppConfigKit


class ConfigDoctorPayload(TypedDict):
    """Machine-readable diagnostics emitted by ``config doctor``."""

    status: str
    writes: str
    capabilities: dict[str, str]
    config_home: str
    config_home_exists: bool
    app_wide_env: str
    app_wide_env_exists: bool
    app_wide_active: bool
    storage_env_key: str | None
    index_env_key: str
    index_env_value: str | None
    index_path: str | None
    index_exists: bool
    index_parse_ok: bool
    index_error: str | None
    storage_count: int
    selected_storage: str | None
    selected_storage_source: str | None
    selected_storage_selector: str | None
    selected_storage_root: str | None
    selected_storage_root_exists: bool | None
    selected_storage_env: str | None
    selected_storage_env_exists: bool | None
    missing_env_keys: list[str]
    issues: list[str]
    warnings: list[str]
    next_steps: list[str]


@dataclass(frozen=True, slots=True)
class _StorageDiagnosis:
    """Active storage state discovered for one doctor run."""

    selection: StorageSelection | None
    storage_root_exists: bool | None
    storage_env: Path | None
    storage_env_exists: bool | None
    missing_env_keys: list[str]
    issues: list[str]
    registry: StorageRegistryInspection


@dataclass(frozen=True, slots=True)
class _AppWideDiagnosis:
    """App-wide dotenv state discovered for one doctor run."""

    active: bool
    issues: list[str]


def config_command_text(kit: "AppConfigKit", action: str) -> str:
    """Return one display command for this app's config group.

    :param kit: Application config facade.
    :param action: Command suffix after ``<app> config``.
    :return: Human-readable command text.
    """
    return f"{kit.spec.config_command_name()} config {action}"


def config_setup_message(kit: "AppConfigKit") -> str:
    """Return setup text shown when runtime storage is missing."""
    if not kit.spec.storage_required():
        return (
            f"{kit.spec.display_name} can run from packaged defaults, explicit "
            "env files, and shell environment variables.\n\n"
            "Inspect the current layer state:\n"
            f"  {config_command_text(kit, 'paths')}\n"
            f"  {config_command_text(kit, 'doctor')}"
        )
    storage_key = kit.spec.require_storage_env_key()
    return (
        f"No active {kit.spec.display_name} storage is selected.\n\n"
        f"Set {storage_key} to a storage path or pass --storage PATH. The "
        "named-storage index is optional and only needed for named selectors.\n"
        "For guided setup:\n"
        f"  {config_command_text(kit, 'setup --yes --storage-root /absolute/path/to/storage-root')}\n\n"
        "Then inspect the setup:\n"
        f"  {config_command_text(kit, 'paths')}\n"
        f"  {config_command_text(kit, 'doctor')}"
    )


def build_config_doctor_payload(
    kit: "AppConfigKit",
    *,
    storage: str | None,
    explicit_values: Mapping[str, str] | None = None,
    env_file_overrides_os_environ: bool = False,
) -> ConfigDoctorPayload:
    """Return local setup diagnostics for one app's active layers.

    :param kit: Application config facade.
    :param storage: Optional selector passed by ``--storage``.
    :param explicit_values: Parsed values from root ``--env-file`` options.
    :param env_file_overrides_os_environ: Whether explicit dotenv values beat
        process env values during selector resolution.
    :return: Stable JSON-friendly diagnostic payload.
    """
    explicit_selector_values = explicit_values or {}
    selector_env = selection_env(
        original_env=os.environ,
        explicit_values=explicit_selector_values,
        env_file_overrides_os_environ=env_file_overrides_os_environ,
    )
    paths = kit.spec.config_paths(proc_env=selector_env)
    app_wide = _diagnose_app_wide(kit, paths=paths)
    storage_diagnosis = _diagnose_storage(
        kit,
        storage=storage,
        explicit_values=explicit_selector_values,
        env_file_overrides_os_environ=env_file_overrides_os_environ,
        selector_env=selector_env,
    )
    registry = storage_diagnosis.registry
    warnings = [
        *_config_package_convention_warnings(kit),
        *registry.warnings,
        *_legacy_file_warnings(
            app_wide_path=paths.app_wide_env,
            storage_env=storage_diagnosis.storage_env,
        ),
    ]
    issues = [
        *app_wide.issues,
        *registry.issues,
        *storage_diagnosis.issues,
    ]
    status = _doctor_status(
        app_wide=app_wide,
        registry=registry,
        storage=storage_diagnosis,
    )
    return _doctor_payload(
        kit,
        paths=paths,
        app_wide=app_wide,
        registry=registry,
        storage=storage_diagnosis,
        status=status,
        issues=issues,
        warnings=warnings,
    )


def _diagnose_app_wide(
    kit: "AppConfigKit",
    *,
    paths: AppConfigHome,
) -> _AppWideDiagnosis:
    """Return app-wide dotenv readiness without creating files.

    :param kit: Application config facade.
    :param paths: Resolved app-wide and index paths.
    :return: App-wide diagnosis.
    """
    if not kit.spec.app_wide_allowed():
        return _AppWideDiagnosis(active=False, issues=[])
    exists = paths.app_wide_env.is_file()
    active = kit.spec.app_wide_default() or exists
    if kit.spec.app_wide_default() and not exists:
        return _AppWideDiagnosis(
            active=active,
            issues=[f"App-wide env file does not exist: {paths.app_wide_env}"],
        )
    if exists:
        try:
            read_dotenv_file(paths.app_wide_env)
        except OSError as exc:
            return _AppWideDiagnosis(
                active=active,
                issues=[
                    "App-wide env file could not be read: "
                    f"{paths.app_wide_env}: {exc}"
                ],
            )
    return _AppWideDiagnosis(active=active, issues=[])


def _doctor_payload(
    kit: "AppConfigKit",
    *,
    paths: AppConfigHome,
    app_wide: _AppWideDiagnosis,
    registry: StorageRegistryInspection,
    storage: _StorageDiagnosis,
    status: ConfigDoctorStatus,
    issues: list[str],
    warnings: list[str],
) -> ConfigDoctorPayload:
    """Serialize diagnosis objects into the public doctor payload.

    :param kit: Application config facade.
    :param paths: Resolved app-wide and index paths.
    :param app_wide: App-wide dotenv diagnosis.
    :param registry: Optional named-storage index diagnosis.
    :param storage: Active storage diagnosis.
    :param status: Public readiness status.
    :param issues: Readiness-affecting problems.
    :param warnings: Non-fatal convention or migration diagnostics.
    :return: Stable JSON-friendly diagnostic payload.
    """
    selection = storage.selection
    selected_storage_root = selection.root if selection is not None else None
    return {
        "status": status.value,
        "writes": "none",
        "capabilities": _capability_payload(kit),
        "config_home": str(paths.root),
        "config_home_exists": paths.root.is_dir(),
        "app_wide_env": str(paths.app_wide_env),
        "app_wide_env_exists": paths.app_wide_env.is_file(),
        "app_wide_active": app_wide.active,
        "storage_env_key": kit.spec.storage_env_key,
        "index_env_key": kit.spec.index_env_key,
        "index_env_value": registry.env_value,
        "index_path": str(registry.path) if registry.path is not None else None,
        "index_exists": registry.exists,
        "index_parse_ok": registry.parse_ok,
        "index_error": registry.error,
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
        "selected_storage_env": (
            str(storage.storage_env)
            if storage.storage_env is not None
            else None
        ),
        "selected_storage_env_exists": storage.storage_env_exists,
        "missing_env_keys": storage.missing_env_keys,
        "issues": issues,
        "warnings": warnings,
        "next_steps": _doctor_next_steps(kit, status),
    }


def _diagnose_storage(
    kit: "AppConfigKit",
    *,
    storage: str | None,
    explicit_values: Mapping[str, str],
    env_file_overrides_os_environ: bool,
    selector_env: Mapping[str, str],
) -> _StorageDiagnosis:
    """Return active storage state for diagnostics.

    :param kit: Application config facade.
    :param storage: Optional selector passed by ``--storage``.
    :param explicit_values: Parsed values from root ``--env-file`` options.
    :param env_file_overrides_os_environ: Whether explicit dotenv values beat
        process env values during selector resolution.
    :param selector_env: Process plus explicit values used for selector paths.
    :return: Storage diagnosis with missing-env and storage-env issues.
    """
    if not kit.spec.storage_required():
        registry = inspect_storage_registry(kit.spec, proc_env=selector_env)
        return _StorageDiagnosis(
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
        issues.append(_missing_env_issue(kit, missing_env_keys))
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
    return _StorageDiagnosis(
        selection=selection,
        storage_root_exists=storage_root_exists,
        storage_env=storage_env,
        storage_env_exists=storage_env_exists,
        missing_env_keys=missing_env_keys,
        issues=issues,
        registry=registry,
    )


def _doctor_status(
    *,
    app_wide: _AppWideDiagnosis,
    registry: StorageRegistryInspection,
    storage: _StorageDiagnosis,
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


def _capability_payload(kit: "AppConfigKit") -> dict[str, str]:
    """Return declared capability state for JSON output.

    :param kit: Application config facade.
    :return: JSON-friendly capability names and states.
    """
    return {
        "storage": kit.spec.storage_layer.value,
        "app_wide": kit.spec.app_wide_layer.value,
        "named_storage": kit.spec.named_storage_layer.value,
    }


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


def _legacy_file_warnings(
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
    if status == ConfigDoctorStatus.ENV_NOT_SET:
        return [
            config_command_text(
                kit,
                "setup --yes --storage-root /absolute/path/to/storage-root",
            ),
            config_command_text(kit, "paths"),
            config_command_text(kit, "doctor"),
        ]
    if status == ConfigDoctorStatus.APP_CONFIG_NOT_READY:
        return [
            config_command_text(kit, "app init"),
            config_command_text(kit, "doctor"),
        ]
    if status == ConfigDoctorStatus.NAMED_STORAGE_NOT_READY:
        return [
            "Fix the named-storage index or create a new entry:",
            config_command_text(
                kit, "storage add NAME /absolute/path/to/storage-root"
            ),
            config_command_text(kit, "doctor"),
        ]
    return [
        "Ensure the selected storage root exists and contains "
        f"{kit.spec.storage_env_filename}.",
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
        f"Env not set. {kit.spec.display_name} requires {keys}. Export the "
        "storage path or add it to an explicit dotenv file, then run "
        f"{config_command_text(kit, 'doctor')}."
    )
