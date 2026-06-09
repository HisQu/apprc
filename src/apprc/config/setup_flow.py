"""Shared config setup workflow helpers."""

from __future__ import annotations

# == Standard Library ========================
import os
import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

# == Internal ================================
from apprc.config.paths import StorageRootPathError, normalize_storage_root_path
from apprc.config.storage_registry import StorageRegistry

if TYPE_CHECKING:
    from apprc.config.kit import AppConfigKit


class ExistingSetupAction(str, Enum):
    """Actions available when setup finds an existing registry."""

    KEEP = "keep"
    RESET = "reset"
    MOVE = "move"


class ConfigSetupError(ValueError):
    """Readable setup failure with optional CLI parameter context.

    :param message: Human-facing error text.
    :param param_hint: Optional Typer parameter hint for CLI callers.
    :param exit_code: Optional CLI exit code for non-parameter refusals.
    """

    def __init__(
        self,
        message: str,
        *,
        param_hint: str | None = None,
        exit_code: int | None = None,
    ) -> None:
        """Store the message and CLI parameter hint."""
        super().__init__(message)
        self.param_hint = param_hint
        self.exit_code = exit_code


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


@dataclass(frozen=True, slots=True)
class ConfigSetupResult:
    """Result returned after setup writes or confirms a registry.

    :param registry: Registry selected by setup.
    :param existing_action: Existing-registry action that was applied.
    """

    registry: StorageRegistry
    existing_action: ExistingSetupAction | None = None


