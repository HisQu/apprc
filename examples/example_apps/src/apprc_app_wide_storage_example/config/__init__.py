"""AppRC config package for the app-wide storage example."""

# ruff: noqa: F401

from apprc_app_wide_storage_example.config.app import MyRC
from apprc_app_wide_storage_example.config.bundle import (
    AppWideStorageExampleConfig,
)
from apprc_app_wide_storage_example.config.catalog import (
    CONFIG_SECTIONS,
    CONFIG_SPEC,
    KIT,
    SECTION_BY_KEY,
)
from apprc_app_wide_storage_example.config.sections import AppWideStorageConfig

__all__ = [
    "AppWideStorageConfig",
    "AppWideStorageExampleConfig",
    "CONFIG_SECTIONS",
    "CONFIG_SPEC",
    "KIT",
    "MyRC",
    "SECTION_BY_KEY",
]
