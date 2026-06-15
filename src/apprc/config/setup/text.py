"""User-facing setup workflow text helpers."""

from __future__ import annotations

# == Standard Library ========================
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

# == Internal ================================
from apprc.config.storage.registry import StorageRegistry, ordered_storage_names

if TYPE_CHECKING:
    from apprc.config.kit import AppConfigKit


@dataclass(frozen=True, slots=True)
class ConfigSetupPaths:
    """Important AppRC TOML paths shown during setup.

    :param active: AppRC TOML path selected by the environment.
    :param env_key: Environment variable that selects the AppRC TOML path.
    """

    active: Path | None
    env_key: str


def setup_paths(kit: "AppConfigKit") -> ConfigSetupPaths:
    """Return the AppRC TOML paths and override variable used by setup.

    :param kit: Application config facade.
    :return: Paths and env var displayed by setup UIs.
    """
    return ConfigSetupPaths(
        active=kit.optional_apprc_toml_path(),
        env_key=kit.apprc_toml_env_key(),
    )


def setup_overview_text(kit: "AppConfigKit") -> str:
    """Return the intro copy for setup UIs.

    :param kit: Application config facade.
    :return: Host-app-specific setup explanation.
    """
    paths = setup_paths(kit)
    active_text = str(paths.active) if paths.active is not None else "<not set>"
    return (
        f"{kit.spec.display_name} needs one active storage root selected by "
        f"{kit.spec.storage_env_key}. Optional multi-storage management adds "
        "one small AppRC TOML to remember named storage roots. The AppRC TOML "
        "does not contain storage data.\n\n"
        f"{paths.env_key} is optional. When it is set, AppRC uses it for "
        "registry-backed listing, switching, archiving, and restoring.\n\n"
        "Setup starts by choosing the active storage root, then asks whether "
        "to enable multi-storage.\n\n"
        f"Current AppRC TOML value:\n{active_text}"
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
        "The derived AppRC TOML stores AppRC state: registered storage names, "
        "storage root paths, and archive restore metadata.\n\n"
        f"{kit.apprc_toml_env_key()} must point at the full AppRC TOML path "
        "in future shells only when multi-storage management is enabled. "
        "Setup asks for the directory so the file name stays consistent."
        f"{suggested_text}{computed}\n\n"
        f"After setup, keep {kit.spec.storage_env_key} exported as the active "
        "storage selector. It may be a registered storage name or an explicit "
        "storage path. Setup prints export commands but does not edit shell "
        "startup files."
    )


def storage_root_step_text(kit: "AppConfigKit") -> str:
    """Return the explanation shown before choosing a storage root.

    :param kit: Application config facade.
    :return: Plain text for CLI and Textual setup UIs.
    """
    return (
        "A storage root is where the application keeps user data and the "
        f"storage-local {kit.spec.local_env_filename} file. Runtime commands "
        f"use {kit.spec.storage_env_key} as the active storage selector. "
        "Optional multi-storage management can additionally register this "
        "root under a short name."
    )


def existing_registry_text(
    kit: "AppConfigKit",
    registry: StorageRegistry,
) -> str:
    """Return the explanation shown when setup finds a registry.

    :param kit: Application config facade.
    :param registry: Existing registry.
    :return: Plain text summary of available actions.
    """
    body = (
        f"{kit.spec.display_name} found an existing AppRC TOML:\n"
        f"{registry.path}\n\n"
        "Keeping it preserves the registered storage roots. Resetting removes "
        f"only {kit.spec.display_name} AppRC state, not storage directories. "
        "Moving it preserves the registry contents at a new AppRC TOML path."
    )
    rows = existing_registry_rows_text(registry)
    if rows:
        return (
            f"{body}\n\n"
            "The current AppRC TOML has these storages registered:\n"
            f"{rows}"
        )
    return f"{body}\n\nNo live storages are registered yet."


def existing_registry_rows_text(registry: StorageRegistry) -> str:
    """Return a compact storage list for setup screens.

    :param registry: Registry whose live storages should be listed.
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
    :param registry: Registry that would be removed.
    :return: Plain text warning.
    """
    lines = [
        "Storage directories are left untouched. Only the AppRC TOML is "
        f"removed. {kit.spec.display_name} storage directories are not "
        "deleted."
    ]
    if registry.storages:
        lines.insert(
            0,
            "Resetting will orphan these registered storages:\n"
            + existing_registry_rows_text(registry),
        )
    return "\n\n".join(lines)


