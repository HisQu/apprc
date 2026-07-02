"""Build AppRC layer diagnostics independent of CLI rendering."""

from __future__ import annotations

# == Standard Library ========================
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

# == Internal ================================
from apprc.runtime._process_env import selection_env
from apprc.runtime.diagnostics._diagnosis import (
    AppWideDiagnosis,
    StorageDiagnosis,
    config_package_convention_warnings,
    diagnose_app_wide,
    diagnose_storage,
    doctor_status,
    legacy_file_warnings,
)
from apprc.runtime.diagnostics.messages import _doctor_next_steps
from apprc.runtime.diagnostics.status import ConfigDoctorStatus
from apprc.user_files.storage_roots._loading import (
    StorageRegistryInspection,
)

if TYPE_CHECKING:
    from apprc.definition.app_config.kit import AppConfigKit
    from apprc.user_files.app_home.locations import AppConfigHome


@dataclass(frozen=True, slots=True)
class ConfigDoctorPayload:
    """Machine-readable diagnostics emitted by ``config doctor``.

    :param status: Overall readiness state.
    :param writes: Whether the diagnostic operation wrote files.
    :param capabilities: Enabled config-layer capabilities by layer name.
    :param config_home: AppRC home directory path.
    :param config_home_exists: Whether ``config_home`` exists.
    :param app_wide_env: App-wide dotenv path.
    :param app_wide_env_exists: Whether the app-wide dotenv file exists.
    :param app_wide_active: Whether app-wide config participates in loading.
    :param storage_env_key: Env key used to select storage, if enabled.
    :param index_env_key: Env key that can override the storage index path.
    :param index_env_value: Current storage index override, if set.
    :param index_path: Resolved storage index path, if named storage applies.
    :param index_exists: Whether the storage index exists.
    :param index_parse_ok: Whether the storage index parsed successfully.
    :param index_error: Storage index parse error, if one was found.
    :param storage_count: Number of registered named storages.
    :param selected_storage: Active storage name, if one resolved.
    :param selected_storage_source: Where the active storage selector came
        from.
    :param selected_storage_selector: Raw active storage selector value.
    :param selected_storage_root: Active storage root path, if one resolved.
    :param selected_storage_root_exists: Whether the selected storage root
        exists, or ``None`` when not applicable.
    :param selected_storage_env: Selected storage dotenv path, if one applies.
    :param selected_storage_env_exists: Whether the selected storage dotenv
        exists, or ``None`` when not applicable.
    :param missing_env_keys: Required env keys missing for the active setup.
    :param issues: Readiness-blocking diagnostic messages.
    :param warnings: Non-blocking diagnostic messages.
    :param next_steps: Suggested CLI commands or manual actions.
    """

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
    missing_env_keys: tuple[str, ...]
    issues: tuple[str, ...]
    warnings: tuple[str, ...]
    next_steps: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        """Return the JSON-friendly public payload shape.

        :return: Dictionary emitted by ``config doctor --json`` and
            ``config paths --json``.
        """
        return {
            "status": self.status,
            "writes": self.writes,
            "capabilities": dict(self.capabilities),
            "config_home": self.config_home,
            "config_home_exists": self.config_home_exists,
            "app_wide_env": self.app_wide_env,
            "app_wide_env_exists": self.app_wide_env_exists,
            "app_wide_active": self.app_wide_active,
            "storage_env_key": self.storage_env_key,
            "index_env_key": self.index_env_key,
            "index_env_value": self.index_env_value,
            "index_path": self.index_path,
            "index_exists": self.index_exists,
            "index_parse_ok": self.index_parse_ok,
            "index_error": self.index_error,
            "storage_count": self.storage_count,
            "selected_storage": self.selected_storage,
            "selected_storage_source": self.selected_storage_source,
            "selected_storage_selector": self.selected_storage_selector,
            "selected_storage_root": self.selected_storage_root,
            "selected_storage_root_exists": self.selected_storage_root_exists,
            "selected_storage_env": self.selected_storage_env,
            "selected_storage_env_exists": self.selected_storage_env_exists,
            "missing_env_keys": list(self.missing_env_keys),
            "issues": list(self.issues),
            "warnings": list(self.warnings),
            "next_steps": list(self.next_steps),
        }


