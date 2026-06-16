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

    runnable: bool
    status: str
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
    next_steps: list[str]


@dataclass(frozen=True, slots=True)
class _RegistryDiagnosis:
    """AppRC TOML state discovered for one doctor run."""

    active_toml_path: Path | None
    toml_env_value: str | None
    toml_exists: bool
    toml_error: str | None
    registry: StorageRegistry | None
    storage_count: int
    issues: list[str]

    @property
    def toml_parse_ok(self) -> bool:
        """Return whether the optional TOML layer is absent or parseable."""
        if self.active_toml_path is None:
            return True
        return self.toml_exists and self.toml_error is None


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
    storage_root: Path | None = None,
    apprc_toml_path: Path | None = None,
) -> ConfigDoctorPayload:
    """Return local setup diagnostics for one app's selected storage.

    :param kit: Application config facade.
    :param storage: Optional selector passed by ``--storage``.
    :param storage_root: Optional explicit storage root selected by setup.
    :param apprc_toml_path: Optional explicit AppRC TOML path used by setup.
        ``None`` means "use the currently configured env value, if any."
    :return: Stable JSON-friendly diagnostic payload.
    """
    registry_diagnosis = _diagnose_registry(
        kit,
        apprc_toml_path=apprc_toml_path,
    )
    storage_diagnosis = _diagnose_storage(
        kit,
        registry=registry_diagnosis.registry,
        storage=storage,
        storage_root=storage_root,
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
    runnable = status == ConfigDoctorStatus.RUNNABLE
    selection = storage.selection
    selected_storage_root = selection.root if selection is not None else None
    return {
        "runnable": runnable,
        "status": status.value,
        "apprc_toml_env_key": kit.spec.apprc_toml_env_key,
        "apprc_toml_env_value": registry.toml_env_value,
        "apprc_toml_path": (
            str(registry.active_toml_path)
            if registry.active_toml_path is not None
            else None
        ),
        "apprc_toml_exists": registry.toml_exists,
        "apprc_toml_parse_ok": registry.toml_parse_ok,
        "apprc_toml_error": registry.toml_error,
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
        "next_steps": []
        if not issues
        else [
            config_command_text(
                kit,
                "setup --yes --storage-root /absolute/path/to/storage-root",
            ),
            config_command_text(kit, "doctor"),
            config_command_text(kit, "show"),
        ],
    }


def _diagnose_registry(
    kit: "AppConfigKit",
    *,
    apprc_toml_path: Path | None,
) -> _RegistryDiagnosis:
    """Return optional multi-storage registry state for diagnostics.

    :param kit: Application config facade.
    :param apprc_toml_path: Optional explicit setup path.
    :return: Registry diagnosis with parse or missing-file issues.
    """
    raw_toml_env_value = os.environ.get(kit.spec.apprc_toml_env_key, "").strip()
    active_toml_path = (
        Path(apprc_toml_path).expanduser().resolve()
        if apprc_toml_path is not None
        else kit.spec.optional_apprc_toml_path()
    )
    if active_toml_path is None:
        return _RegistryDiagnosis(
            active_toml_path=None,
            toml_env_value=raw_toml_env_value or None,
            toml_exists=False,
            toml_error=None,
            registry=None,
            storage_count=0,
            issues=[],
        )

    toml_exists = active_toml_path.is_file()
    if not toml_exists:
        return _RegistryDiagnosis(
            active_toml_path=active_toml_path,
            toml_env_value=raw_toml_env_value or None,
            toml_exists=False,
            toml_error=None,
            registry=None,
            storage_count=0,
            issues=[f"AppRC TOML does not exist: {active_toml_path}"],
        )

    try:
        registry = load_storage_registry_or_empty(active_toml_path)
    except ValueError as exc:
        toml_error = str(exc)
        return _RegistryDiagnosis(
            active_toml_path=active_toml_path,
            toml_env_value=raw_toml_env_value or None,
            toml_exists=True,
            toml_error=toml_error,
            registry=None,
            storage_count=0,
            issues=[f"AppRC TOML is invalid: {toml_error}"],
        )

    return _RegistryDiagnosis(
        active_toml_path=active_toml_path,
        toml_env_value=raw_toml_env_value or None,
        toml_exists=True,
        toml_error=None,
        registry=registry,
        storage_count=len(registry.storages),
        issues=[],
    )


def _diagnose_storage(
    kit: "AppConfigKit",
    *,
    registry: StorageRegistry | None,
    storage: str | None,
    storage_root: Path | None,
) -> _StorageDiagnosis:
    """Return active storage state for diagnostics.

    :param kit: Application config facade.
    :param registry: Optional multi-storage registry diagnosis result.
    :param storage: Optional selector passed by ``--storage``.
    :param storage_root: Optional explicit storage root selected by setup.
    :return: Storage diagnosis with missing-env and local-env issues.
    """
    storage_env_key = kit.spec.storage_env_key
    raw_storage_env_value = os.environ.get(storage_env_key, "").strip()
    issues: list[str] = []
    missing_env_keys: list[str] = []
    selection: StorageSelection | None = None

    if storage_root is not None:
        selected_root = Path(storage_root).expanduser().resolve()
        selection = StorageSelection(
            source=storage_env_key,
            raw_value=str(storage_root),
            storage_name=storage if registry is not None else None,
            root=selected_root,
        )
    elif storage is None and not raw_storage_env_value:
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
