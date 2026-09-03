"""Typed surface for the config-with-storage config section namespace."""

# ruff: noqa: F401

from config_with_storage.config.sections.app import AppSettings as AppSettings

__all__: list[str]

def __getattr__(name: str) -> object: ...
def __dir__() -> list[str]: ...
