"""AppRC declarations for the app-wide storage example app."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path

# == Internal ================================
import apprc as rc


MyRC = rc.AppRC.app_wide_storage(
    app_name="apprc-example-app-wide-storage",
    display_name="AppRC App-Wide Storage Example",
    config_package="apprc_app_wide_storage_example",
    storage_env_key="APPRC_EXAMPLE_APP_WIDE_STORAGE_ROOT",
    command_name="apprc-app-wide-storage",
)


@MyRC.config(
    "app_wide_storage",
    prefix="APPRC_EXAMPLE_APP_WIDE_STORAGE_",
    title="App Wide Storage",
)
class AppWideStorageConfig(rc.Config):
    """Config fields resolved from app-wide and storage layers."""

    storage_root: Path = rc.field(
        "APPRC_EXAMPLE_APP_WIDE_STORAGE_ROOT",
        editable=False,
        required=True,
        title="Storage root",
        explanation_short="Active storage root selected for this run.",
    )
    region: str = rc.field(
        "APPRC_EXAMPLE_APP_WIDE_STORAGE_REGION",
        default="local",
        title="Region",
        explanation_short="App-wide value shared by every storage.",
    )
    access_token: str = rc.field(
        "APPRC_EXAMPLE_APP_WIDE_STORAGE_ACCESS_TOKEN",
        required=True,
        secret=True,
        title="Access token",
        explanation_short="Required storage-local secret.",
    )


KIT = MyRC.kit
OWNERS = KIT.spec.owners
