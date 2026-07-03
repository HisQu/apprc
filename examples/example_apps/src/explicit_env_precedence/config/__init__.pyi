"""Typed surface for the explicit env precedence example package."""

# ruff: noqa: F401

from explicit_env_precedence.config.app import MyRC as MyRC
from explicit_env_precedence.config.bundle import (
    ExplicitEnvPrecedenceExampleConfig as ExplicitEnvPrecedenceExampleConfig,
)
from explicit_env_precedence.config.catalog import (
    CONFIG_SECTIONS as CONFIG_SECTIONS,
    CONFIG_SPEC as CONFIG_SPEC,
    KIT as KIT,
    SECTION_BY_KEY as SECTION_BY_KEY,
)
from explicit_env_precedence.config.sections.app import (
    ExplicitEnvPrecedenceConfig as ExplicitEnvPrecedenceConfig,
)

__all__: list[str]

def __getattr__(name: str) -> object: ...
def __dir__() -> list[str]: ...
