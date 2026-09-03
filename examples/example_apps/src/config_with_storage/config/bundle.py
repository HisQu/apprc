"""Top-level config bundle for the config-with-storage example."""

from config_with_storage.config.app import MyRC
from config_with_storage.config.sections.app import AppSettings


@MyRC.bundle
class ConfigWithStorageExampleConfig:
    """Aggregate config-with-storage example sections."""

    app: AppSettings
