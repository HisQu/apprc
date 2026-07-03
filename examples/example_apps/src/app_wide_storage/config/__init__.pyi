"""Typed surface for the app-wide storage example package."""

# ruff: noqa: F401

from app_wide_storage.config.app import MyRC as MyRC
from app_wide_storage.config.bundle import (
    AppWideStorageExampleConfig as AppWideStorageExampleConfig,
)
from app_wide_storage.config.catalog import (
    CONFIG_SECTIONS as CONFIG_SECTIONS,
    CONFIG_SPEC as CONFIG_SPEC,
    KIT as KIT,
    SECTION_BY_KEY as SECTION_BY_KEY,
)
from app_wide_storage.config.sections.app import (
    AppWideStorageConfig as AppWideStorageConfig,
)

__all__: list[str]

def __getattr__(name: str) -> object: ...
def __dir__() -> list[str]: ...
