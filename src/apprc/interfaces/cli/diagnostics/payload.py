"""Build AppRC layer diagnostics independent of CLI rendering."""

from __future__ import annotations

from apprc.user_files.app_home.application import AppFiles

# == Standard Library ===========================================
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

# == Internal ===================================================
from apprc.definition.resolution import ResolveOptions
from apprc.services.manager import ConfigManager
from apprc.interfaces.cli.diagnostics.status import ConfigDoctorStatus
from apprc.interfaces.cli.diagnostics._diagnosis import (
    diagnose_user_dotenv,
    diagnose_storage,
    doctor_status,
    legacy_file_warnings,
)
from apprc.interfaces.cli.diagnostics.messages import _doctor_next_steps

if TYPE_CHECKING:
    from apprc.public.app_rc import AppRC


@dataclass(frozen=True, slots=True)
class ConfigDoctorPayload:
    """Machine-readable diagnostics emitted by ``config doctor``.

    The payload uses file-specific terms: dotenv paths are never called
    configuration paths, and the AppRC directory override is distinct from
    the fixed TOML filename.
    """

    status: str
    writes: str
    user_dotenv_enabled: bool
    user_dotenv_required: bool
    storage_enabled: bool
    storage_required: bool
    apprc_dir: str | None
    apprc_dir_env_key: str | None
    apprc_dir_env_value: str | None
    apprc_dir_exists: bool | None
    user_dotenv: str | None
    user_dotenv_exists: bool | None
    storage_selector_env_key: str | None
    apprc_toml: str | None
    apprc_toml_exists: bool | None
    apprc_toml_parse_ok: bool | None
    apprc_toml_error: str | None
    storage_count: int
    configured_selected_storage: str | None
    selected_storage: str | None
    selected_storage_source: str | None
    selected_storage_selector: str | None
    selected_storage_selector_kind: str | None
    selected_storage_root: str | None
    selected_storage_root_exists: bool | None
    selected_storage_dotenv: str | None
    selected_storage_dotenv_exists: bool | None
    issues: tuple[str, ...]
    warnings: tuple[str, ...]
    next_steps: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        """Return a JSON-friendly dictionary.

        :return: Diagnostic fields with tuples converted to lists.
        """
        payload = asdict(self)
        for key in ("issues", "warnings", "next_steps"):
            payload[key] = list(payload[key])
        return payload


def build_config_doctor_payload(
    apprc: "AppRC",
    *,
    storage: str | None,
    manager: ConfigManager | None = None,
    storage_required: bool = False,
    config_group_name: str = "config",
) -> ConfigDoctorPayload:
    """Return zero-write setup diagnostics for one application.

    :param apprc: Application config facade.
    :param storage: Optional name supplied through ``--storage``.
    :param manager: Invocation-bound shared operations, including explicit files.
    :param storage_required: Runtime policy when no manager is supplied.
    :param config_group_name: Mounted config command name.
    :return: Stable diagnostic payload.
    """
    manager = manager or apprc.manage(
        ResolveOptions(storage=storage, storage_required=storage_required)
    )
    inspection = manager.inspect()
    resolved = inspection.resolved
    paths = resolved.paths or AppFiles(apprc.schema).paths(manager.environment)
    user_dotenv = diagnose_user_dotenv(apprc, paths=paths)
    storage_diagnosis = diagnose_storage(
        apprc, resolved=resolved, registry=manager.inspect_registry()
    )
    registry = storage_diagnosis.registry
    selected_root = (
        storage_diagnosis.selection.root
        if storage_diagnosis.selection is not None
        else None
    )
    warnings = [
        *user_dotenv.warnings,
        *registry.warnings,
        *legacy_file_warnings(
            apprc.schema, storage_root=selected_root, paths=paths
        ),
    ]
    issues = list(
        dict.fromkeys(
            [
                *user_dotenv.issues,
                *registry.issues,
                *storage_diagnosis.issues,
                *inspection.issues,
            ]
        )
    )
    status = doctor_status(
        user_dotenv=user_dotenv,
        registry=registry,
        storage=storage_diagnosis,
    )
    if status == ConfigDoctorStatus.RUNNABLE and issues:
        status = ConfigDoctorStatus.CONFIG_INVALID
    selection = storage_diagnosis.selection
    configured_selected_storage = (
        registry.registry.selected_storage
        if registry.registry is not None
        else None
    )
    return ConfigDoctorPayload(
        status=status.value,
        writes="none",
        user_dotenv_enabled=apprc.schema.uses_user_dotenv(),
        user_dotenv_required=False,
        storage_enabled=apprc.schema.uses_storage(),
        storage_required=manager.options.storage_required,
        apprc_dir=str(paths.root)
        if apprc.schema.uses_managed_files()
        else None,
        apprc_dir_env_key=(
            apprc.schema.apprc_dir_env_key
            if apprc.schema.uses_managed_files()
            else None
        ),
        apprc_dir_env_value=(
            registry.env_value if apprc.schema.uses_managed_files() else None
        ),
        apprc_dir_exists=(
            paths.root.is_dir() if apprc.schema.uses_managed_files() else None
        ),
        user_dotenv=(
            str(paths.user_dotenv) if apprc.schema.uses_user_dotenv() else None
        ),
        user_dotenv_exists=(
            paths.user_dotenv.is_file()
            if apprc.schema.uses_user_dotenv()
            else None
        ),
        storage_selector_env_key=apprc.schema.storage_selector_env_key,
        apprc_toml=(
            str(paths.apprc_toml) if apprc.schema.uses_storage() else None
        ),
        apprc_toml_exists=(
            registry.exists if apprc.schema.uses_storage() else None
        ),
        apprc_toml_parse_ok=(
            registry.parse_ok if apprc.schema.uses_storage() else None
        ),
        apprc_toml_error=(
            registry.error if apprc.schema.uses_storage() else None
        ),
        storage_count=(
            registry.storage_count if apprc.schema.uses_storage() else 0
        ),
        configured_selected_storage=(
            configured_selected_storage if apprc.schema.uses_storage() else None
        ),
        selected_storage=selection.storage_name if selection else None,
        selected_storage_source=selection.source if selection else None,
        selected_storage_selector=selection.raw_value if selection else None,
        selected_storage_selector_kind=(
            selection.selector_kind if selection else None
        ),
        selected_storage_root=str(selected_root) if selected_root else None,
        selected_storage_root_exists=storage_diagnosis.storage_root_exists,
        selected_storage_dotenv=(
            str(storage_diagnosis.storage_dotenv)
            if storage_diagnosis.storage_dotenv
            else None
        ),
        selected_storage_dotenv_exists=(
            storage_diagnosis.storage_dotenv_exists
        ),
        issues=tuple(issues),
        warnings=tuple(warnings),
        next_steps=tuple(
            _doctor_next_steps(
                apprc,
                status,
                config_group_name=config_group_name,
                storage_count=registry.storage_count,
                selector_error=storage_diagnosis.selector_error,
                selected_storage=(
                    selection.storage_name if selection is not None else None
                ),
                storage_root_exists=storage_diagnosis.storage_root_exists,
            )
        ),
    )
