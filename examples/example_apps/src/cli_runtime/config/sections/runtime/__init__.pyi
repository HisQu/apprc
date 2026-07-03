"""Typed surface for the CLI runtime section package."""

# ruff: noqa: F401

from cli_runtime.config.sections.runtime.settings import (
    CliRuntimeConfig as CliRuntimeConfig,
)

__all__: list[str]

def __getattr__(name: str) -> object: ...
def __dir__() -> list[str]: ...
