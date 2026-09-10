"""Application-level configuration contract."""

from __future__ import annotations

# == Standard Library ===========================================
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# == Internal ===================================================
from apprc.definition.app_config._validation import (
    derive_apprc_dir_env_key,
    derive_legacy_apprc_toml_env_key,
    resolve_storage_selector_env_key,
)
from apprc.definition.app_config.storage import Storage
from apprc.definition.app_config.user_dotenv import UserDotenv
from apprc.definition.env_config._validation import (
    validate_config_owner_inventory,
)
from apprc.definition.env_config.env import EnvConfig
from apprc.definition.env_config.fields import config_owner_for
from apprc.definition.env_config.schema import ConfigOwner
from apprc.user_files.app_home.locations import (
    AppRCDirectoryPaths,
    apprc_file,
    ensure_text_file,
    resolve_apprc_dir,
    resolve_apprc_directory_paths,
)
from apprc.user_files.env_files.files import storage_dotenv_path

DEFAULT_DEFAULTS_DOTENV_FILENAME = "apprc.defaults.env"
DEFAULT_USER_DOTENV_FILENAME = "apprc.user.env"
DEFAULT_STORAGE_DOTENV_FILENAME = "apprc.storage.env"
DEFAULT_APPRC_TOML_FILENAME = "apprc.toml"

LEGACY_DEFAULTS_DOTENV_FILENAME = ".env.shared"
LEGACY_USER_DOTENV_FILENAME = ".env.apprc-app"
LEGACY_STORAGE_DOTENV_FILENAME = ".env.apprc-storage"


