"""AppRC directory paths and package resource helpers."""

# ruff: noqa: F401

from apprc.user_files.app_home._package_resources import resolve_package_root
from apprc.user_files.app_home.locations import (
    AppRCDirectoryError,
    AppRCDirectoryPaths,
    apprc_file,
    default_apprc_dir,
    ensure_text_file,
    require_filename,
    require_readable_text_file,
    resolve_apprc_dir,
    resolve_apprc_directory_paths,
    write_text_atomic,
)

__all__ = [
    "AppRCDirectoryError",
    "AppRCDirectoryPaths",
    "apprc_file",
    "default_apprc_dir",
    "ensure_text_file",
    "require_filename",
    "require_readable_text_file",
    "resolve_apprc_dir",
    "resolve_apprc_directory_paths",
    "resolve_package_root",
    "write_text_atomic",
]
