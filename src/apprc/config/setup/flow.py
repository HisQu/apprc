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
from apprc.config.local_env import ensure_local_env_file
from apprc.config.paths import (
    StorageRootPathError,
    normalize_apprc_toml_path,
    normalize_storage_root_path,
)
from apprc.config.storage_registry_loading import (
    load_create_or_empty_storage_registry,
)
import apprc.config.setup.text as setup_text
from apprc.config.storage.registry import (
    StorageRegistry,
    register_storage,
    suggested_storage_name,
)
from apprc.config.storage.selector import resolve_setup_storage_root_from_env

if TYPE_CHECKING:
    from apprc.config.kit import AppConfigKit


class ExistingSetupAction(str, Enum):
    """Actions available when setup finds an existing AppRC TOML file."""

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

    :param registry: Storage table selected when multi-storage is enabled.
    :param active_storage_root: Explicit storage path selected for runtime.
    :param registered_storage_name: Optional selector created by setup.
    :param existing_action: Existing AppRC TOML action that was applied.
    """

    registry: StorageRegistry | None
    active_storage_root: Path
    registered_storage_name: str | None = None
    existing_action: ExistingSetupAction | None = None


@dataclass(frozen=True, slots=True)
class PreparedStorageRegistry:
    """Storage table chosen before the active storage step runs.

    :param registry: Storage table selected by setup.
    :param existing_action: Existing AppRC TOML action that was applied.
    """

    registry: StorageRegistry
    existing_action: ExistingSetupAction | None = None


class ConfigSetupFlow:
    """Own setup operations for one AppRC application integration.

    :param kit: Application config facade mounted by the host CLI.
    """

    def __init__(self, kit: "AppConfigKit") -> None:
        """Store the app facade used by setup decisions."""
        self.kit = kit

    def find_existing_apprc_toml_path(self) -> Path | None:
        """Return the env-selected AppRC TOML path when setup can reuse it."""
        active_path = self.kit.spec.optional_apprc_toml_path()
        if active_path is not None and active_path.is_file():
            return normalize_apprc_toml_path(active_path)
        return None

    def prepare_storage_registry(
        self,
        *,
        apprc_dir: Path | None,
        existing_action: ExistingSetupAction | None,
        replace_existing_file: bool,
    ) -> PreparedStorageRegistry:
        """Select, reset, or move the AppRC TOML used by setup.

        :param apprc_dir: Optional explicit target AppRC directory.
        :param existing_action: Optional action for a discovered AppRC TOML.
        :param replace_existing_file: Whether an existing move target may be
            replaced.
        :return: Selected storage table and action metadata.
        :raises ConfigSetupError: If the requested path cannot be rediscovered.
        """
        target_path = self.apprc_toml_path(apprc_dir)
        env_existing_path = self.find_existing_apprc_toml_path()
        existing_path = self._existing_apprc_toml_path(
            target_path=target_path,
            env_existing_path=env_existing_path,
            explicit_apprc_dir=apprc_dir is not None,
            existing_action=existing_action,
        )
        if existing_path is None:
            self.require_apprc_toml_path_available(target_path)
            return PreparedStorageRegistry(
                registry=self.load_storage_registry(target_path)
            )

        action = existing_action or ExistingSetupAction.KEEP
        if action == ExistingSetupAction.KEEP:
            self.require_apprc_toml_path_available(existing_path)
            return PreparedStorageRegistry(
                registry=self.load_storage_registry(existing_path),
                existing_action=action,
            )
        if action == ExistingSetupAction.RESET:
            self.remove_apprc_toml_file(existing_path)
            self.require_apprc_toml_path_available(target_path)
            return PreparedStorageRegistry(
                registry=self.load_storage_registry(target_path),
                existing_action=action,
            )

        self.require_apprc_toml_path_available(target_path)
        registry = self.move_existing_apprc_toml(
            source_path=existing_path,
            target_path=target_path,
            replace_existing_file=replace_existing_file,
        )
        return PreparedStorageRegistry(
            registry=registry, existing_action=action
        )

    @staticmethod
    def _existing_apprc_toml_path(
        *,
        target_path: Path,
        env_existing_path: Path | None,
        explicit_apprc_dir: bool,
        existing_action: ExistingSetupAction | None,
    ) -> Path | None:
        """Return the existing AppRC TOML path setup should operate on."""
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

    def ensure_registered_storage(
        self,
        registry: StorageRegistry,
        *,
        storage_root: Path,
        storage_name: str,
    ) -> ConfigSetupResult:
        """Ensure and register the active storage root for multi-storage."""
        try:
            updated = register_storage(
                name=storage_name,
                root=storage_root,
                path=registry.path,
                local_env_filename=self.kit.spec.local_env_filename,
            )
            record = updated.selected(storage_name)
            return ConfigSetupResult(
                registry=updated,
                active_storage_root=record.root,
                registered_storage_name=storage_name,
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
        self,
        *,
        storage_root: Path,
    ) -> ConfigSetupResult:
        """Create or confirm the active storage root without multi-storage."""
        resolved_root = self.ensure_storage_local_env(storage_root)
        return ConfigSetupResult(
            registry=None,
            active_storage_root=resolved_root,
        )

    def default_storage_name(self) -> str:
        """Return the conventional storage selector for setup when unset."""
        return suggested_storage_name(self.kit.spec.app_name)

    def prepare_storage_root(
        self,
        *,
        storage_root: Path | None,
        storage_name: str | None,
        allow_non_empty_storage: bool,
    ) -> Path:
        """Resolve and validate the active storage root before setup writes."""
        active_root = storage_root or self.storage_root_from_env()
        if active_root is None:
            raise ConfigSetupError(
                f"{self.kit.spec.storage_env_key} or --storage-root is "
                "required for non-interactive setup.",
                param_hint="--storage-root",
            )
        return self.validate_storage_root(
            active_root,
            storage_name=storage_name,
            allow_non_empty_storage=allow_non_empty_storage,
        )

    def ensure_storage_local_env(self, storage_root: Path) -> Path:
        """Create or confirm the storage-local dotenv file after validation."""
        try:
            local_env = ensure_local_env_file(
                storage_root,
                filename=self.kit.spec.local_env_filename,
            )
        except StorageRootPathError as exc:
            raise ConfigSetupError(
                str(exc),
                param_hint="STORAGE_ROOT",
            ) from exc
        return local_env.parent

    def validate_storage_root(
        self,
        storage_root: Path,
        *,
        storage_name: str | None,
        allow_non_empty_storage: bool,
    ) -> Path:
        """Return a safe storage root path before registration writes."""
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
                self.kit,
                resolved_root,
                storage_name=storage_name,
            ),
            param_hint="STORAGE_ROOT",
        )

    def storage_root_from_env(self) -> Path | None:
        """Return the active storage root from the setup-time env selector."""
        try:
            return resolve_setup_storage_root_from_env(
                storage_env_key=self.kit.spec.storage_env_key,
                proc_env=os.environ,
            )
        except StorageRootPathError as exc:
            raise ConfigSetupError(
                str(exc),
                param_hint=self.kit.spec.storage_env_key,
            ) from exc

    def apprc_toml_path(self, apprc_dir: Path | None) -> Path:
        """Return the AppRC TOML path selected by setup directory input."""
        if apprc_dir is not None:
            return self.apprc_toml_path_from_dir(apprc_dir)
        active_path = self.kit.spec.optional_apprc_toml_path()
        if active_path is not None:
            return normalize_apprc_toml_path(active_path)
        raise ConfigSetupError(
            f"{self.kit.spec.display_name} setup needs the "
            f"{self.kit.spec.display_name} directory (AppRC) because "
            f"{self.kit.spec.apprc_toml_env_key} is not set.\n"
            "Run setup again with an explicit directory:\n"
            f"{self.kit.spec.config_command_name()} config setup --yes "
            "--apprc-dir /absolute/path/to/config-dir",
            param_hint="--apprc-dir",
        )

    def apprc_dir(self, apprc_dir: Path) -> Path:
        """Return the directory that should contain the AppRC TOML file."""
        path = Path(apprc_dir).expanduser().resolve()
        if path.exists() and not path.is_dir():
            raise ConfigSetupError(
                f"AppRC directory is not a directory: {path}",
                param_hint="APPRC_DIR",
            )
        return path

    def apprc_toml_path_from_dir(self, apprc_dir: Path) -> Path:
        """Return the enforced AppRC TOML file inside a setup directory."""
        return self.apprc_dir(apprc_dir) / self.kit.spec.apprc_toml_filename

    @staticmethod
    def require_apprc_toml_path_available(apprc_toml_path: Path) -> None:
        """Reject AppRC TOML targets that cannot be written as files."""
        path = normalize_apprc_toml_path(apprc_toml_path)
        if not path.exists() or path.is_file():
            return
        raise ConfigSetupError(
            f"AppRC TOML target is not a file: {path}",
            param_hint="APPRC_TOML",
        )

    @staticmethod
    def remove_apprc_toml_file(apprc_toml_path: Path) -> None:
        """Delete only AppRC TOML state, never registered storage roots."""
        resolved_path = normalize_apprc_toml_path(apprc_toml_path)
        resolved_path.unlink(missing_ok=True)

    def move_existing_apprc_toml(
        self,
        *,
        source_path: Path,
        target_path: Path,
        replace_existing_file: bool,
    ) -> StorageRegistry:
        """Move an existing AppRC TOML file and load its storage table."""
        source = normalize_apprc_toml_path(source_path)
        target = normalize_apprc_toml_path(target_path)
        if self.same_path(source, target):
            return self.load_storage_registry(target)
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
        return self.load_storage_registry(target)

    @staticmethod
    def load_storage_registry(apprc_toml_path: Path) -> StorageRegistry:
        """Load a storage table and convert parse failures to setup errors."""
        try:
            return load_create_or_empty_storage_registry(apprc_toml_path)
        except ValueError as exc:
            raise ConfigSetupError(
                str(exc),
                param_hint=str(apprc_toml_path),
            ) from exc

    @staticmethod
    def same_path(left: str | Path, right: str | Path) -> bool:
        """Return whether two path spellings identify the same filesystem path."""
        return normalize_apprc_toml_path(left) == normalize_apprc_toml_path(
            right
        )
