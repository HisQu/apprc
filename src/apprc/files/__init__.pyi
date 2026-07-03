"""Typed surface for the lazy AppRC file helper namespace."""

# ruff: noqa: F401

from apprc.user_files.app_home._package_resources import (
    resolve_package_root as resolve_package_root,
)
from apprc.user_files.app_home.locations import (
    AppConfigHome as AppConfigHome,
    ConfigHomeError as ConfigHomeError,
    app_config_file as app_config_file,
    app_config_home as app_config_home,
    ensure_text_file as ensure_text_file,
    resolve_app_config_home as resolve_app_config_home,
    write_text_atomic as write_text_atomic,
)
from apprc.user_files.env_files.files import (
    ensure_env_file as ensure_env_file,
    ensure_storage_env_file as ensure_storage_env_file,
    read_env_file as read_env_file,
    storage_env_path as storage_env_path,
    write_env_file as write_env_file,
)
from apprc.user_files.env_files.updates import (
    EnvFileUpdate as EnvFileUpdate,
    clear_env_file_value as clear_env_file_value,
    clear_storage_env_value as clear_storage_env_value,
    set_env_file_value as set_env_file_value,
    set_storage_env_value as set_storage_env_value,
)
from apprc.user_files.env_files.values import (
    normalize_env_value as normalize_env_value,
)
from apprc.user_files.setup.flow import (
    ConfigSetupError as ConfigSetupError,
    ConfigSetupFlow as ConfigSetupFlow,
    ConfigSetupResult as ConfigSetupResult,
)

__all__: list[str]

def __getattr__(name: str) -> object: ...
def __dir__() -> list[str]: ...
