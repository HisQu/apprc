"""AppRC config package for the env-only example."""

# ruff: noqa: F401

from env_only.config.app import MyRC
from env_only.config.bundle import EnvOnlyExampleConfig
from env_only.config.catalog import (
    CONFIG_SECTIONS,
    CONFIG_SPEC,
    KIT,
    SECTION_BY_KEY,
)
from env_only.config.sections import EnvOnlyConfig

__all__ = [
    "CONFIG_SECTIONS",
    "CONFIG_SPEC",
    "EnvOnlyConfig",
    "EnvOnlyExampleConfig",
    "KIT",
    "MyRC",
    "SECTION_BY_KEY",
]
