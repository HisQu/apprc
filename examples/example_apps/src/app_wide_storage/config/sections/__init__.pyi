"""Typed surface for the app-wide storage section namespace."""

# ruff: noqa: F401

from app_wide_storage.config.sections.app import (
    AppWideStorageConfig as AppWideStorageConfig,
)

__all__: list[str]

def __getattr__(name: str) -> object: ...
def __dir__() -> list[str]: ...
