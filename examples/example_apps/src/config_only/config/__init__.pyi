"""Typed surface for the config-only example config package."""

# ruff: noqa: F401

from config_only.config.app import MyRC as MyRC
from config_only.config.bundle import (
    ConfigOnlyExampleConfig as ConfigOnlyExampleConfig,
)
from config_only.config.catalog import (
    CONFIG_SECTIONS as CONFIG_SECTIONS,
    CONFIG_SPEC as CONFIG_SPEC,
    KIT as KIT,
    SECTION_BY_KEY as SECTION_BY_KEY,
)
from config_only.config.sections.app import AppSettings as AppSettings

__all__: list[str]

def __getattr__(name: str) -> object: ...
def __dir__() -> list[str]: ...
