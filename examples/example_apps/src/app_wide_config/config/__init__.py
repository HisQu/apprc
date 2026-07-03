"""AppRC config package for the app-wide config example."""

# ruff: noqa: F401

from app_wide_config.config.app import MyRC
from app_wide_config.config.bundle import (
    AppWideConfigExampleConfig,
)
from app_wide_config.config.catalog import (
    CONFIG_SECTIONS,
    CONFIG_SPEC,
    KIT,
    SECTION_BY_KEY,
)
from app_wide_config.config.sections import AppWideConfig

__all__ = [
    "AppWideConfig",
    "AppWideConfigExampleConfig",
    "CONFIG_SECTIONS",
    "CONFIG_SPEC",
    "KIT",
    "MyRC",
    "SECTION_BY_KEY",
]