def setup_paths(kit: "AppConfigKit") -> ConfigSetupPaths:
    """Return the registry paths and override variable used by setup.

    :param kit: Application config facade.
    :return: Paths and env var displayed by setup UIs.
    """
    return ConfigSetupPaths(
        automatic=normalized_config_file_path(kit.default_registry_path()),
        active=normalized_config_file_path(kit.registry_path()),
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
    lines = [
        f"{kit.spec.app_name} config edit",
        f"{kit.spec.app_name} config show",
        f"{kit.spec.app_name} config doctor",
    ]
    if not same_path(registry.path, kit.default_registry_path()):
        lines.append(
            "Keep this variable exported for future shells:\n"
            f"{export_config_file_command(kit, registry.path)}"
        )
    return "\n".join(lines)


def find_existing_registry_path(kit: "AppConfigKit") -> Path | None:
    """Return the registry path setup should treat as already configured.

    :param kit: Application config facade.
    :return: Existing active/default registry path, or ``None``.
    """
    active_path = normalized_config_file_path(kit.registry_path())
    if active_path.is_file():
        return active_path

    default_path = normalized_config_file_path(kit.default_registry_path())
    if not same_path(active_path, default_path) and default_path.is_file():
        return default_path
    return None


def default_existing_setup_action(
    registry_path: Path,
    active_path: Path,
) -> ExistingSetupAction:
    """Return the safest existing-registry action for default setup.

    :param registry_path: Existing registry found by setup.
    :param active_path: Registry path selected for this process.
    :return: ``MOVE`` when an env-selected target differs, else ``KEEP``.
    """
    if not same_path(registry_path, active_path):
        return ExistingSetupAction.MOVE
    return ExistingSetupAction.KEEP


def prepare_setup_registry(
    kit: "AppConfigKit",
    *,
    config_file_path: Path | None,
    existing_action: ExistingSetupAction | None,
    replace_existing_file: bool,
) -> ConfigSetupResult:
    """Select, reset, or move the registry used by setup.

    :param kit: Application config facade.
    :param config_file_path: Optional explicit target registry path.
    :param existing_action: Optional action for a discovered registry.
    :param replace_existing_file: Whether an existing move target may be
        replaced.
    :return: Selected registry and action metadata.
    :raises ConfigSetupError: If the requested path cannot be rediscovered.
    """
    target_path = normalized_config_file_path(
        config_file_path or kit.registry_path()
    )
    existing_path = find_existing_registry_path(kit)
    if existing_path is None:
        require_registry_path_available(kit, target_path)
        return ConfigSetupResult(registry=load_registry(kit, target_path))

    action = existing_action or default_existing_setup_action(
        existing_path,
        normalized_config_file_path(kit.registry_path()),
    )
    if action == ExistingSetupAction.KEEP:
        require_registry_path_available(kit, existing_path)
        return ConfigSetupResult(
            registry=load_registry(kit, existing_path),
            existing_action=action,
        )
    if action == ExistingSetupAction.RESET:
        remove_registry_config_state(kit, existing_path)
        require_registry_path_available(kit, target_path)
        return ConfigSetupResult(
            registry=load_registry(kit, target_path),
            existing_action=action,
        )

    require_registry_path_available(kit, target_path)
    registry = move_existing_registry(
        kit,
        source_path=existing_path,
        target_path=target_path,
        replace_existing_file=replace_existing_file,
    )
    return ConfigSetupResult(registry=registry, existing_action=action)


def ensure_default_storage(
    kit: "AppConfigKit",
    registry: StorageRegistry,
    *,
    storage_name: str | None,
    storage_root: Path | None,
    allow_non_empty_storage: bool,
) -> StorageRegistry:
    """Ensure a live default storage exists after registry setup.

    :param kit: Application config facade.
    :param registry: Registry selected by setup.
    :param storage_name: Optional selector to register as the default.
    :param storage_root: Optional storage root to register as the default.
    :param allow_non_empty_storage: Whether non-empty roots may be reused.
    :return: Registry with a live default storage.
    :raises ConfigSetupError: If the storage root is unsafe.
    """
    current_default = registry.default()
    explicit_storage = storage_name is not None or storage_root is not None
    if (
        current_default is not None
        and current_default.root.is_dir()
        and not explicit_storage
    ):
        return registry

    name = (
        storage_name or registry.default_storage or kit.default_storage_name()
    )
    root = validate_storage_root_for_setup(
        kit,
        storage_root or kit.default_storage_data_root(),
        storage_name=name,
        make_default=True,
        allow_non_empty_storage=allow_non_empty_storage,
    )
    try:
        return kit.register_storage(
            name=name,
            root=root,
            make_default=True,
            path=registry.path,
        )
    except StorageRootPathError as exc:
        raise ConfigSetupError(
            str(exc),
            param_hint="STORAGE_ROOT",
        ) from exc
    except ValueError as exc:
        raise ConfigSetupError(
            str(exc),
            param_hint="Storage name",
        ) from exc


def validate_storage_root_for_setup(
    kit: "AppConfigKit",
    storage_root: Path,
    *,
    storage_name: str,
    make_default: bool,
    allow_non_empty_storage: bool,
) -> Path:
    """Return a safe storage root path before registration writes.

    :param kit: Application config facade.
    :param storage_root: User-provided storage root path.
    :param storage_name: Registry selector that will point at the directory.
    :param make_default: Whether the selector will become the default.
    :param allow_non_empty_storage: Whether to reuse non-empty directories.
    :return: Normalized storage root path.
    :raises ConfigSetupError: If the path cannot be safely used.
    """
    try:
        root = normalize_storage_root_path(storage_root)
    except StorageRootPathError as exc:
        raise ConfigSetupError(
            str(exc),
            param_hint="STORAGE_ROOT",
        ) from exc
    if not root.exists():
        return root
    resolved_root = root.resolve()
    if not resolved_root.is_dir():
        raise ConfigSetupError(
            f"Storage root exists but is not a directory: {resolved_root}",
            param_hint="STORAGE_ROOT",
        )
    if allow_non_empty_storage or not any(resolved_root.iterdir()):
        return resolved_root
    raise ConfigSetupError(
        storage_root_reuse_text(
            kit,
            resolved_root,
            storage_name=storage_name,
            make_default=make_default,
        ),
        param_hint="STORAGE_ROOT",
    )


def require_registry_path_available(
    kit: "AppConfigKit",
    registry_path: Path,
) -> None:
    """Reject config-file paths future commands cannot rediscover.

    :param kit: Application config facade.
    :param registry_path: Requested registry path.
    :raises ConfigSetupError: If the env override does not select the path.
    """
    default_path = normalized_config_file_path(kit.default_registry_path())
    if same_path(registry_path, default_path):
        raw_override = os.environ.get(kit.config_file_env_key(), "").strip()
        if raw_override and not same_path(raw_override, default_path):
            raise ConfigSetupError(
                "The config-file override is active.\n"
                "Unset it before using the automatic path:\n"
                f"unset {kit.config_file_env_key()}",
                param_hint="CONFIG_FILE",
                exit_code=1,
            )
        return

    if env_path_matches(kit, registry_path):
        return

    raise ConfigSetupError(
        "Custom config-file paths require an environment variable.\n"
        "Run setup again with this variable exported so future commands use "
        "the same file:\n"
        f"{export_config_file_command(kit, registry_path)}",
        param_hint="CONFIG_FILE",
        exit_code=1,
    )


def remove_registry_config_state(
    kit: "AppConfigKit",
    registry_path: Path,
) -> None:
    """Delete only config files, never registered storage roots.

    :param kit: Application config facade.
    :param registry_path: Registry file to remove.
    """
    default_dir = normalized_config_file_path(
        kit.default_registry_path()
    ).parent
    resolved_registry_path = normalized_config_file_path(registry_path)
    if resolved_registry_path.is_relative_to(default_dir):
        shutil.rmtree(default_dir, ignore_errors=True)
        return
    resolved_registry_path.unlink(missing_ok=True)


def move_existing_registry(
    kit: "AppConfigKit",
    *,
    source_path: Path,
    target_path: Path,
    replace_existing_file: bool,
) -> StorageRegistry:
    """Move an existing registry file and load it from its new path.

    :param kit: Application config facade.
    :param source_path: Existing registry file.
    :param target_path: Destination registry file.
    :param replace_existing_file: Whether an existing file may be replaced.
    :return: Loaded registry at the target path.
    :raises ConfigSetupError: If the target cannot be replaced.
    """
    source = normalized_config_file_path(source_path)
    target = normalized_config_file_path(target_path)
    if same_path(source, target):
        return load_registry(kit, target)
    if target.exists():
        if target.is_dir():
            raise ConfigSetupError(
                f"Config file target is a directory: {target}",
                param_hint="CONFIG_FILE",
            )
        if not replace_existing_file:
            raise ConfigSetupError(
                f"Config file target already exists: {target}",
                param_hint="CONFIG_FILE",
            )
        target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    return load_registry(kit, target)


def load_registry(
    kit: "AppConfigKit",
    registry_path: Path,
) -> StorageRegistry:
    """Load a registry and convert parse failures to setup errors.

    :param kit: Application config facade.
    :param registry_path: Registry path to load.
    :return: Parsed or empty registry.
    :raises ConfigSetupError: If the registry cannot be parsed.
    """
    try:
        return kit.load_registry(path=registry_path)
    except ValueError as exc:
        raise ConfigSetupError(
            str(exc),
            param_hint=str(registry_path),
        ) from exc


def ordered_storage_names(registry: StorageRegistry) -> list[str]:
    """Return default storage first, then remaining storages by name.

    :param registry: Registry whose storage names should be ordered.
    :return: Stable display order.
    """
    names = sorted(registry.storages)
    default_name = registry.default_storage
    if default_name in names:
        names.remove(default_name)
        names.insert(0, default_name)
    return names


def env_path_matches(kit: "AppConfigKit", registry_path: Path) -> bool:
    """Return whether the override env var points at ``registry_path``.

    :param kit: Application config facade.
    :param registry_path: Registry path to compare.
    :return: Whether the active env override matches the path.
    """
    raw_override = os.environ.get(kit.config_file_env_key(), "").strip()
    if not raw_override:
        return False
    return same_path(raw_override, registry_path)


def export_config_file_command(
    kit: "AppConfigKit",
    registry_path: Path,
) -> str:
    """Return the shell export command for one custom config file path.

    :param kit: Application config facade.
    :param registry_path: Custom registry path.
    :return: POSIX shell export command.
    """
    path_text = str(normalized_config_file_path(registry_path)).replace(
        '"',
        '\\"',
    )
    return f'export {kit.config_file_env_key()}="{path_text}"'


def same_path(left: str | Path, right: str | Path) -> bool:
    """Return whether two path spellings identify the same filesystem path.

    :param left: First path spelling.
    :param right: Second path spelling.
    :return: Whether both normalize to the same absolute path.
    """
    return normalized_config_file_path(left) == normalized_config_file_path(
        right
    )


def normalized_config_file_path(path: str | Path) -> Path:
    """Return an absolute, user-expanded config file path.

    :param path: User-provided registry path.
    :return: Absolute path spelling.
    """
    return Path(path).expanduser().resolve()
