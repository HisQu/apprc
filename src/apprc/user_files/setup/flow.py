"""Explicit setup operations for AppRC-managed files."""

from __future__ import annotations

# == Standard Library ===========================================
from dataclasses import dataclass
from pathlib import Path

# == Internal ===================================================
from apprc.definition.app_config.kit import AppConfigKit
from apprc.user_files.app_home.locations import AppRCDirectoryError
from apprc.user_files.env_files.files import ensure_env_file
from apprc.user_files.managed_files import path_entry_exists
from apprc.user_files.storage_roots._io import load_storage_registry_or_empty
from apprc.user_files.storage_roots.paths import (
    StorageRootPathError,
    resolve_storage_root_path,
)
from apprc.user_files.storage_roots.registry import (
    register_storage,
    select_storage,
)


class ConfigSetupError(ValueError):
    """Readable setup failure with optional CLI context.

    :param message: Human-facing failure text.
    :param param_hint: Optional Typer parameter hint.
    :param exit_code: Optional process exit code for user cancellation.
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
    """Files initialized by one setup run.

    :param active_storage_root: Registered storage root, if supported.
    :param storage_dotenv: Storage-local dotenv file, if supported.
    :param user_dotenv: Per-user dotenv file.
    """

    active_storage_root: Path | None
    storage_dotenv: Path | None
    user_dotenv: Path


class ConfigSetupFlow:
    """Reusable non-interactive setup operations for one AppRC kit."""

    def __init__(self, kit: AppConfigKit) -> None:
        """Store the application whose managed files will be initialized."""
        self.kit = kit

    def ensure_user_dotenv(self) -> Path:
        """Create the per-user dotenv file.

        :return: Fixed ``apprc.user.env`` path.
        """
        try:
            return self.kit.spec.ensure_user_dotenv()
        except AppRCDirectoryError as exc:
            raise ConfigSetupError(
                str(exc),
                param_hint="--apprc-dir",
            ) from exc

    def run_app_setup(self) -> ConfigSetupResult:
        """Create the always-present per-user dotenv file.

        :return: Initialized file paths.
        """
        return ConfigSetupResult(
            active_storage_root=None,
            storage_dotenv=None,
            user_dotenv=self.ensure_user_dotenv(),
        )

    def run_storage_setup(
        self,
        storage_root: Path,
        *,
        storage_name: str = "default",
    ) -> ConfigSetupResult:
        """Create user dotenv, registry, and one named storage.

        Repeating setup for the same name and root is safe. Setup never
        repoints or moves an existing storage implicitly.

        :param storage_root: Root for the initial named storage.
        :param storage_name: Registry name, normally ``default``.
        :return: Initialized file paths.
        """
        spec = self.kit.spec
        spec.require_storage()
        registry_path = spec.preferred_apprc_toml_path()
        try:
            root = resolve_storage_root_path(
                storage_root,
                base=registry_path.parent,
            )
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

        user_dotenv = spec.user_dotenv_path()
        user_dotenv_existed = path_entry_exists(user_dotenv)
        try:
            ensured_user_dotenv = self.ensure_user_dotenv()
            registry = load_storage_registry_or_empty(registry_path)
            existing = registry.storages.get(storage_name)
            if existing is None:
                register_storage(
                    name=storage_name,
                    root=root,
                    path=registry_path,
                    storage_dotenv_filename=spec.storage_dotenv_filename,
                )
            elif existing.root != root:
                raise ConfigSetupError(
                    f"Storage {storage_name!r} already points to "
                    f"{existing.root}. Use `config storage repoint` or "
                    "`config storage move` to change it.",
                    param_hint="--storage-root",
                )
            else:
                root.mkdir(parents=True, exist_ok=True)
                ensure_env_file(spec.storage_dotenv_path(root))
                if registry.selected_storage is None:
                    select_storage(name=storage_name, path=registry_path)
        except ConfigSetupError:
            self._remove_new_user_dotenv(
                user_dotenv,
                existed=user_dotenv_existed,
            )
            raise
        except (AppRCDirectoryError, OSError, ValueError) as exc:
            self._remove_new_user_dotenv(
                user_dotenv,
                existed=user_dotenv_existed,
            )
            raise ConfigSetupError(str(exc)) from exc

        return ConfigSetupResult(
            active_storage_root=root,
            storage_dotenv=spec.storage_dotenv_path(root),
            user_dotenv=ensured_user_dotenv,
        )

    @staticmethod
    def _remove_new_user_dotenv(path: Path, *, existed: bool) -> None:
        """Remove a newly created empty user dotenv after setup failure.

        :param path: User dotenv candidate.
        :param existed: Whether it existed before setup.
        """
        if existed or not path.is_file():
            return
        try:
            if path.stat().st_size == 0:
                path.unlink()
                path.parent.rmdir()
        except OSError:
            return
