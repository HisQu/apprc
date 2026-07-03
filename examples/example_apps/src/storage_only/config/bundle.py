"""Top-level config bundle for the storage-only example."""

from storage_only.config.app import MyRC
from storage_only.config.sections.app import StorageOnlyConfig


@MyRC.bundle
class StorageOnlyExampleConfig:
    """Aggregate storage-only example sections."""

    storage_only: StorageOnlyConfig
