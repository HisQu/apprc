"""Top-level config bundle for the config-only example."""

from dataclasses import dataclass, field

from config_only.config.app import MyRC
from config_only.config.sections.app import AppSettings


@MyRC.bundle
@dataclass(kw_only=True)
class ConfigOnlyExampleConfig:
    """Aggregate config-only example sections."""

    app: AppSettings = field(default_factory=AppSettings)
