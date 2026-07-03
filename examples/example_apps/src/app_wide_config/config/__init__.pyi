"""Typed surface for the app-wide config example package."""

# ruff: noqa: F401

from app_wide_config.config.app import MyRC as MyRC
from app_wide_config.config.bundle import (
    AppWideConfigExampleConfig as AppWideConfigExampleConfig,
)
from app_wide_config.config.catalog import (
    CONFIG_SECTIONS as CONFIG_SECTIONS,
    CONFIG_SPEC as CONFIG_SPEC,
    KIT as KIT,
    SECTION_BY_KEY as SECTION_BY_KEY,
)
from app_wide_config.config.sections.app import (
    AppWideConfig as AppWideConfig,
)

__all__: list[str]

def __getattr__(name: str) -> object: ...
def __dir__() -> list[str]: ...
