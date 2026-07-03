"""Typed surface for the storage-only example config package."""

# ruff: noqa: F401

from storage_only.config.app import MyRC as MyRC
from storage_only.config.bundle import (
    StorageOnlyExampleConfig as StorageOnlyExampleConfig,
)
from storage_only.config.catalog import (
    CONFIG_SECTIONS as CONFIG_SECTIONS,
    CONFIG_SPEC as CONFIG_SPEC,
    KIT as KIT,
    SECTION_BY_KEY as SECTION_BY_KEY,
)
from storage_only.config.sections.app import (
    StorageOnlyConfig as StorageOnlyConfig,
)

__all__: list[str]

def __getattr__(name: str) -> object: ...
def __dir__() -> list[str]: ...
