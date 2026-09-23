"""Resolve and initialize the fixed managed files of one application."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from apprc.definition.app_config.spec import AppConfigSpec
from apprc.user_files.app_home.locations import (
    AppRCDirectoryPaths,
    apprc_file,
    ensure_text_file,
    resolve_apprc_dir,
    resolve_apprc_directory_paths,
)
from apprc.user_files.env_files.files import storage_dotenv_path


@dataclass(frozen=True, slots=True)
class AppFiles:
    """Locate and initialize the managed files described by a declaration.

    File operations belong to persistence, so application declarations can be
    inspected without depending on filesystem implementation code.

    :param spec: Validated declaration supplying fixed filenames and identity.
    """

    spec: AppConfigSpec

    def apprc_dir(
        self,
        proc_env: Mapping[str, str] | None = None,
    ) -> Path:
        """Return the resolved AppRC directory without creating it.

        :param proc_env: Environment mapping used for directory selection.
        :return: Environment, declaration, or default directory.
        """
        return resolve_apprc_dir(
            app_id=self.spec.app_id,
            declared_path=self.spec.declared_apprc_dir,
            env_key=self.spec.apprc_dir_env_key,
            proc_env=proc_env,
        )

    def preferred_apprc_toml_path(
        self,
        proc_env: Mapping[str, str] | None = None,
    ) -> Path:
        """Return the fixed storage registry path."""
        return apprc_file(
            self.apprc_dir(proc_env),
            self.spec.apprc_toml_filename,
        )

    def user_dotenv_path(
        self,
        proc_env: Mapping[str, str] | None = None,
    ) -> Path:
        """Return the fixed per-user dotenv path."""
        return apprc_file(
            self.apprc_dir(proc_env),
            self.spec.user_dotenv_filename,
        )

    def storage_dotenv_path(self, storage_root: Path) -> Path:
        """Return the fixed dotenv path inside a storage root.

        :param storage_root: Registered storage directory.
        :return: Storage-local dotenv path.
        """
        self.spec.require_storage()
        return storage_dotenv_path(
            storage_root,
            filename=self.spec.storage_dotenv_filename,
        )

    def paths(
        self,
        proc_env: Mapping[str, str] | None = None,
    ) -> AppRCDirectoryPaths:
        """Return every AppRC-directory path without creating files."""
        root = self.apprc_dir(proc_env)
        return resolve_apprc_directory_paths(
            apprc_dir=root,
            user_dotenv_path=apprc_file(root, self.spec.user_dotenv_filename),
            apprc_toml_path=apprc_file(root, self.spec.apprc_toml_filename),
        )

    def ensure_user_dotenv(
        self,
        proc_env: Mapping[str, str] | None = None,
    ) -> Path:
        """Create the declared per-user dotenv for an explicit setup."""
        self.spec.require_user_dotenv()
        return ensure_text_file(self.user_dotenv_path(proc_env))

    def ensure_apprc_toml(
        self,
        proc_env: Mapping[str, str] | None = None,
    ) -> Path:
        """Create the registry for an explicit storage write."""
        self.spec.require_storage()
        return ensure_text_file(self.preferred_apprc_toml_path(proc_env))
