"""Top-level config bundle for the config-only example."""

from config_only.config.app import MyRC
from config_only.config.sections.app import AppSettings


@MyRC.bundle
class ConfigOnlyExampleConfig:
    """Aggregate config-only example sections."""

    app: AppSettings
