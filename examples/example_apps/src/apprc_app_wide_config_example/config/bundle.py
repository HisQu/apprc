"""Top-level config bundle for the app-wide config example."""

from apprc_app_wide_config_example.config.app import MyRC
from apprc_app_wide_config_example.config.sections import AppWideConfig


@MyRC.bundle
class AppWideConfigExampleConfig:
    """Aggregate app-wide config example sections."""

    app_wide: AppWideConfig
