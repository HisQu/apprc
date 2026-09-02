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
    AppConfigDiagnosis,
    StorageDiagnosis,
    config_package_convention_warnings,
    diagnose_app_config,
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
    :param storage_enabled: Whether the app declares storage.
    :param app_config_enabled: Whether per-user app config is available.
    :param named_storage_enabled: Whether named storage management is available.
    :param config_home: AppRC home directory path.
    :param config_home_exists: Whether ``config_home`` exists.
    :param app_env: Per-user app dotenv path.
    :param app_env_exists: Whether the app dotenv file exists.
    :param app_config_active: Whether app config participates in loading.
    :param storage_selector_env_key: Env key used to select storage.
    :param apprc_toml_env_key: Env key that relocates AppRC TOML.
    :param apprc_toml_env_value: Current AppRC TOML override, if set.
    :param apprc_toml: Resolved AppRC TOML path.
    :param apprc_toml_exists: Whether AppRC TOML exists.
    :param apprc_toml_parse_ok: Whether AppRC TOML parsed successfully.
    :param apprc_toml_error: AppRC TOML parse error, if one was found.
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
    storage_enabled: bool
    app_config_enabled: bool
    named_storage_enabled: bool
    config_home: str
    config_home_exists: bool
    app_env: str
    app_env_exists: bool
    app_config_active: bool
    storage_selector_env_key: str | None
    apprc_toml_env_key: str
    apprc_toml_env_value: str | None
    apprc_toml: str | None
    apprc_toml_exists: bool
    apprc_toml_parse_ok: bool
    apprc_toml_error: str | None
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

    @property
    def capabilities(self) -> dict[str, str]:
        """Return the old capability map as a 0.20 read alias."""
        return {
            "storage": "required" if self.storage_enabled else "disabled",
            "app_wide": "optional" if self.app_config_enabled else "disabled",
            "named_storage": (
                "optional" if self.named_storage_enabled else "disabled"
            ),
        }

    @property
    def app_wide_env(self) -> str:
        """Return ``app_env`` through the deprecated 0.19 name."""
        return self.app_env

    @property
    def app_wide_env_exists(self) -> bool:
        """Return ``app_env_exists`` through the deprecated 0.19 name."""
        return self.app_env_exists

    @property
    def app_wide_active(self) -> bool:
        """Return ``app_config_active`` through the deprecated 0.19 name."""
        return self.app_config_active

    @property
    def storage_env_key(self) -> str | None:
        """Return the selector key through the deprecated 0.19 name."""
        return self.storage_selector_env_key

    @property
    def index_env_key(self) -> str:
        """Return the TOML key through the deprecated 0.19 name."""
        return self.apprc_toml_env_key

    @property
    def index_env_value(self) -> str | None:
        """Return the TOML override through the deprecated 0.19 name."""
        return self.apprc_toml_env_value

    @property
    def index_path(self) -> str | None:
        """Return the TOML path through the deprecated 0.19 name."""
        return self.apprc_toml

    @property
    def index_exists(self) -> bool:
        """Return TOML existence through the deprecated 0.19 name."""
        return self.apprc_toml_exists

    @property
    def index_parse_ok(self) -> bool:
        """Return TOML parse status through the deprecated 0.19 name."""
        return self.apprc_toml_parse_ok

    @property
    def index_error(self) -> str | None:
        """Return the TOML error through the deprecated 0.19 name."""
        return self.apprc_toml_error

    def to_payload(self) -> dict[str, Any]:
        """Return the JSON-friendly public payload shape.

        :return: Dictionary emitted by ``config doctor --json`` and
            ``config paths --json``.
        """
        return {
            "status": self.status,
            "writes": self.writes,
            "storage_enabled": self.storage_enabled,
            "app_config_enabled": self.app_config_enabled,
            "named_storage_enabled": self.named_storage_enabled,
            "config_home": self.config_home,
            "config_home_exists": self.config_home_exists,
            "app_env": self.app_env,
            "app_env_exists": self.app_env_exists,
            "app_config_active": self.app_config_active,
            "storage_selector_env_key": self.storage_selector_env_key,
            "apprc_toml_env_key": self.apprc_toml_env_key,
            "apprc_toml_env_value": self.apprc_toml_env_value,
            "apprc_toml": self.apprc_toml,
            "apprc_toml_exists": self.apprc_toml_exists,
            "apprc_toml_parse_ok": self.apprc_toml_parse_ok,
            "apprc_toml_error": self.apprc_toml_error,
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
    app_config = diagnose_app_config(kit, paths=paths)
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
            kit.spec,
            storage_root=(
                storage_diagnosis.selection.root
                if storage_diagnosis.selection is not None
                else None
            ),
        ),
    ]
    issues = [
        *app_config.issues,
        *registry.issues,
        *storage_diagnosis.issues,
    ]
    status = doctor_status(
        app_config=app_config,
        registry=registry,
        storage=storage_diagnosis,
    )
    return _doctor_payload(
        kit,
        paths=paths,
        app_config=app_config,
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
    app_config: AppConfigDiagnosis,
    registry: StorageRegistryInspection,
    storage: StorageDiagnosis,
    status: ConfigDoctorStatus,
    issues: list[str],
    warnings: list[str],
    config_group_name: str,
) -> ConfigDoctorPayload:
    """Serialize diagnosis objects into the public doctor payload.

    :param kit: Application config facade.
    :param paths: Resolved app and AppRC TOML paths.
    :param app_config: Per-user app dotenv diagnosis.
    :param registry: Optional AppRC TOML diagnosis.
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
        storage_enabled=kit.spec.uses_storage(),
        app_config_enabled=kit.spec.app_env_enabled(),
        named_storage_enabled=kit.spec.named_storage_enabled(),
        config_home=str(paths.root),
        config_home_exists=paths.root.is_dir(),
        app_env=str(paths.app_env),
        app_env_exists=paths.app_env.is_file(),
        app_config_active=app_config.active,
        storage_selector_env_key=kit.spec.storage_selector_env_key,
        apprc_toml_env_key=kit.spec.apprc_toml_env_key,
        apprc_toml_env_value=registry.env_value,
        apprc_toml=(str(registry.path) if registry.path is not None else None),
        apprc_toml_exists=registry.exists,
        apprc_toml_parse_ok=registry.parse_ok,
        apprc_toml_error=registry.error,
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
