"""User-facing setup workflow text helpers."""

from __future__ import annotations

# == Standard Library ========================
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

# == Internal ================================
from apprc.config.storage_registry import StorageRegistry, ordered_storage_names

if TYPE_CHECKING:
    from apprc.config.kit import AppConfigKit


@dataclass(frozen=True, slots=True)
class ConfigSetupPaths:
    """Important registry paths shown during setup.

    :param active: AppRC TOML path selected by the environment.
    :param env_key: Environment variable that selects the AppRC TOML path.
    """

    active: Path | None
    env_key: str


def setup_paths(kit: "AppConfigKit") -> ConfigSetupPaths:
    """Return the registry paths and override variable used by setup.

    :param kit: Application config facade.
    :return: Paths and env var displayed by setup UIs.
    """
    return ConfigSetupPaths(
        active=kit.optional_registry_path(),
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
        f"{kit.spec.display_name} uses one small AppRC TOML to remember "
        "named storage directories and which storage is the default. The "
        "AppRC TOML does not contain your storage data; it only points to "
        "storage roots.\n\n"
        f"{kit.spec.display_name} expects this variable to point at that "
        f"TOML file:\n{paths.env_key}\n\n"
        f"{kit.spec.storage_env_key} selects the active storage name or path "
        "while commands are running.\n\n"
        "If it is not set yet, setup will ask where the new or existing "
        f"{kit.spec.apprc_toml_filename} file should live.\n\n"
        f"Current value:\n{active_text}"
    )


def apprc_toml_step_text(
    kit: "AppConfigKit",
    suggested: Path | None,
) -> str:
    """Return the explanation shown before choosing a registry path.

    :param kit: Application config facade.
    :param suggested: Prefilled AppRC TOML path, if one is known.
    :return: Plain text for CLI and Textual setup UIs.
    """
    suggested_text = (
        f"\n\nCurrent path:\n{suggested}" if suggested is not None else ""
    )
    return (
        "This TOML file stores the storage registry: storage names, storage "
        "root paths, and the default storage.\n\n"
        f"{kit.spec.display_name} expects {kit.apprc_toml_env_key()} to point "
        f"at this file in future shells, so setup needs a path to a new or "
        f"existing {kit.spec.apprc_toml_filename} file."
        f"{suggested_text}\n\n"
        f"{kit.spec.display_name} setup prints the export command when it "
        "finishes, but it does not edit shell startup files. "
        f"{kit.spec.storage_env_key} is the active storage selector for the "
        "current shell."
    )


def default_storage_step_text(kit: "AppConfigKit") -> str:
    """Return the explanation shown before choosing a storage root.

    :param kit: Application config facade.
    :return: Plain text for CLI and Textual setup UIs.
    """
    return (
        "A storage root is where the application keeps user data and the "
        f"storage-local {kit.spec.local_env_filename} file. The registry can "
        "remember many named storages, but setup makes one default so normal "
        "commands work without --storage."
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
            "The current config has these storages registered:\n"
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
        default = " [default]" if name == registry.default_storage else ""
        rows.append(f"{index}. {name}{default}: {record.root}")
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
    storage_name: str,
    make_default: bool,
    registry_path: Path | None = None,
) -> str:
    """Return the warning for reusing a non-empty storage root.

    :param kit: Application config facade.
    :param storage_root: Existing non-empty storage directory.
    :param storage_name: Registry selector that will point at the directory.
    :param make_default: Whether the selector will become the default.
    :param registry_path: Registry file that will be created or updated.
    :return: Plain text warning.
    """
    active_registry_path = registry_path or kit.registry_path()
    default_line = (
        f"\n\nDefault storage: {storage_name}" if make_default else ""
    )
    return (
        "Directory exists and is not empty.\n\n"
        f"Path:\n{storage_root}\n\n"
        f"{kit.spec.display_name} will reuse this directory for "
        f"{kit.spec.display_name} storage {storage_name!r}.\n\n"
        "Config files to create or update:\n"
        f"storage-local env: {storage_root / kit.spec.local_env_filename}\n"
        f"user registry: {active_registry_path}\n\n"
        "No existing files will be deleted, moved, or overwritten."
        f"{default_line}"
    )


def next_steps_text(kit: "AppConfigKit", registry: StorageRegistry) -> str:
    """Return commands to show after setup finishes.

    :param kit: Application config facade.
    :param registry: Registry selected by setup.
    :return: Newline-delimited commands and export guidance.
    """
    command_name = kit.spec.config_command_name()
    lines = [
        f"{command_name} config edit",
        f"{command_name} config show",
        f"{command_name} config doctor",
    ]
    export_commands = [export_apprc_toml_command(kit, registry.path)]
    default_storage = registry.default()
    if default_storage is not None:
        export_commands.append(
            export_storage_root_command(kit, default_storage.root)
        )
    export_label = (
        "these variables" if len(export_commands) > 1 else "this variable"
    )
    lines.append(
        f"Keep {export_label} exported for future shells:\n"
        + "\n".join(export_commands)
    )
    return "\n".join(lines)


def export_apprc_toml_command(
    kit: "AppConfigKit",
    registry_path: Path,
) -> str:
    """Return the shell export command for one custom AppRC TOML path.

    :param kit: Application config facade.
    :param registry_path: Custom registry path.
    :return: POSIX shell export command.
    """
    path_text = str(_normalized_apprc_toml_path(registry_path)).replace(
        '"',
        '\\"',
    )
    return f'export {kit.apprc_toml_env_key()}="{path_text}"'


def export_storage_root_command(
    kit: "AppConfigKit",
    storage_root: Path,
) -> str:
    """Return the shell export command for one active storage root.

    :param kit: Application config facade.
    :param storage_root: Storage root selected as active for future shells.
    :return: POSIX shell export command.
    """
    path_text = str(Path(storage_root).expanduser().resolve()).replace(
        '"',
        '\\"',
    )
    return f'export {kit.spec.storage_env_key}="{path_text}"'


def _normalized_apprc_toml_path(path: str | Path) -> Path:
    """Return an absolute, user-expanded AppRC TOML path."""
    return Path(path).expanduser().resolve()
