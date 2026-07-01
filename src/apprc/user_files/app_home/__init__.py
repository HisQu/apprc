"""Platform config-home paths and package resource helpers."""

# ruff: noqa: F401

from apprc.user_files.app_home._package_resources import resolve_package_root
from apprc.user_files.app_home.index import (
    ApprcTomlEnvError,
    missing_apprc_toml_env_message,
    missing_apprc_toml_file_message,
)
from apprc.user_files.app_home.locations import (
    AppConfigHome,
    ConfigHomeError,
    app_config_file,
    app_config_home,
    ensure_text_file,
    require_config_filename,
    require_readable_text_file,
    resolve_app_config_home,
    write_text_atomic,
)

__all__ = [
    "AppConfigHome",
    "ApprcTomlEnvError",
    "ConfigHomeError",
    "app_config_file",
    "app_config_home",
    "ensure_text_file",
    "missing_apprc_toml_env_message",
    "missing_apprc_toml_file_message",
    "require_config_filename",
    "require_readable_text_file",
    "resolve_app_config_home",
    "resolve_package_root",
    "write_text_atomic",
]
