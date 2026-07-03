"""Typed surface for the env-only config section namespace."""

# ruff: noqa: F401

from env_only.config.sections.app import EnvOnlyConfig as EnvOnlyConfig

__all__: list[str]

def __getattr__(name: str) -> object: ...
def __dir__() -> list[str]: ...
