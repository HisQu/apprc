"""AppRC config package for the storage-only example."""

# ruff: noqa: F401

from apprc_storage_only_example.config.app import MyRC
from apprc_storage_only_example.config.bundle import StorageOnlyExampleConfig
from apprc_storage_only_example.config.catalog import (
    CONFIG_SECTIONS,
    CONFIG_SPEC,
    KIT,
    SECTION_BY_KEY,
)
from apprc_storage_only_example.config.sections import StorageOnlyConfig

__all__ = [
    "CONFIG_SECTIONS",
    "CONFIG_SPEC",
    "KIT",
    "MyRC",
    "SECTION_BY_KEY",
    "StorageOnlyConfig",
    "StorageOnlyExampleConfig",
]
