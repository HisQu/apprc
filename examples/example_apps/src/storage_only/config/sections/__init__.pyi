"""Typed surface for the storage-only config section namespace."""

# ruff: noqa: F401

from storage_only.config.sections.app import (
    StorageOnlyConfig as StorageOnlyConfig,
)

__all__: list[str]

def __getattr__(name: str) -> object: ...
def __dir__() -> list[str]: ...
