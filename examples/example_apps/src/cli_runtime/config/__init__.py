"""AppRC config package for the CLI runtime example."""

# ruff: noqa: F401

from cli_runtime.config.app import MyRC
from cli_runtime.config.bundle import CliRuntimeExampleConfig
from cli_runtime.config.catalog import (
    CONFIG_SECTIONS,
    CONFIG_SPEC,
    KIT,
    SECTION_BY_KEY,
)
from cli_runtime.config.sections import CliRuntimeConfig

__all__ = [
    "CONFIG_SECTIONS",
    "CONFIG_SPEC",
    "CliRuntimeConfig",
    "CliRuntimeExampleConfig",
    "KIT",
    "MyRC",
    "SECTION_BY_KEY",
]
