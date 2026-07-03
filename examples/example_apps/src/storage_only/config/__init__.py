"""AppRC config package for the storage-only example."""

# ruff: noqa: F401

from storage_only.config.app import MyRC
from storage_only.config.bundle import StorageOnlyExampleConfig
from storage_only.config.catalog import (
    CONFIG_SECTIONS,
    CONFIG_SPEC,
    KIT,
    SECTION_BY_KEY,
)
from storage_only.config.sections import StorageOnlyConfig

__all__ = [
    "CONFIG_SECTIONS",
    "CONFIG_SPEC",
    "KIT",
    "MyRC",
    "SECTION_BY_KEY",
    "StorageOnlyConfig",
    "StorageOnlyExampleConfig",
]
