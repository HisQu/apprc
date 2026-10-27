"""Derive configuration filenames from one captured application snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from apprc.definition.app_config.spec import AppConfigSpec
from apprc.definition.paths import AppPaths
from apprc.user_files.app_home.locations import (
    AppRCDirectoryError,
    apprc_file,
    assert_no_links,
    ensure_text_file,
)
from apprc.user_files.env_files.secrets import secret_companion_path


@dataclass(frozen=True, slots=True)
class AppFiles:
    """Locate declared configuration files without resolving paths again.

    :param spec: Validated declaration supplying filenames and identity.
    :param paths: Captured paths for the current invocation.
    """

    spec: AppConfigSpec
    paths: AppPaths

    def config_file(self, filename: str | None = None) -> Path:
        """Return a declared filename below the enabled configuration root.

        :param filename: Optional filename; defaults to the registry filename.
        :return: Absolute configuration-file path.
        """
        return apprc_file(
            self.paths.require("config"),
            filename or self.spec.apprc_toml_filename,
        )

    def user_dotenv_path(self) -> Path:
        """Return the declared per-user dotenv path."""
        self.spec.require_user_dotenv()
        return self.config_file(self.spec.user_dotenv_filename)

    def workspace_dotenv_path(self, workspace_root: Path) -> Path:
        """Return the local dotenv path for one selected workspace."""
        self.spec.require_workspaces()
        return apprc_file(workspace_root, self.spec.workspace_dotenv_filename)

    def user_secret_dotenv_path(self) -> Path:
        """Return the private companion of the declared user dotenv."""
        return secret_companion_path(self.user_dotenv_path())

    def workspace_secret_dotenv_path(self, workspace_root: Path) -> Path:
        """Return the private companion of one workspace dotenv."""
        return secret_companion_path(self.workspace_dotenv_path(workspace_root))

    def ensure_user_dotenv(self) -> Path:
        """Create the declared per-user dotenv during explicit setup."""
        path = self.user_dotenv_path()
        for parent in reversed(path.expanduser().absolute().parents):
            assert_no_links(parent)
            if parent.exists() and not parent.is_dir():
                raise AppRCDirectoryError(
                    "AppRC-managed file parent exists but is not a directory: "
                    f"{parent}"
                )
        return ensure_text_file(path)
