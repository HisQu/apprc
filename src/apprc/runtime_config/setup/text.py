"""User-facing setup workflow text helpers."""

from __future__ import annotations

# == Standard Library ========================
import json
from pathlib import Path
from typing import TYPE_CHECKING

# == Internal ================================
from apprc.runtime_config.contract.paths import normalize_apprc_toml_path
from apprc.runtime_config.storage.registry import (
    StorageRegistry,
    ordered_storage_names,
)

if TYPE_CHECKING:
    from apprc.runtime_config.kit import AppConfigKit


def setup_overview_text(kit: "AppConfigKit") -> str:
    """Return the intro copy for setup UIs.

    :param kit: Application config facade.
    :return: Host-app-specific setup explanation.
    """
    storage_env_key = kit.spec.require_storage_env_key()
    apprc_toml_path = kit.spec.apprc_toml_path()
    apprc_toml_path_text = str(apprc_toml_path)
    return (
        f"{kit.spec.display_name} needs one active storage root selected by "
        f"{storage_env_key}. Optional multi-storage management uses "
        "one small AppRC TOML file to remember named storage roots. The AppRC "
        "TOML file does not contain storage data.\n\n"
        f"{kit.spec.apprc_toml_env_key} is optional. Set it only to relocate "
        "the AppRC TOML metadata file; otherwise AppRC uses the platform "
        "config-home default.\n\n"
        "Setup starts by choosing the active storage root, then asks whether "
        "to enable multi-storage.\n\n"
        f"Current AppRC TOML value:\n{apprc_toml_path_text}"
    )


def apprc_dir_step_text(
    kit: "AppConfigKit",
    suggested: Path | None,
) -> str:
    """Return the explanation shown before choosing an AppRC directory.

    :param kit: Application config facade.
    :param suggested: Prefilled AppRC directory, if one is known.
    :return: Plain text for CLI and Textual setup UIs.
    """
    storage_env_key = kit.spec.require_storage_env_key()
    computed = (
        "\n\nDerived AppRC TOML path:\n"
        f"{suggested / kit.spec.apprc_toml_filename}"
        if suggested is not None
        else ""
    )
    suggested_text = (
        f"\n\nCurrent {apprc_dir_label(kit)}:\n{suggested}"
        if suggested is not None
        else ""
    )
    return (
        f"Choose the {apprc_dir_label(kit)}. Setup will create or reuse "
        f"{kit.spec.apprc_toml_filename} inside this directory.\n\n"
        "The derived AppRC TOML file stores AppRC state: registered storage names, "
        "storage root paths, and archive restore metadata.\n\n"
        f"{kit.spec.apprc_toml_env_key} should point at the full AppRC TOML "
        "path only when you want to relocate this metadata file. Setup asks "
        "for the directory so the file name stays consistent."
        f"{suggested_text}{computed}\n\n"
        f"After setup, keep {storage_env_key} exported as the active "
        "storage selector. It may be a registered storage name or an explicit "
        "storage path. Setup prints export commands but does not edit shell "
        "startup files."
    )


def storage_root_step_text(kit: "AppConfigKit") -> str:
    """Return the explanation shown before choosing a storage root.

    :param kit: Application config facade.
    :return: Plain text for CLI and Textual setup UIs.
    """
    storage_env_key = kit.spec.require_storage_env_key()
    return (
        "A storage root is where the application keeps user data and the "
        f"storage-local {kit.spec.local_env_filename} file. Runtime commands "
        f"use {storage_env_key} as the active storage selector. "
        "Optional multi-storage management can additionally register this "
        "root under a short name."
    )


def existing_apprc_toml_text(
    kit: "AppConfigKit",
    registry: StorageRegistry,
) -> str:
    """Return the explanation shown when setup finds an AppRC TOML file.

    :param kit: Application config facade.
    :param registry: Existing storage table.
    :return: Plain text summary of available actions.
    """
    body = (
        f"{kit.spec.display_name} found an existing AppRC TOML file:\n"
        f"{registry.path}\n\n"
        "Keeping it preserves the registered storage roots. Resetting removes "
        f"only {kit.spec.display_name} AppRC state, not storage directories. "
        "Moving it preserves the multi-storage contents at a new path."
    )
    rows = existing_storage_rows_text(registry)
    if rows:
        return (
            f"{body}\n\n"
            "The current AppRC TOML has these storages registered:\n"
            f"{rows}"
        )
    return f"{body}\n\nNo live storages are registered yet."


