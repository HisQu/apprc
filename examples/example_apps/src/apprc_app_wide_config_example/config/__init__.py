"""AppRC config package for the app-wide config example."""

# ruff: noqa: F401

from apprc_app_wide_config_example.config.app import MyRC
from apprc_app_wide_config_example.config.bundle import (
    AppWideConfigExampleConfig,
)
from apprc_app_wide_config_example.config.catalog import (
    CONFIG_SECTIONS,
    CONFIG_SPEC,
    KIT,
    SECTION_BY_KEY,
)
from apprc_app_wide_config_example.config.sections import AppWideConfig

__all__ = [
    "AppWideConfig",
    "AppWideConfigExampleConfig",
    "CONFIG_SECTIONS",
    "CONFIG_SPEC",
    "KIT",
    "MyRC",
    "SECTION_BY_KEY",
]
