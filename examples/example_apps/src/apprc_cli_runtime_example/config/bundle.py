"""Top-level config bundle for the CLI runtime example."""

from apprc_cli_runtime_example.config.app import MyRC
from apprc_cli_runtime_example.config.sections import CliRuntimeConfig


@MyRC.bundle
class CliRuntimeExampleConfig:
    """Aggregate CLI runtime example sections."""

    runtime: CliRuntimeConfig