def existing_storage_rows_text(registry: StorageRegistry) -> str:
    """Return a compact storage list for setup screens.

    :param registry: Storage table whose live storages should be listed.
    :return: Newline-delimited storage rows.
    """
    rows: list[str] = []
    for index, name in enumerate(ordered_storage_names(registry), start=1):
        record = registry.selected(name)
        rows.append(f"{index}. {name}: {record.root}")
    return "\n".join(rows)


def reset_warning_text(
    kit: "AppConfigKit",
    registry: StorageRegistry,
) -> str:
    """Return the reset warning shown before deleting config state.

    :param kit: Application config facade.
    :param registry: Storage table that would be removed.
    :return: Plain text warning.
    """
    lines = [
        "Storage directories are left untouched. Only the AppRC TOML file is "
        f"removed. {kit.spec.display_name} storage directories are not "
        "deleted."
    ]
    if registry.storages:
        lines.insert(
            0,
            "Resetting will orphan these registered storages:\n"
            + existing_storage_rows_text(registry),
        )
    return "\n\n".join(lines)


def storage_root_reuse_text(
    kit: "AppConfigKit",
    storage_root: Path,
    *,
    storage_name: str | None,
    apprc_toml_path: Path | None = None,
) -> str:
    """Return the warning for reusing a non-empty storage root.

    :param kit: Application config facade.
    :param storage_root: Existing non-empty storage directory.
    :param storage_name: Optional selector that will point at the directory.
    :param apprc_toml_path: AppRC TOML file that will be created or updated.
    :return: Plain text warning.
    """
    storage_context = (
        f"{kit.spec.display_name} will reuse this directory for "
        f"{kit.spec.display_name} storage {storage_name!r}."
        if storage_name is not None
        else f"{kit.spec.display_name} will reuse this directory as the "
        "active storage root."
    )
    managed_lines = [
        f"storage-local env: {storage_root / kit.spec.local_env_filename}",
    ]
    if apprc_toml_path is not None:
        managed_lines.append(f"AppRC TOML file: {apprc_toml_path}")
    managed_text = "\n".join(managed_lines)
    return (
        "Storage root exists and is not empty.\n\n"
        f"Storage root:\n{storage_root}\n\n"
        f"{storage_context}\n\n"
        "AppRC-managed files to create or update:\n"
        f"{managed_text}\n\n"
        "Existing files inside the storage root will not be deleted, moved, "
        "or overwritten."
    )


def setup_finish_text(
    kit: "AppConfigKit",
    registry: StorageRegistry | None,
    active_storage_root: Path,
) -> str:
    """Return setup completion text with shell and dotenv handoff.

    :param kit: Application config facade.
    :param registry: Storage table selected when multi-storage is enabled.
    :param active_storage_root: Explicit storage path selected for runtime.
    :return: Human-facing setup completion guidance.
    """
    storage_env_key = kit.spec.require_storage_env_key()
    lines = [
        f"{kit.spec.display_name} setup files are ready.",
        "",
        "Add these to your environment:",
        "",
        "Shell:",
        *[
            f"  {command}"
            for command in shell_export_commands(
                kit,
                registry,
                active_storage_root,
            )
        ],
        "",
        "Or Dotenv:",
        *[
            f"  {assignment}"
            for assignment in dotenv_assignment_commands(
                kit,
                registry,
                active_storage_root,
            )
        ],
        "",
        f"Without {storage_env_key}, {kit.spec.app_name} will report "
        "env_not_set in config doctor.",
        "",
        "Then verify:",
        *[f"  {command}" for command in verification_commands(kit)],
    ]
    return "\n".join(lines)


def verification_commands(kit: "AppConfigKit") -> list[str]:
    """Return commands users can run after exporting setup env vars.

    :param kit: Application config facade.
    :return: Ordered verification and editor commands.
    """
    command_name = kit.spec.config_command_name()
    return [
        f"{command_name} config edit",
        f"{command_name} config show",
        f"{command_name} config doctor",
    ]


