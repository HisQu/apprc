"""Shared config setup workflow helpers."""

from __future__ import annotations

# == Standard Library ========================
import shutil
from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
from typing import TYPE_CHECKING

# == Internal ================================
from apprc.config.apprc_toml import normalized_apprc_toml_path
from apprc.config.local_env import ensure_local_env_file
from apprc.config.paths import StorageRootPathError, normalize_storage_root_path
import apprc.config.setup.text as setup_text
from apprc.config.storage.registry import (
    StorageRegistry,
)

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
class ConfigSetupResult:
    """Result returned after setup writes or confirms setup state.

    :param registry: Registry selected by setup when multi-storage is enabled.
    :param active_storage_root: Explicit storage path selected for runtime.
    :param registered_storage_name: Optional registry selector created by setup.
    :param existing_action: Existing-registry action that was applied.
    """

    registry: StorageRegistry | None
    active_storage_root: Path
    registered_storage_name: str | None = None
    existing_action: ExistingSetupAction | None = None


@dataclass(frozen=True, slots=True)
class PreparedSetupRegistry:
    """Registry chosen before the active storage step runs.

    :param registry: Registry selected by setup.
    :param existing_action: Existing-registry action that was applied.
    """

    registry: StorageRegistry
    existing_action: ExistingSetupAction | None = None


def find_existing_apprc_toml_path(kit: "AppConfigKit") -> Path | None:
    """Return the AppRC TOML path setup should treat as already configured.

    :param kit: Application config facade.
    :return: Existing env-selected AppRC TOML path, or ``None``.
    """
    active_path = kit.optional_apprc_toml_path()
    if active_path is not None and active_path.is_file():
        return normalized_apprc_toml_path(active_path)
    return None


def default_existing_setup_action() -> ExistingSetupAction:
    """Return the safest existing-registry action for default setup.

    :return: ``KEEP`` because setup no longer has an automatic move target.
    """
    return ExistingSetupAction.KEEP


def prepare_setup_registry(
    kit: "AppConfigKit",
    *,
    apprc_dir: Path | None,
    existing_action: ExistingSetupAction | None,
    replace_existing_file: bool,
) -> PreparedSetupRegistry:
    """Select, reset, or move the registry used by setup.

    :param kit: Application config facade.
    :param apprc_dir: Optional explicit target AppRC directory.
    :param existing_action: Optional action for a discovered registry.
    :param replace_existing_file: Whether an existing move target may be
        replaced.
    :return: Selected registry and action metadata.
    :raises ConfigSetupError: If the requested path cannot be rediscovered.
    """
    target_path = setup_apprc_toml_path(kit, apprc_dir)
    env_existing_path = find_existing_apprc_toml_path(kit)
    existing_path = _setup_existing_apprc_toml_path(
        target_path=target_path,
        env_existing_path=env_existing_path,
        explicit_apprc_dir=apprc_dir is not None,
        existing_action=existing_action,
    )
    if existing_path is None:
        require_apprc_toml_path_available(target_path)
        return PreparedSetupRegistry(registry=load_registry(kit, target_path))

    action = existing_action or default_existing_setup_action()
    if action == ExistingSetupAction.KEEP:
        require_apprc_toml_path_available(existing_path)
        return PreparedSetupRegistry(
            registry=load_registry(kit, existing_path),
            existing_action=action,
        )
    if action == ExistingSetupAction.RESET:
        remove_apprc_toml_config_state(existing_path)
        require_apprc_toml_path_available(target_path)
        return PreparedSetupRegistry(
            registry=load_registry(kit, target_path),
            existing_action=action,
        )

    require_apprc_toml_path_available(target_path)
    registry = move_existing_apprc_toml(
        kit,
        source_path=existing_path,
        target_path=target_path,
        replace_existing_file=replace_existing_file,
    )
    return PreparedSetupRegistry(registry=registry, existing_action=action)


def _setup_existing_apprc_toml_path(
    *,
    target_path: Path,
    env_existing_path: Path | None,
    explicit_apprc_dir: bool,
    existing_action: ExistingSetupAction | None,
) -> Path | None:
    """Return the existing AppRC TOML setup should operate on.

    :param target_path: AppRC TOML path selected for this setup run.
    :param env_existing_path: Existing env-selected AppRC TOML, if any.
    :param explicit_apprc_dir: Whether ``--apprc-dir`` selected the target.
    :param existing_action: Optional action for an existing AppRC TOML.
    :return: Existing AppRC TOML path, or ``None``.
    """
    if target_path.is_file():
        return target_path
    if not explicit_apprc_dir:
        return env_existing_path
    if existing_action in {
        ExistingSetupAction.MOVE,
        ExistingSetupAction.RESET,
    }:
        return env_existing_path
    return None


