"""Typed surface for the app-wide config section namespace."""

# ruff: noqa: F401

from app_wide_config.config.sections.app import AppWideConfig as AppWideConfig

__all__: list[str]

def __getattr__(name: str) -> object: ...
def __dir__() -> list[str]: ...
