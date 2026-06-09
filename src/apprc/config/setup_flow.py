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
import apprc.config.setup_text as setup_text
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


config_file_step_text = setup_text.config_file_step_text
ConfigSetupPaths = setup_text.ConfigSetupPaths
default_storage_step_text = setup_text.default_storage_step_text
existing_registry_text = setup_text.existing_registry_text
existing_registry_rows_text = setup_text.existing_registry_rows_text
export_config_file_command = setup_text.export_config_file_command
next_steps_text = setup_text.next_steps_text
reset_warning_text = setup_text.reset_warning_text
setup_overview_text = setup_text.setup_overview_text
setup_paths = setup_text.setup_paths
storage_root_reuse_text = setup_text.storage_root_reuse_text


@dataclass(frozen=True, slots=True)
class ConfigSetupResult:
    """Result returned after setup writes or confirms a registry.

    :param registry: Registry selected by setup.
    :param existing_action: Existing-registry action that was applied.
    """

    registry: StorageRegistry
    existing_action: ExistingSetupAction | None = None


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