def storage_root_reuse_text(
    kit: "AppConfigKit",
    storage_root: Path,
    *,
    storage_name: str | None,
    registry_path: Path | None = None,
) -> str:
    """Return the warning for reusing a non-empty storage root.

    :param kit: Application config facade.
    :param storage_root: Existing non-empty storage directory.
    :param storage_name: Optional selector that will point at the directory.
    :param registry_path: AppRC TOML file that will be created or updated.
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
    if registry_path is not None:
        managed_lines.append(f"AppRC TOML: {registry_path}")
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


def next_steps_text(
    kit: "AppConfigKit",
    registry: StorageRegistry | None,
    active_storage_root: Path,
) -> str:
    """Return the environment handoff shown after setup finishes.

    :param kit: Application config facade.
    :param registry: Registry selected by setup when multi-storage is enabled.
    :param active_storage_root: Explicit storage path selected for runtime.
    :return: Newline-delimited setup finish guidance.
    """
    return setup_finish_text(kit, registry, active_storage_root)


def setup_finish_text(
    kit: "AppConfigKit",
    registry: StorageRegistry | None,
    active_storage_root: Path,
) -> str:
    """Return setup completion text with shell and dotenv handoff.

    :param kit: Application config facade.
    :param registry: Registry selected by setup when multi-storage is enabled.
    :param active_storage_root: Explicit storage path selected for runtime.
    :return: Human-facing setup completion guidance.
    """
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
        f"Without {kit.spec.storage_env_key}, {kit.spec.app_name} will report "
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
    :param registry: Registry selected by setup when multi-storage is enabled.
    :param active_storage_root: Explicit storage path selected for runtime.
    :return: Ordered shell export commands.
    """
    commands: list[str] = []
    if registry is not None:
        commands.append(export_apprc_toml_command(kit, registry.path))
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
    :param registry: Registry selected by setup when multi-storage is enabled.
    :param active_storage_root: Explicit storage path selected for runtime.
    :return: Ordered dotenv assignment lines.
    """
    assignments: list[str] = []
    if registry is not None:
        assignments.append(dotenv_apprc_toml_assignment(kit, registry.path))
    assignments.append(
        dotenv_storage_selector_assignment(kit, str(active_storage_root))
    )
    return assignments


def export_apprc_toml_command(
    kit: "AppConfigKit",
    registry_path: Path,
) -> str:
    """Return the shell export command for one custom AppRC TOML path.

    :param kit: Application config facade.
    :param registry_path: Custom AppRC TOML path.
    :return: POSIX shell export command.
    """
    path_text = str(_normalized_apprc_toml_path(registry_path)).replace(
        '"',
        '\\"',
    )
    return f'export {kit.apprc_toml_env_key()}="{path_text}"'


def dotenv_apprc_toml_assignment(
    kit: "AppConfigKit",
    registry_path: Path,
) -> str:
    """Return the dotenv assignment for one custom AppRC TOML path.

    :param kit: Application config facade.
    :param registry_path: Custom AppRC TOML path.
    :return: Dotenv assignment with a quoted path value.
    """
    return _dotenv_assignment(
        kit.apprc_toml_env_key(),
        str(_normalized_apprc_toml_path(registry_path)),
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
    return f'export {kit.spec.storage_env_key}="{selector_text}"'


def dotenv_storage_selector_assignment(
    kit: "AppConfigKit",
    storage_selector: str,
) -> str:
    """Return the dotenv assignment for one active storage selector.

    :param kit: Application config facade.
    :param storage_selector: Storage selector selected for future shells.
    :return: Dotenv assignment with a quoted selector value.
    """
    return _dotenv_assignment(kit.spec.storage_env_key, storage_selector)


def _dotenv_assignment(key: str, value: str) -> str:
    """Return one deterministic dotenv key/value assignment."""
    return f"{key}={json.dumps(value)}"


def _normalized_apprc_toml_path(path: str | Path) -> Path:
    """Return an absolute, user-expanded AppRC TOML path."""
    return Path(path).expanduser().resolve()