def build_config_doctor_payload(
    kit: "AppConfigKit",
    *,
    storage: str | None,
    explicit_values: Mapping[str, str] | None = None,
    env_file_overrides_os_environ: bool = False,
    config_group_name: str = "config",
) -> ConfigDoctorPayload:
    """Return local setup diagnostics for one app's active layers.

    :param kit: Application config facade.
    :param storage: Optional selector passed by ``--storage``.
    :param explicit_values: Parsed values from host-level ``--env-file``
        options.
    :param env_file_overrides_os_environ: Whether explicit dotenv values beat
        process env values during selector resolution.
    :param config_group_name: Config command group name used in generated
        guidance.
    :return: Stable JSON-friendly diagnostic payload.
    """
    explicit_selector_values = explicit_values or {}
    selector_env = selection_env(
        original_env=os.environ,
        explicit_values=explicit_selector_values,
        env_file_overrides_os_environ=env_file_overrides_os_environ,
    )
    paths = kit.spec.config_paths(proc_env=selector_env)
    app_wide = diagnose_app_wide(kit, paths=paths)
    storage_diagnosis = diagnose_storage(
        kit,
        storage=storage,
        explicit_values=explicit_selector_values,
        env_file_overrides_os_environ=env_file_overrides_os_environ,
        selector_env=selector_env,
        config_group_name=config_group_name,
    )
    registry = storage_diagnosis.registry
    warnings = [
        *config_package_convention_warnings(kit),
        *registry.warnings,
        *legacy_file_warnings(
            app_wide_path=paths.app_wide_env,
            storage_env=storage_diagnosis.storage_env,
        ),
    ]
    issues = [
        *app_wide.issues,
        *registry.issues,
        *storage_diagnosis.issues,
    ]
    status = doctor_status(
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
        config_group_name=config_group_name,
    )


def _doctor_payload(
    kit: "AppConfigKit",
    *,
    paths: AppConfigHome,
    app_wide: AppWideDiagnosis,
    registry: StorageRegistryInspection,
    storage: StorageDiagnosis,
    status: ConfigDoctorStatus,
    issues: list[str],
    warnings: list[str],
    config_group_name: str,
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
    :param config_group_name: Config command group name used in generated
        guidance.
    :return: Stable JSON-friendly diagnostic payload.
    """
    selection = storage.selection
    selected_storage_root = selection.root if selection is not None else None
    return ConfigDoctorPayload(
        status=status.value,
        writes="none",
        capabilities=_capability_payload(kit),
        config_home=str(paths.root),
        config_home_exists=paths.root.is_dir(),
        app_wide_env=str(paths.app_wide_env),
        app_wide_env_exists=paths.app_wide_env.is_file(),
        app_wide_active=app_wide.active,
        storage_env_key=kit.spec.storage_env_key,
        index_env_key=kit.spec.index_env_key,
        index_env_value=registry.env_value,
        index_path=str(registry.path) if registry.path is not None else None,
        index_exists=registry.exists,
        index_parse_ok=registry.parse_ok,
        index_error=registry.error,
        storage_count=registry.storage_count,
        selected_storage=(
            selection.storage_name if selection is not None else None
        ),
        selected_storage_source=(
            selection.source if selection is not None else None
        ),
        selected_storage_selector=(
            selection.raw_value if selection is not None else None
        ),
        selected_storage_root=(
            str(selected_storage_root)
            if selected_storage_root is not None
            else None
        ),
        selected_storage_root_exists=storage.storage_root_exists,
        selected_storage_env=(
            str(storage.storage_env)
            if storage.storage_env is not None
            else None
        ),
        selected_storage_env_exists=storage.storage_env_exists,
        missing_env_keys=tuple(storage.missing_env_keys),
        issues=tuple(issues),
        warnings=tuple(warnings),
        next_steps=tuple(
            _doctor_next_steps(
                kit,
                status,
                config_group_name=config_group_name,
            )
        ),
    )


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