def ensure_setup_storage(
    kit: "AppConfigKit",
    registry: StorageRegistry,
    *,
    storage_root: Path | None,
    storage_name: str | None,
    multi_storage: bool,
    allow_non_empty_storage: bool,
) -> ConfigSetupResult:
    """Ensure the active storage root exists after registry setup.

    :param kit: Application config facade.
    :param registry: Registry selected by setup.
    :param storage_root: Optional active storage root selected by setup.
    :param storage_name: Optional selector to register for multi-storage.
    :param multi_storage: Whether to register the active root in the registry.
    :param allow_non_empty_storage: Whether non-empty roots may be reused.
    :return: Setup result with active root and optional registered selector.
    :raises ConfigSetupError: If the storage root is unsafe.
    """
    active_root = storage_root or active_storage_root_from_env(kit)
    if active_root is None:
        raise ConfigSetupError(
            f"{kit.spec.storage_env_key} or --storage-root is required for "
            "non-interactive setup.",
            param_hint="--storage-root",
        )
    name = storage_name or kit.suggested_storage_name()
    root = validate_storage_root_for_setup(
        kit,
        active_root,
        storage_name=name if multi_storage else None,
        allow_non_empty_storage=allow_non_empty_storage,
    )
    try:
        local_env = ensure_local_env_file(
            root,
            filename=kit.spec.local_env_filename,
        )
        resolved_root = local_env.parent
        if not multi_storage:
            return ConfigSetupResult(
                registry=None,
                active_storage_root=resolved_root,
            )
        updated = kit.register_storage(
            name=name,
            root=resolved_root,
            path=registry.path,
        )
        return ConfigSetupResult(
            registry=updated,
            active_storage_root=resolved_root,
            registered_storage_name=name,
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


def ensure_single_storage(
    kit: "AppConfigKit",
    *,
    storage_root: Path | None,
    allow_non_empty_storage: bool,
) -> ConfigSetupResult:
    """Create or confirm the active storage root without a registry.

    :param kit: Application config facade.
    :param storage_root: Optional active storage root selected by setup.
    :param allow_non_empty_storage: Whether non-empty roots may be reused.
    :return: Setup result with no AppRC TOML registry.
    :raises ConfigSetupError: If the storage root is unsafe.
    """
    active_root = storage_root or active_storage_root_from_env(kit)
    if active_root is None:
        raise ConfigSetupError(
            f"{kit.spec.storage_env_key} or --storage-root is required for "
            "non-interactive setup.",
            param_hint="--storage-root",
        )
    root = validate_storage_root_for_setup(
        kit,
        active_root,
        storage_name=None,
        allow_non_empty_storage=allow_non_empty_storage,
    )
    try:
        local_env = ensure_local_env_file(
            root,
            filename=kit.spec.local_env_filename,
        )
    except StorageRootPathError as exc:
        raise ConfigSetupError(
            str(exc),
            param_hint="STORAGE_ROOT",
        ) from exc
    return ConfigSetupResult(
        registry=None,
        active_storage_root=local_env.parent,
    )


def validate_storage_root_for_setup(
    kit: "AppConfigKit",
    storage_root: Path,
    *,
    storage_name: str | None,
    allow_non_empty_storage: bool,
) -> Path:
    """Return a safe storage root path before registration writes.

    :param kit: Application config facade.
    :param storage_root: User-provided storage root path.
    :param storage_name: Optional selector that will point at the directory.
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
        setup_text.storage_root_reuse_text(
            kit,
            resolved_root,
            storage_name=storage_name,
        ),
        param_hint="STORAGE_ROOT",
    )


def active_storage_root_from_env(kit: "AppConfigKit") -> Path | None:
    """Return the active storage root from the setup-time env selector.

    During setup, the storage env value is path-preferred. A bare value such as
    ``alpha`` is treated as a relative path, not as a registry selector.

    :param kit: Application config facade.
    :return: Normalized storage path, or ``None`` when unset.
    :raises ConfigSetupError: If the path cannot be safely interpreted.
    """
    raw_value = os.environ.get(kit.spec.storage_env_key, "").strip()
    if not raw_value:
        return None
    try:
        return normalize_storage_root_path(raw_value)
    except StorageRootPathError as exc:
        raise ConfigSetupError(
            str(exc),
            param_hint=kit.spec.storage_env_key,
        ) from exc


def setup_apprc_toml_path(
    kit: "AppConfigKit",
    apprc_dir: Path | None,
) -> Path:
    """Return the AppRC TOML path selected by setup directory input.

    :param kit: Application config facade.
    :param apprc_dir: Optional setup ``--apprc-dir`` value.
    :return: Normalized AppRC TOML path setup should write.
    :raises ConfigSetupError: If no path was provided or exported.
    """
    if apprc_dir is not None:
        return setup_apprc_toml_path_from_dir(kit, apprc_dir)
    active_path = kit.optional_apprc_toml_path()
    if active_path is not None:
        return normalized_apprc_toml_path(active_path)
    raise ConfigSetupError(
        f"{kit.spec.display_name} setup needs the "
        f"{kit.spec.display_name} directory (AppRC) because "
        f"{kit.apprc_toml_env_key()} is not set.\n"
        "Run setup again with an explicit directory:\n"
        f"{kit.spec.config_command_name()} config setup --yes "
        "--apprc-dir /absolute/path/to/config-dir",
        param_hint="--apprc-dir",
    )


def setup_apprc_toml_dir(apprc_dir: Path) -> Path:
    """Return a normalized setup directory after validating its type.

    :param apprc_dir: User-provided AppRC directory.
    :return: Absolute, user-expanded directory path.
    :raises ConfigSetupError: If the path exists but is not a directory.
    """
    path = Path(apprc_dir).expanduser().resolve()
    if path.exists() and not path.is_dir():
        raise ConfigSetupError(
            f"AppRC directory is not a directory: {path}",
            param_hint="APPRC_DIR",
        )
    return path


def setup_apprc_toml_path_from_dir(
    kit: "AppConfigKit",
    apprc_dir: Path,
) -> Path:
    """Return the enforced AppRC TOML file inside a setup directory.

    :param kit: Application config facade.
    :param apprc_dir: User-provided AppRC directory.
    :return: Computed AppRC TOML path.
    :raises ConfigSetupError: If the directory path is invalid.
    """
    return setup_apprc_toml_dir(apprc_dir) / kit.spec.apprc_toml_filename


def require_apprc_toml_path_available(
    apprc_toml_path: Path,
) -> None:
    """Reject AppRC TOML targets that cannot be written as files.

    :param apprc_toml_path: Requested AppRC TOML path.
    :raises ConfigSetupError: If the path is an existing directory.
    """
    path = normalized_apprc_toml_path(apprc_toml_path)
    if not path.exists() or path.is_file():
        return
    raise ConfigSetupError(
        f"AppRC TOML target is not a file: {path}",
        param_hint="APPRC_TOML",
    )


def remove_apprc_toml_config_state(apprc_toml_path: Path) -> None:
    """Delete only AppRC TOML state, never registered storage roots.

    :param apprc_toml_path: AppRC TOML file to remove.
    """
    resolved_apprc_toml_path = normalized_apprc_toml_path(apprc_toml_path)
    resolved_apprc_toml_path.unlink(missing_ok=True)


def move_existing_apprc_toml(
    kit: "AppConfigKit",
    *,
    source_path: Path,
    target_path: Path,
    replace_existing_file: bool,
) -> StorageRegistry:
    """Move an existing AppRC TOML file and load it from its new path.

    :param kit: Application config facade.
    :param source_path: Existing AppRC TOML file.
    :param target_path: Destination AppRC TOML file.
    :param replace_existing_file: Whether an existing file may be replaced.
    :return: Loaded registry at the target path.
    :raises ConfigSetupError: If the target cannot be replaced.
    """
    source = normalized_apprc_toml_path(source_path)
    target = normalized_apprc_toml_path(target_path)
    if same_path(source, target):
        return load_registry(kit, target)
    if target.exists():
        if target.is_dir():
            raise ConfigSetupError(
                f"AppRC TOML target is a directory: {target}",
                param_hint="APPRC_TOML",
            )
        if not replace_existing_file:
            raise ConfigSetupError(
                f"AppRC TOML target already exists: {target}",
                param_hint="APPRC_TOML",
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
    :param registry_path: AppRC TOML path to load.
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


def same_path(left: str | Path, right: str | Path) -> bool:
    """Return whether two path spellings identify the same filesystem path.

    :param left: First path spelling.
    :param right: Second path spelling.
    :return: Whether both normalize to the same absolute path.
    """
    return normalized_apprc_toml_path(left) == normalized_apprc_toml_path(right)
