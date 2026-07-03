"""Top-level config bundle for the storage-only example."""

from apprc_storage_only_example.config.app import MyRC
from apprc_storage_only_example.config.sections import StorageOnlyConfig


@MyRC.bundle
class StorageOnlyExampleConfig:
    """Aggregate storage-only example sections."""

    storage_only: StorageOnlyConfig
