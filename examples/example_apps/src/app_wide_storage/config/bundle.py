"""Top-level config bundle for the app-wide storage example."""

from app_wide_storage.config.app import MyRC
from app_wide_storage.config.sections import (
    AppWideStorageConfig,
)


@MyRC.bundle
class AppWideStorageExampleConfig:
    """Aggregate app-wide storage example sections."""

    app_wide_storage: AppWideStorageConfig
