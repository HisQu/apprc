"""Top-level config bundle for the app-wide config example."""

from app_wide_config.config.app import MyRC
from app_wide_config.config.sections import AppWideConfig


@MyRC.bundle
class AppWideConfigExampleConfig:
    """Aggregate app-wide config example sections."""

    app_wide: AppWideConfig
