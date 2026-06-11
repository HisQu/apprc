"""Build AppRC setup diagnostics independent of CLI rendering."""

from __future__ import annotations

# == Standard Library ========================
import os
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

# == Internal ================================
from apprc.config.install_state import ConfigInstallState
from apprc.config.storage_selector import (
    StorageSelection,
    StorageSelectorError,
    resolve_active_storage_selection,
)

if TYPE_CHECKING:
    from apprc.config.kit import AppConfigKit


class ConfigDoctorPayload(TypedDict):
    """Machine-readable diagnostics emitted by ``config doctor``."""

    ok: bool
    install_state: str
    installed: bool
    healthy: bool
    apprc_toml_env_key: str
    apprc_toml_env_value: str | None
    apprc_toml_path: str | None
    apprc_toml_exists: bool
    apprc_toml_parse_ok: bool
    apprc_toml_error: str | None
    storage_count: int
    default_storage: str | None
    selected_storage: str | None
    selected_storage_source: str | None
    selected_storage_selector: str | None
    selected_storage_root: str | None
    selected_storage_root_exists: bool | None
    selected_local_env: str | None
    selected_local_env_exists: bool | None
    issues: list[str]
    next_steps: list[str]


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
    setup_action = "setup --yes --apprc-dir /absolute/path/to/config-dir"
    return (
        f"No {kit.spec.display_name} AppRC TOML is installed yet.\n\n"
        f"{kit.spec.display_name} expects {kit.apprc_toml_env_key()} to point "
        "at its AppRC TOML, and "
        f"{storage_key} to track the active storage selector.\n"
        "Choose where that file's directory should live, then run setup:\n"
        f"  {config_command_text(kit, setup_action)}\n\n"
        "Keep both variables exported for future commands, then inspect the setup:\n"
        f"  {config_command_text(kit, 'doctor')}\n"
        f"  {config_command_text(kit, 'show')}\n\n"
        "Setup creates:\n"
        f"  /absolute/path/to/config-dir/{kit.spec.apprc_toml_filename}\n"
        f"  /absolute/path/to/storage-root/{kit.spec.local_env_filename}"
    )


def build_config_doctor_payload(
    kit: "AppConfigKit",
    *,
    storage_name: str | None,
    apprc_toml_path: Path | None = None,
) -> ConfigDoctorPayload:
    """Return local setup diagnostics for one app's AppRC TOML.

    :param kit: Application config facade.
    :param storage_name: Optional registered storage selected by ``--storage``.
    :param apprc_toml_path: Optional explicit AppRC TOML path used by setup.
    :return: Stable JSON-friendly diagnostic payload.
    """
    toml_env_key = kit.apprc_toml_env_key()
    raw_toml_env_value = os.environ.get(toml_env_key, "").strip()
    toml_env_value = raw_toml_env_value or None
    active_toml_path = (
        Path(apprc_toml_path).expanduser().resolve()
        if apprc_toml_path is not None
        else kit.optional_apprc_toml_path()
    )
    issues: list[str] = []
    selection: StorageSelection | None = None
    toml_error: str | None = None
    storage_count = 0
    default_storage: str | None = None
    toml_exists = (
        active_toml_path.is_file() if active_toml_path is not None else False
    )
    install_state = ConfigInstallState.NOT_INSTALLED

    if active_toml_path is None:
        issues.append(
            f"{toml_env_key} is not set. Run "
            f"{config_command_text(kit, 'setup --yes --apprc-dir /absolute/path/to/config-dir')}"
            " and keep the printed export command in your shell setup."
        )
    elif not toml_exists:
        issues.append(f"AppRC TOML does not exist: {active_toml_path}")
    else:
        install_state = ConfigInstallState.INSTALLED_UNHEALTHY
        try:
            registry = kit.load_registry(path=active_toml_path)
        except ValueError as exc:
            toml_error = str(exc)
            issues.append(f"AppRC TOML is invalid: {toml_error}")
        else:
            storage_count = len(registry.storages)
            default_storage = registry.default_storage
            if not registry.storages:
                issues.append(
                    f"No {kit.spec.display_name} storage is registered yet."
                )
            elif registry.default_storage is None:
                issues.append(
                    f"No default {kit.spec.display_name} storage is "
                    "configured. The default is used as the first setup/editor "
                    "selection, not as a runtime fallback. "
                    f"Run {config_command_text(kit, 'set-default NAME')}."
                )

            try:
                selection = resolve_active_storage_selection(
                    registry=registry,
                    storage_name=storage_name,
                    storage_env_key=kit.spec.storage_env_key,
                    original_env=os.environ,
                )
            except StorageSelectorError as exc:
                issues.append(str(exc))
            if selection is None and registry.storages:
                issues.append(
                    f"{kit.spec.storage_env_key} is not set. Export a "
                    "registered storage name or explicit storage path; the "
                    "registry default is not used as a runtime fallback."
                )

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
        issues.append(f"Storage root does not exist: {selected_storage_root}")
    if local_env is not None and not local_env_exists:
        issues.append(f"Storage local env file does not exist: {local_env}")

    if toml_exists and not issues:
        install_state = ConfigInstallState.INSTALLED_HEALTHY
    elif toml_exists:
        install_state = ConfigInstallState.INSTALLED_UNHEALTHY

    healthy = install_state == ConfigInstallState.INSTALLED_HEALTHY
    return {
        "ok": healthy,
        "install_state": install_state.value,
        "installed": install_state != ConfigInstallState.NOT_INSTALLED,
        "healthy": healthy,
        "apprc_toml_env_key": toml_env_key,
        "apprc_toml_env_value": toml_env_value,
        "apprc_toml_path": (
            str(active_toml_path) if active_toml_path is not None else None
        ),
        "apprc_toml_exists": toml_exists,
        "apprc_toml_parse_ok": toml_exists and toml_error is None,
        "apprc_toml_error": toml_error,
        "storage_count": storage_count,
        "default_storage": default_storage,
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
        "selected_storage_root_exists": storage_root_exists,
        "selected_local_env": str(local_env) if local_env is not None else None,
        "selected_local_env_exists": local_env_exists,
        "issues": issues,
        "next_steps": []
        if not issues
        else [
            config_command_text(
                kit,
                "setup --yes --apprc-dir /absolute/path/to/config-dir",
            ),
            config_command_text(kit, "doctor"),
            config_command_text(kit, "show"),
        ],
    }
