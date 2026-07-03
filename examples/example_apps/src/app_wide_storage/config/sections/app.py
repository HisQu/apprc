"""App-wide storage example AppRC section."""

# == Standard Library ========================
from pathlib import Path

# == Internal ================================
import apprc as rc
from app_wide_storage.config.app import MyRC


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
