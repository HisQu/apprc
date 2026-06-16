"""Build AppRC setup diagnostics independent of CLI rendering."""

from __future__ import annotations

# == Standard Library ========================
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

# == Internal ================================
from apprc.config.doctor_status import ConfigDoctorStatus
from apprc.config.storage.registry import (
    StorageRegistry,
    load_storage_registry_or_empty,
)
from apprc.config.storage.selector import (
    StorageSelection,
    StorageSelectorError,
    resolve_active_storage_selection,
)

if TYPE_CHECKING:
    from apprc.config.kit import AppConfigKit


class ConfigDoctorPayload(TypedDict):
    """Machine-readable diagnostics emitted by ``config doctor``."""

    status: str
    registry_env_key: str
    registry_env_value: str | None
    registry_path: str | None
    registry_exists: bool
    registry_parse_ok: bool
    registry_error: str | None
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
    next_steps: list[str]


@dataclass(frozen=True, slots=True)
class _RegistryDiagnosis:
    """Registry state discovered for one doctor run."""

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


@dataclass(frozen=True, slots=True)
class _StorageDiagnosis:
    """Active storage state discovered for one doctor run."""

    selection: StorageSelection | None
    storage_root_exists: bool | None
    local_env: Path | None
    local_env_exists: bool | None
    missing_env_keys: list[str]
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
    storage_key = kit.spec.storage_env_key
    setup_action = "setup --yes --storage-root /absolute/path/to/storage-root"
    return (
        f"No active {kit.spec.display_name} storage is selected.\n\n"
        f"{storage_key} is required and points at the active storage root. "
        f"{kit.spec.apprc_toml_env_key} is optional; set it only when you want "
        "multi-storage registry features.\n"
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
    registry_diagnosis = _diagnose_registry(kit)
    storage_diagnosis = _diagnose_storage(
        kit,
        registry=registry_diagnosis.registry,
        storage=storage,
    )
    issues = [*registry_diagnosis.issues, *storage_diagnosis.issues]
    status = _doctor_status(
        registry=registry_diagnosis,
        storage=storage_diagnosis,
    )
    return _doctor_payload(
        kit,
        registry=registry_diagnosis,
        storage=storage_diagnosis,
        status=status,
        issues=issues,
    )


def _doctor_payload(
    kit: "AppConfigKit",
    *,
    registry: _RegistryDiagnosis,
    storage: _StorageDiagnosis,
    status: ConfigDoctorStatus,
    issues: list[str],
) -> ConfigDoctorPayload:
    """Serialize diagnosis objects into the public doctor payload.

    :param kit: Application config facade.
    :param registry: Optional registry diagnosis.
    :param storage: Active storage diagnosis.
    :param status: Public readiness status.
    :param issues: All collected issues.
    :return: Stable JSON-friendly diagnostic payload.
    """
    selection = storage.selection
    selected_storage_root = selection.root if selection is not None else None
    return {
        "status": status.value,
        "registry_env_key": kit.spec.apprc_toml_env_key,
        "registry_env_value": registry.env_value,
        "registry_path": str(registry.path)
        if registry.path is not None
        else None,
        "registry_exists": registry.exists,
        "registry_parse_ok": registry.parse_ok,
        "registry_error": registry.error,
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
        "next_steps": _doctor_next_steps(kit, status),
    }


def _diagnose_registry(kit: "AppConfigKit") -> _RegistryDiagnosis:
    """Return optional multi-storage registry state for diagnostics.

    :param kit: Application config facade.
    :return: Registry diagnosis with parse or missing-file issues.
    """
    raw_registry_env_value = os.environ.get(
        kit.spec.apprc_toml_env_key,
        "",
    ).strip()
    registry_path = kit.spec.optional_apprc_toml_path()
    if registry_path is None:
        return _RegistryDiagnosis(
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
        return _RegistryDiagnosis(
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
        return _RegistryDiagnosis(
            path=registry_path,
            env_value=raw_registry_env_value or None,
            exists=True,
            error=registry_error,
            registry=None,
            storage_count=0,
            issues=[f"Registry file is invalid: {registry_error}"],
        )

    return _RegistryDiagnosis(
        path=registry_path,
        env_value=raw_registry_env_value or None,
        exists=True,
        error=None,
        registry=registry,
        storage_count=len(registry.storages),
        issues=[],
    )


def _diagnose_storage(
    kit: "AppConfigKit",
    *,
    registry: StorageRegistry | None,
    storage: str | None,
) -> _StorageDiagnosis:
    """Return active storage state for diagnostics.

    :param kit: Application config facade.
    :param registry: Optional multi-storage registry diagnosis result.
    :param storage: Optional selector passed by ``--storage``.
    :return: Storage diagnosis with missing-env and local-env issues.
    """
    storage_env_key = kit.spec.storage_env_key
    raw_storage_env_value = os.environ.get(storage_env_key, "").strip()
    issues: list[str] = []
    missing_env_keys: list[str] = []
    selection: StorageSelection | None = None

    if storage is None and not raw_storage_env_value:
        missing_env_keys.append(storage_env_key)
        issues.append(_missing_env_issue(kit, missing_env_keys))
    else:
        try:
            selection = resolve_active_storage_selection(
                registry=registry,
                storage=storage,
                storage_env_key=storage_env_key,
                original_env=os.environ,
            )
        except StorageSelectorError as exc:
            issues.append(str(exc))

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
    *,
    registry: _RegistryDiagnosis,
    storage: _StorageDiagnosis,
) -> ConfigDoctorStatus:
    """Return readiness status while keeping missing storage env decisive.

    :param registry: Optional registry diagnosis.
    :param storage: Active storage diagnosis.
    :return: Public doctor status.
    """
    if storage.missing_env_keys:
        return ConfigDoctorStatus.ENV_NOT_SET
    if registry.issues:
        return ConfigDoctorStatus.REGISTRY_NOT_READY
    if storage.issues:
        return ConfigDoctorStatus.STORAGE_NOT_READY
    return ConfigDoctorStatus.RUNNABLE


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
            config_command_text(kit, "doctor"),
            config_command_text(kit, "show"),
        ]
    if status == ConfigDoctorStatus.REGISTRY_NOT_READY:
        return [
            f"Unset {kit.spec.apprc_toml_env_key} for single-storage mode, "
            "or create the registry:",
            config_command_text(
                kit,
                "setup --yes --apprc-dir /absolute/path/to/config-dir "
                "--storage-root /absolute/path/to/storage-root "
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
