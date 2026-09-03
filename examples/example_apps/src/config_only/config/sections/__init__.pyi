"""Typed surface for the config-only config section namespace."""

# ruff: noqa: F401

from config_only.config.sections.app import AppSettings as AppSettings

__all__: list[str]

def __getattr__(name: str) -> object: ...
def __dir__() -> list[str]: ...
