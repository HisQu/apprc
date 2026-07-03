"""Typed surface for the explicit env precedence section namespace."""

# ruff: noqa: F401

from explicit_env_precedence.config.sections.app import (
    ExplicitEnvPrecedenceConfig as ExplicitEnvPrecedenceConfig,
)

__all__: list[str]

def __getattr__(name: str) -> object: ...
def __dir__() -> list[str]: ...
