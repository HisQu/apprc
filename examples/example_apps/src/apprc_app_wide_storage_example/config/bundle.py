"""Top-level config bundle for the app-wide storage example."""

from apprc_app_wide_storage_example.config.app import MyRC
from apprc_app_wide_storage_example.config.sections import (
    AppWideStorageConfig,
)


@MyRC.bundle
class AppWideStorageExampleConfig:
    """Aggregate app-wide storage example sections."""

    app_wide_storage: AppWideStorageConfig
