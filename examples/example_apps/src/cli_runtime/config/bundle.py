"""Top-level config bundle for the CLI runtime example."""

from dataclasses import dataclass, field

from cli_runtime.config.app import MyRC
from cli_runtime.config.sections.runtime.settings import CliRuntimeConfig


@MyRC.bundle
@dataclass(kw_only=True)
class CliRuntimeExampleConfig:
    """Aggregate CLI runtime example sections."""

    runtime: CliRuntimeConfig = field(default_factory=CliRuntimeConfig)