def shell_export_commands(
    kit: "AppConfigKit",
    registry: StorageRegistry | None,
    active_storage_root: Path,
) -> list[str]:
    """Return POSIX shell exports needed to activate this setup.

    :param kit: Application config facade.
    :param registry: Storage table selected when multi-storage is enabled.
    :param active_storage_root: Explicit storage path selected for runtime.
    :return: Ordered shell export commands.
    """
    commands: list[str] = []
    custom_apprc_toml_path = custom_apprc_toml_path_for_export(
        kit,
        registry,
    )
    if custom_apprc_toml_path is not None:
        commands.append(export_apprc_toml_command(kit, custom_apprc_toml_path))
    commands.append(
        export_storage_selector_command(kit, str(active_storage_root))
    )
    return commands


def dotenv_assignment_commands(
    kit: "AppConfigKit",
    registry: StorageRegistry | None,
    active_storage_root: Path,
) -> list[str]:
    """Return dotenv assignments needed to activate this setup.

    :param kit: Application config facade.
    :param registry: Storage table selected when multi-storage is enabled.
    :param active_storage_root: Explicit storage path selected for runtime.
    :return: Ordered dotenv assignment lines.
    """
    assignments: list[str] = []
    custom_apprc_toml_path = custom_apprc_toml_path_for_export(
        kit,
        registry,
    )
    if custom_apprc_toml_path is not None:
        assignments.append(
            dotenv_apprc_toml_assignment(kit, custom_apprc_toml_path)
        )
    assignments.append(
        dotenv_storage_selector_assignment(kit, str(active_storage_root))
    )
    return assignments


def custom_apprc_toml_path_for_export(
    kit: "AppConfigKit",
    registry: StorageRegistry | None,
) -> Path | None:
    """Return a custom AppRC TOML path that future shells must export.

    :param kit: Application config facade.
    :param registry: Storage table selected when multi-storage is enabled.
    :return: Normalized custom path, or ``None`` for the config-home default.
    """
    if registry is None:
        return None
    registry_path = normalize_apprc_toml_path(registry.path)
    default_path = normalize_apprc_toml_path(kit.spec.default_apprc_toml_path())
    if registry_path == default_path:
        return None
    return registry_path


def export_apprc_toml_command(
    kit: "AppConfigKit",
    apprc_toml_path: Path,
) -> str:
    """Return the shell export command for one custom AppRC TOML path.

    :param kit: Application config facade.
    :param apprc_toml_path: Custom AppRC TOML path.
    :return: POSIX shell export command.
    """
    path_text = str(normalize_apprc_toml_path(apprc_toml_path)).replace(
        '"',
        '\\"',
    )
    return f'export {kit.spec.apprc_toml_env_key}="{path_text}"'


def dotenv_apprc_toml_assignment(
    kit: "AppConfigKit",
    apprc_toml_path: Path,
) -> str:
    """Return the dotenv assignment for one custom AppRC TOML path.

    :param kit: Application config facade.
    :param apprc_toml_path: Custom AppRC TOML path.
    :return: Dotenv assignment with a quoted path value.
    """
    return _dotenv_assignment(
        kit.spec.apprc_toml_env_key,
        str(normalize_apprc_toml_path(apprc_toml_path)),
    )


def apprc_dir_label(kit: "AppConfigKit") -> str:
    """Return the user-facing setup directory label.

    :param kit: Application config facade.
    :return: Display-name-specific AppRC directory label.
    """
    return f"{kit.spec.display_name} directory (AppRC)"


def export_storage_selector_command(
    kit: "AppConfigKit",
    storage_selector: str,
) -> str:
    """Return the shell export command for one active storage selector.

    :param kit: Application config facade.
    :param storage_selector: Storage selector selected for future shells.
    :return: POSIX shell export command.
    """
    selector_text = storage_selector.replace(
        '"',
        '\\"',
    )
    return f'export {kit.spec.require_storage_env_key()}="{selector_text}"'


def dotenv_storage_selector_assignment(
    kit: "AppConfigKit",
    storage_selector: str,
) -> str:
    """Return the dotenv assignment for one active storage selector.

    :param kit: Application config facade.
    :param storage_selector: Storage selector selected for future shells.
    :return: Dotenv assignment with a quoted selector value.
    """
    return _dotenv_assignment(
        kit.spec.require_storage_env_key(),
        storage_selector,
    )


def _dotenv_assignment(key: str, value: str) -> str:
    """Return one deterministic dotenv key/value assignment."""
    return f"{key}={json.dumps(value)}"
