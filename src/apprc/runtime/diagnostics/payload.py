"""Build AppRC layer diagnostics independent of CLI rendering."""

from __future__ import annotations

# == Standard Library ===========================================
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

# == Internal ===================================================
from apprc.runtime._process_env import selection_env
from apprc.runtime.diagnostics._diagnosis import (
    config_package_convention_warnings,
    diagnose_user_dotenv,
    diagnose_storage,
    doctor_status,
    legacy_file_warnings,
)
from apprc.runtime.diagnostics.messages import _doctor_next_steps

if TYPE_CHECKING:
    from apprc.definition.app_config.kit import AppConfigKit


@dataclass(frozen=True, slots=True)
class ConfigDoctorPayload:
    """Machine-readable diagnostics emitted by ``config doctor``.

    The payload uses file-specific terms: dotenv paths are never called
    configuration paths, and the AppRC directory override is distinct from
    the fixed TOML filename.
    """

    status: str
    writes: str
    storage_enabled: bool
    apprc_dir: str
    apprc_dir_env_key: str
    apprc_dir_env_value: str | None
    apprc_dir_exists: bool
    user_dotenv: str
    user_dotenv_exists: bool
    storage_selector_env_key: str | None
    apprc_toml: str
    apprc_toml_exists: bool
    apprc_toml_parse_ok: bool
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
    kit: "AppConfigKit",
    *,
    storage: str | None,
    explicit_values: Mapping[str, str] | None = None,
    env_file_overrides_os_environ: bool = False,
    config_group_name: str = "config",
) -> ConfigDoctorPayload:
    """Return zero-write setup diagnostics for one application.

    :param kit: Application config facade.
    :param storage: Optional name supplied through ``--storage``.
    :param explicit_values: Values from explicit dotenv files.
    :param env_file_overrides_os_environ: Whether explicit values beat process
        environment values for structural selection.
    :param config_group_name: Mounted config command name.
    :return: Stable diagnostic payload.
    """
    explicit_selector_values = explicit_values or {}
    selector_env = selection_env(
        original_env=os.environ,
        explicit_values=explicit_selector_values,
        env_file_overrides_os_environ=env_file_overrides_os_environ,
    )
    paths = kit.spec.paths(proc_env=selector_env)
    user_dotenv = diagnose_user_dotenv(kit, paths=paths)
    storage_diagnosis = diagnose_storage(
        kit,
        storage=storage,
        explicit_values=explicit_selector_values,
        env_file_overrides_os_environ=env_file_overrides_os_environ,
        selector_env=selector_env,
        config_group_name=config_group_name,
    )
    registry = storage_diagnosis.registry
    selected_root = (
        storage_diagnosis.selection.root
        if storage_diagnosis.selection is not None
        else None
    )
    warnings = [
        *config_package_convention_warnings(kit),
        *registry.warnings,
        *legacy_file_warnings(kit.spec, storage_root=selected_root),
    ]
    issues = list(
        dict.fromkeys(
            [
                *user_dotenv.issues,
                *registry.issues,
                *storage_diagnosis.issues,
            ]
        )
    )
    status = doctor_status(
        user_dotenv=user_dotenv,
        registry=registry,
        storage=storage_diagnosis,
    )
    selection = storage_diagnosis.selection
    configured_selected_storage = (
        registry.registry.selected_storage
        if registry.registry is not None
        else None
    )
    return ConfigDoctorPayload(
        status=status.value,
        writes="none",
        storage_enabled=kit.spec.uses_storage(),
        apprc_dir=str(paths.root),
        apprc_dir_env_key=kit.spec.apprc_dir_env_key,
        apprc_dir_env_value=registry.env_value,
        apprc_dir_exists=paths.root.is_dir(),
        user_dotenv=str(paths.user_dotenv),
        user_dotenv_exists=paths.user_dotenv.is_file(),
        storage_selector_env_key=kit.spec.storage_selector_env_key,
        apprc_toml=str(paths.apprc_toml),
        apprc_toml_exists=registry.exists,
        apprc_toml_parse_ok=registry.parse_ok,
        apprc_toml_error=registry.error,
        storage_count=registry.storage_count,
        configured_selected_storage=configured_selected_storage,
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
                kit,
                status,
                config_group_name=config_group_name,
                storage_count=registry.storage_count,
                selector_error=storage_diagnosis.selector_error,
            )
        ),
    )
