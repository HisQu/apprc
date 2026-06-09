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

    :param automatic: Default config file path before environment overrides.
    :param active: Config file path selected for this process.
    :param env_key: Environment variable that overrides the config file path.
    """

    automatic: Path
    active: Path
    env_key: str


def setup_paths(kit: "AppConfigKit") -> ConfigSetupPaths:
    """Return the registry paths and override variable used by setup.

    :param kit: Application config facade.
    :return: Paths and env var displayed by setup UIs.
    """
    return ConfigSetupPaths(
        automatic=_normalized_config_file_path(kit.default_registry_path()),
        active=_normalized_config_file_path(kit.registry_path()),
        env_key=kit.config_file_env_key(),
    )


def setup_overview_text(kit: "AppConfigKit") -> str:
    """Return the intro copy for setup UIs.

    :param kit: Application config facade.
    :return: Host-app-specific setup explanation.
    """
    paths = setup_paths(kit)
    return (
        f"{kit.spec.display_name} uses one small TOML config file to remember "
        "named storage directories and which storage is the default. The "
        "config file does not contain your storage data; it only points to "
        "storage roots.\n\n"
        f"Automatic config file:\n{paths.automatic}\n\n"
        f"Override variable:\n{paths.env_key}\n\n"
        f"Active config file for this process:\n{paths.active}"
    )


def config_file_step_text(kit: "AppConfigKit", suggested: Path) -> str:
    """Return the explanation shown before choosing a registry path.

    :param kit: Application config facade.
    :param suggested: Prefilled config file path.
    :return: Plain text for CLI and Textual setup UIs.
    """
    return (
        "This TOML file stores the storage registry: storage names, storage "
        "root paths, and the default storage. It is small and safe to keep in "
        "your normal per-user config directory.\n\n"
        f"Suggested path:\n{suggested}\n\n"
        f"To use any custom path, start the command with "
        f"{kit.config_file_env_key()} pointing at that exact file. "
        f"{kit.spec.display_name} setup does not edit shell startup files."
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
        f"{kit.spec.display_name} found an existing config file:\n"
        f"{registry.path}\n\n"
        "Keeping it preserves the registered storage roots. Resetting removes "
        f"only {kit.spec.display_name} config state, not storage directories. "
        "Moving it preserves the registry contents at a new config-file path."
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
        "Storage directories are left untouched. Only the config file is "
        "removed. When it lives below the automatic config directory, that "
        f"{kit.spec.display_name} config directory is removed too."
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
) -> str:
    """Return the warning for reusing a non-empty storage root.

    :param kit: Application config facade.
    :param storage_root: Existing non-empty storage directory.
    :param storage_name: Registry selector that will point at the directory.
    :param make_default: Whether the selector will become the default.
    :return: Plain text warning.
    """
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
        f"user registry: {kit.registry_path()}\n\n"
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
    if not _same_path(registry.path, kit.default_registry_path()):
        lines.append(
            "Keep this variable exported for future shells:\n"
            f"{export_config_file_command(kit, registry.path)}"
        )
    return "\n".join(lines)


def export_config_file_command(
    kit: "AppConfigKit",
    registry_path: Path,
) -> str:
    """Return the shell export command for one custom config file path.

    :param kit: Application config facade.
    :param registry_path: Custom registry path.
    :return: POSIX shell export command.
    """
    path_text = str(_normalized_config_file_path(registry_path)).replace(
        '"',
        '\\"',
    )
    return f'export {kit.config_file_env_key()}="{path_text}"'


def _same_path(left: str | Path, right: str | Path) -> bool:
    """Return whether two path spellings identify the same filesystem path."""
    return _normalized_config_file_path(left) == _normalized_config_file_path(
        right
    )


def _normalized_config_file_path(path: str | Path) -> Path:
    """Return an absolute, user-expanded config file path."""
    return Path(path).expanduser().resolve()
