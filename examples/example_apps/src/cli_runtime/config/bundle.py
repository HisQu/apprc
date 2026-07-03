"""Top-level config bundle for the CLI runtime example."""

from cli_runtime.config.app import MyRC
from cli_runtime.config.sections.runtime.settings import CliRuntimeConfig


@MyRC.bundle
class CliRuntimeExampleConfig:
    """Aggregate CLI runtime example sections."""

    runtime: CliRuntimeConfig