@dataclass(frozen=True, slots=True, init=False)
class AppConfigSpec:
    """Complete configuration contract for one application.

    Python code determines whether user-dotenv and storage capabilities exist.
    Files on disk record instances of those features and never enable them.

    :param app_id: Stable application identity used in paths and derived keys.
    :param display_name: Human-readable application name.
    :param config_package: Package that may contain ``apprc.defaults.env``.
    :param envs: Environment-backed config classes registered by the facade.
    :param user_dotenv: User dotenv declaration, or ``None`` when disabled.
    :param storage: Storage declaration, or ``None`` for a storage-free app.
    :param command_name: Executable name shown in generated instructions.
    :param apprc_dir: Optional application-declared AppRC directory.
    :param apprc_dir_env_key: Explicit directory override key.
    :param legacy_app_ids: Released 0.19 identities accepted by migration.
    """

    app_id: str
    display_name: str
    config_package: str
    owners: tuple[ConfigOwner, ...]
    envs: tuple[type[EnvConfig], ...]
    user_dotenv: UserDotenv | None
    storage: Storage | None
    storage_selector_env_key: str | None
    command_name: str | None
    declared_apprc_dir: Path | None
    apprc_dir_env_key: str
    legacy_app_ids: tuple[str, ...]
    defaults_dotenv_filename: str
    user_dotenv_filename: str
    storage_dotenv_filename: str
    apprc_toml_filename: str

    def __init__(
        self,
        *,
        app_id: str,
        display_name: str,
        config_package: str,
        envs: tuple[type[EnvConfig], ...] = (),
        user_dotenv: UserDotenv | None = None,
        storage: Storage | None = None,
        command_name: str | None = None,
        apprc_dir: Path | None = None,
        apprc_dir_env_key: str | None = None,
        legacy_app_ids: tuple[str, ...] = (),
    ) -> None:
        """Normalize one direct AppRC declaration."""
        if not app_id.strip():
            raise ValueError("app_id must not be empty.")
        if user_dotenv is None and storage is None:
            if apprc_dir is not None:
                raise ValueError(
                    "apprc_dir requires user_dotenv=rc.UserDotenv() or "
                    "storage=rc.Storage()."
                )
            if apprc_dir_env_key is not None:
                raise ValueError(
                    "apprc_dir_env_key requires user_dotenv=rc.UserDotenv() "
                    "or storage=rc.Storage()."
                )
        resolved_owners = tuple(config_owner_for(env_cls) for env_cls in envs)
        validate_config_owner_inventory(resolved_owners)
        resolved_selector_key = (
            resolve_storage_selector_env_key(
                app_id=app_id,
                selector_env_key=storage.selector_env_key,
            )
            if storage is not None
            else None
        )
        normalized_legacy_ids = tuple(dict.fromkeys(legacy_app_ids))
        if app_id in normalized_legacy_ids:
            raise ValueError("legacy_app_ids must not repeat app_id.")

        object.__setattr__(self, "app_id", app_id)
        object.__setattr__(self, "display_name", display_name)
        object.__setattr__(self, "config_package", config_package)
        object.__setattr__(self, "owners", resolved_owners)
        object.__setattr__(self, "envs", tuple(envs))
        object.__setattr__(self, "user_dotenv", user_dotenv)
        object.__setattr__(self, "storage", storage)
        object.__setattr__(
            self,
            "storage_selector_env_key",
            resolved_selector_key,
        )
        object.__setattr__(self, "command_name", command_name)
        object.__setattr__(self, "declared_apprc_dir", apprc_dir)
        object.__setattr__(
            self,
            "apprc_dir_env_key",
            apprc_dir_env_key or derive_apprc_dir_env_key(app_id),
        )
        object.__setattr__(self, "legacy_app_ids", normalized_legacy_ids)
        object.__setattr__(
            self,
            "defaults_dotenv_filename",
            DEFAULT_DEFAULTS_DOTENV_FILENAME,
        )
        object.__setattr__(
            self,
            "user_dotenv_filename",
            DEFAULT_USER_DOTENV_FILENAME,
        )
        object.__setattr__(
            self,
            "storage_dotenv_filename",
            DEFAULT_STORAGE_DOTENV_FILENAME,
        )
        object.__setattr__(
            self,
            "apprc_toml_filename",
            DEFAULT_APPRC_TOML_FILENAME,
        )

    def config_command_name(self) -> str:
        """Return the executable name shown in generated commands."""
        return self.command_name or self.app_id

    @staticmethod
    def derive_legacy_apprc_toml_filename(app_id: str) -> str:
        """Return the released 0.19 registry basename.

        :param app_id: Legacy application identity.
        :return: Legacy ``<app>.apprc.toml`` filename.
        """
        normalized = re.sub(r"[^A-Za-z0-9_-]+", "_", app_id).strip("_-")
        return f"{normalized or 'app'}.apprc.toml"

    def legacy_apprc_toml_env_keys(self) -> tuple[str, ...]:
        """Return released registry relocation keys in lookup order.

        :return: Current-ID key followed by declared legacy-ID keys.
        """
        return tuple(
            derive_legacy_apprc_toml_env_key(app_id)
            for app_id in (self.app_id, *self.legacy_app_ids)
        )

    def uses_storage(self) -> bool:
        """Return whether Python code enables storage support."""
        return self.storage is not None

    def uses_user_dotenv(self) -> bool:
        """Return whether Python code enables user-dotenv persistence."""
        return self.user_dotenv is not None

    def requires_user_dotenv(self) -> bool:
        """Return whether diagnostics require the declared user dotenv."""
        return self.user_dotenv is not None and self.user_dotenv.required

    def requires_storage(self, override: bool | None = None) -> bool:
        """Return whether one runtime must resolve an active storage.

        :param override: Runtime policy, or ``None`` to use the declaration.
        :return: Effective storage requirement.
        :raises ValueError: If an override requires undeclared storage.
        """
        if override is True and self.storage is None:
            raise ValueError(
                "storage_required=True requires storage=rc.Storage()."
            )
        if self.storage is None:
            return False
        return self.storage.required if override is None else override

    def uses_managed_files(self) -> bool:
        """Return whether the application declares any persistent files."""
        return self.uses_user_dotenv() or self.uses_storage()

    def apprc_dir(
        self,
        proc_env: Mapping[str, str] | None = None,
    ) -> Path:
        """Return the resolved AppRC directory without creating it.

        :param proc_env: Environment mapping used for directory selection.
        :return: Environment, declaration, or default directory.
        """
        return resolve_apprc_dir(
            app_id=self.app_id,
            declared_path=self.declared_apprc_dir,
            env_key=self.apprc_dir_env_key,
            proc_env=proc_env,
        )

    def preferred_apprc_toml_path(
        self,
        proc_env: Mapping[str, str] | None = None,
    ) -> Path:
        """Return the fixed storage registry path."""
        return apprc_file(
            self.apprc_dir(proc_env),
            self.apprc_toml_filename,
        )

    def user_dotenv_path(
        self,
        proc_env: Mapping[str, str] | None = None,
    ) -> Path:
        """Return the fixed per-user dotenv path."""
        return apprc_file(
            self.apprc_dir(proc_env),
            self.user_dotenv_filename,
        )

    def storage_dotenv_path(self, storage_root: Path) -> Path:
        """Return the fixed dotenv path inside a storage root.

        :param storage_root: Registered storage directory.
        :return: Storage-local dotenv path.
        """
        self.require_storage()
        return storage_dotenv_path(
            storage_root,
            filename=self.storage_dotenv_filename,
        )

    def paths(
        self,
        proc_env: Mapping[str, str] | None = None,
    ) -> AppRCDirectoryPaths:
        """Return every AppRC-directory path without creating files."""
        root = self.apprc_dir(proc_env)
        return resolve_apprc_directory_paths(
            apprc_dir=root,
            user_dotenv_path=apprc_file(root, self.user_dotenv_filename),
            apprc_toml_path=apprc_file(root, self.apprc_toml_filename),
        )

    def ensure_user_dotenv(
        self,
        proc_env: Mapping[str, str] | None = None,
    ) -> Path:
        """Create the declared per-user dotenv for an explicit setup."""
        self.require_user_dotenv()
        return ensure_text_file(self.user_dotenv_path(proc_env))

    def ensure_apprc_toml(
        self,
        proc_env: Mapping[str, str] | None = None,
    ) -> Path:
        """Create the registry for an explicit storage write."""
        self.require_storage()
        return ensure_text_file(self.preferred_apprc_toml_path(proc_env))

    def require_storage_selector_env_key(self) -> str:
        """Return the selector key or raise for a storage-free app."""
        if self.storage_selector_env_key is None:
            raise ValueError(f"{self.display_name} does not use AppRC storage.")
        return self.storage_selector_env_key

    def require_storage(self) -> Storage:
        """Return the storage declaration or raise when absent.

        :return: Storage declaration owned by this application.
        :raises ValueError: If Python code did not enable storage.
        """
        if self.storage is None:
            raise ValueError(f"{self.display_name} does not use AppRC storage.")
        return self.storage

    def require_user_dotenv(self) -> UserDotenv:
        """Return the user-dotenv declaration or raise when absent.

        :return: User dotenv declaration owned by this application.
        :raises ValueError: If Python code did not enable user-dotenv support.
        """
        if self.user_dotenv is None:
            raise ValueError(
                f"{self.display_name} does not use an AppRC user dotenv."
            )
        return self.user_dotenv
