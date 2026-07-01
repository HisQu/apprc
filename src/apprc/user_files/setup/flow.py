"""Small setup helpers for AppRC capability layers."""

from __future__ import annotations

# == Standard Library ========================
from dataclasses import dataclass
from pathlib import Path

# == Internal ================================
from apprc.user_files.app_home.locations import ConfigHomeError
from apprc.definition.app_config.kit import AppConfigKit
from apprc.user_files.env_files.files import ensure_storage_env_file
from apprc.user_files.storage_roots.paths import (
    StorageRootPathError,
    normalize_storage_root_path,
)


class ConfigSetupError(ValueError):
    """Readable setup failure with optional CLI parameter context.

    :param message: Human-facing failure text.
    :param param_hint: Optional Typer parameter hint.
    :param exit_code: Optional process exit code for user cancellations.
    """

    def __init__(
        self,
        message: str,
        *,
        param_hint: str | None = None,
        exit_code: int | None = None,
    ) -> None:
        """Store setup failure details."""
        super().__init__(message)
        self.param_hint = param_hint
        self.exit_code = exit_code


@dataclass(frozen=True, slots=True)
class ConfigSetupResult:
    """Files initialized by one capability-layer setup run.

    :param active_storage_root: Storage root selected by setup, if any.
    :param storage_env: Storage dotenv file initialized by setup, if any.
    :param app_wide_env: App-wide dotenv file initialized by setup, if any.
    """

    active_storage_root: Path | None
    storage_env: Path | None
    app_wide_env: Path | None


class ConfigSetupFlow:
    """Reusable non-interactive setup operations for one AppRC kit."""

    def __init__(self, kit: AppConfigKit) -> None:
        """Store the kit whose capability layers should be initialized."""
        self.kit = kit

    def prepare_storage_root(self, storage_root: Path) -> Path:
        """Create and return a normalized storage root directory.

        :param storage_root: User-provided storage root.
        :return: Existing storage root directory.
        :raises ConfigSetupError: If the root path is invalid.
        """
        try:
            root = normalize_storage_root_path(storage_root)
        except StorageRootPathError as exc:
            raise ConfigSetupError(
                str(exc),
                param_hint="--storage-root",
            ) from exc
        if root.exists() and not root.is_dir():
            raise ConfigSetupError(
                f"Storage root exists but is not a directory: {root}",
                param_hint="--storage-root",
            )
        root.mkdir(parents=True, exist_ok=True)
        return root.resolve()

    def ensure_storage_env(self, storage_root: Path) -> Path:
        """Create the storage dotenv file under one root.

        :param storage_root: Storage root that should own the dotenv file.
        :return: Storage dotenv path.
        """
        try:
            return ensure_storage_env_file(
                storage_root,
                filename=self.kit.spec.storage_env_filename,
            )
        except StorageRootPathError as exc:
            raise ConfigSetupError(
                str(exc),
                param_hint="--storage-root",
            ) from exc

    def ensure_app_wide_env(self) -> Path:
        """Create the app-wide dotenv file for an app-wide setup run.

        :return: App-wide dotenv path.
        """
        try:
            return self.kit.spec.ensure_app_wide_env()
        except ConfigHomeError as exc:
            raise ConfigSetupError(
                str(exc),
                param_hint="config-home",
            ) from exc

    def run_app_wide_setup(self) -> ConfigSetupResult:
        """Initialize the app-wide dotenv file for this kit.

        :return: Files initialized by setup.
        """
        app_wide_env = self.ensure_app_wide_env()
        return ConfigSetupResult(
            active_storage_root=None,
            storage_env=None,
            app_wide_env=app_wide_env,
        )

    def run_storage_setup(self, storage_root: Path) -> ConfigSetupResult:
        """Initialize the files needed by storage-capable constructors.

        :param storage_root: Storage root selected by setup.
        :return: Files initialized by setup.
        """
        root = self.prepare_storage_root(storage_root)
        storage_env = self.ensure_storage_env(root)
        app_wide_env = (
            self.ensure_app_wide_env()
            if self.kit.spec.app_wide_default()
            else None
        )
        return ConfigSetupResult(
            active_storage_root=root,
            storage_env=storage_env,
            app_wide_env=app_wide_env,
        )
