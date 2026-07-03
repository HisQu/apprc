"""AppRC config package for the app-wide storage example."""

# ruff: noqa: F401

from app_wide_storage.config.app import MyRC
from app_wide_storage.config.bundle import (
    AppWideStorageExampleConfig,
)
from app_wide_storage.config.catalog import (
    CONFIG_SECTIONS,
    CONFIG_SPEC,
    KIT,
    SECTION_BY_KEY,
)
from app_wide_storage.config.sections import AppWideStorageConfig

__all__ = [
    "AppWideStorageConfig",
    "AppWideStorageExampleConfig",
    "CONFIG_SECTIONS",
    "CONFIG_SPEC",
    "KIT",
    "MyRC",
    "SECTION_BY_KEY",
]
