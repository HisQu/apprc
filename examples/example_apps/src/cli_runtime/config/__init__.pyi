"""Typed surface for the CLI runtime example config package."""

# ruff: noqa: F401

from cli_runtime.config.app import MyRC as MyRC
from cli_runtime.config.bundle import (
    CliRuntimeExampleConfig as CliRuntimeExampleConfig,
)
from cli_runtime.config.catalog import (
    CONFIG_SECTIONS as CONFIG_SECTIONS,
    CONFIG_SPEC as CONFIG_SPEC,
    KIT as KIT,
    SECTION_BY_KEY as SECTION_BY_KEY,
)
from cli_runtime.config.sections.runtime.settings import (
    CliRuntimeConfig as CliRuntimeConfig,
)

__all__: list[str]

def __getattr__(name: str) -> object: ...
def __dir__() -> list[str]: ...
