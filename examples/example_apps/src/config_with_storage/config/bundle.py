"""Top-level config bundle for the config-with-storage example."""

from dataclasses import dataclass, field

from config_with_storage.config.app import MyRC
from config_with_storage.config.sections.app import AppSettings


@MyRC.bundle
@dataclass(kw_only=True)
class ConfigWithStorageExampleConfig:
    """Aggregate config-with-storage example sections."""

    app: AppSettings = field(default_factory=AppSettings)
