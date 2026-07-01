"""AppRC declarations for the app-wide storage example app."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path

# == Internal ================================
import apprc


@apprc.env_owner(
    key="app_wide_storage",
    title="App Wide Storage",
    env_prefix="APPRC_EXAMPLE_APP_WIDE_STORAGE_",
    rc_path=("app_wide_storage",),
)
class AppWideStorageConfig(apprc.EnvConfig):
    """Config fields resolved from app-wide and storage layers."""

    storage_root: Path = apprc.env_field(
        "ROOT",
        editable=False,
        required=True,
        title="Storage root",
        explanation_short="Active storage root selected for this run.",
    )
    region: str = apprc.env_field(
        "REGION",
        default="local",
        title="Region",
        explanation_short="App-wide value shared by every storage.",
    )
    access_token: str = apprc.env_field(
        "ACCESS_TOKEN",
        required=True,
        secret=True,
        title="Access token",
        explanation_short="Required storage-local secret.",
    )


KIT = apprc.AppConfigKit.app_wide_storage(
    app_name="apprc-example-app-wide-storage",
    display_name="AppRC App-Wide Storage Example",
    config_package="apprc_app_wide_storage_example",
    envs=(AppWideStorageConfig,),
    storage_env_key="APPRC_EXAMPLE_APP_WIDE_STORAGE_ROOT",
    command_name="apprc-app-wide-storage",
)

OWNERS = (apprc.config_owner_for(AppWideStorageConfig),)
