"""Small AppRC capability-mode matrix examples."""

from __future__ import annotations

from pathlib import Path

import apprc


@apprc.env_owner(
    key="simple",
    title="Simple",
    env_prefix="APPRC_MATRIX_",
    rc_path=("simple",),
)
class MatrixSimpleEnv(apprc.EnvConfig):
    """Config fields for non-storage examples."""

    profile: str = apprc.env_field("PROFILE", default="default")


@apprc.env_owner(
    key="storage",
    title="Storage",
    env_prefix="APPRC_MATRIX_",
    rc_path=("storage",),
)
class MatrixStorageEnv(apprc.EnvConfig):
    """Config fields for storage-capable examples."""

    storage_root: Path = apprc.env_field(
        "STORAGE",
        editable=False,
        required=True,
    )
    profile: str = apprc.env_field("PROFILE", default="default")


ENV_ONLY_KIT = apprc.AppConfigKit.env_only(
    app_name="apprc_matrix_env_only",
    display_name="Matrix Env Only",
    config_package="apprc_example_app.config",
    envs=(MatrixSimpleEnv,),
)

STORAGE_ONLY_KIT = apprc.AppConfigKit.storage_only(
    app_name="apprc_matrix_storage_only",
    display_name="Matrix Storage Only",
    config_package="apprc_example_app.config",
    envs=(MatrixStorageEnv,),
    storage_env_key="APPRC_MATRIX_STORAGE",
)

APP_WIDE_CONFIG_KIT = apprc.AppConfigKit.app_wide_config(
    app_name="apprc_matrix_app_wide",
    display_name="Matrix App Wide",
    config_package="apprc_example_app.config",
    envs=(MatrixSimpleEnv,),
)

APP_WIDE_STORAGE_KIT = apprc.AppConfigKit.app_wide_storage(
    app_name="apprc_matrix_app_wide_storage",
    display_name="Matrix App Wide Storage",
    config_package="apprc_example_app.config",
    envs=(MatrixStorageEnv,),
    storage_env_key="APPRC_MATRIX_STORAGE",
)

MODE_MATRIX_KITS = {
    "env_only": ENV_ONLY_KIT,
    "storage_only": STORAGE_ONLY_KIT,
    "app_wide_config": APP_WIDE_CONFIG_KIT,
    "app_wide_storage": APP_WIDE_STORAGE_KIT,
}

STORAGE_ONLY_UPGRADES = (
    "apprc config app init",
    "apprc config storage add alpha /absolute/path/to/alpha",
)
