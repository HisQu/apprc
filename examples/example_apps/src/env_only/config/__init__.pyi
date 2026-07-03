"""Typed surface for the env-only example config package."""

# ruff: noqa: F401

from env_only.config.app import MyRC as MyRC
from env_only.config.bundle import EnvOnlyExampleConfig as EnvOnlyExampleConfig
from env_only.config.catalog import (
    CONFIG_SECTIONS as CONFIG_SECTIONS,
    CONFIG_SPEC as CONFIG_SPEC,
    KIT as KIT,
    SECTION_BY_KEY as SECTION_BY_KEY,
)
from env_only.config.sections.app import EnvOnlyConfig as EnvOnlyConfig

__all__: list[str]

def __getattr__(name: str) -> object: ...
def __dir__() -> list[str]: ...
