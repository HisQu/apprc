"""AppRC config package for the CLI runtime example."""

# ruff: noqa: F401

from apprc_cli_runtime_example.config.app import MyRC
from apprc_cli_runtime_example.config.bundle import CliRuntimeExampleConfig
from apprc_cli_runtime_example.config.catalog import (
    CONFIG_SECTIONS,
    CONFIG_SPEC,
    KIT,
    SECTION_BY_KEY,
)
from apprc_cli_runtime_example.config.sections import CliRuntimeConfig

__all__ = [
    "CONFIG_SECTIONS",
    "CONFIG_SPEC",
    "CliRuntimeConfig",
    "CliRuntimeExampleConfig",
    "KIT",
    "MyRC",
    "SECTION_BY_KEY",
]
