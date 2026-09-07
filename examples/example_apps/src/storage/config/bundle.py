"""Top-level config bundle for the storage example."""

from dataclasses import dataclass, field

from storage.config.app import MyRC
from storage.config.sections.app import AppSettings


@MyRC.bundle
@dataclass(kw_only=True)
class StorageExampleConfig:
    """Aggregate the example's env-backed settings."""

    app: AppSettings = field(default_factory=AppSettings)
