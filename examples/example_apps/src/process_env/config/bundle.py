"""Top-level config bundle for the process-environment example."""

from dataclasses import dataclass, field

from process_env.config.app import MyRC
from process_env.config.sections.app import AppSettings


@MyRC.bundle
@dataclass(kw_only=True)
class ProcessEnvExampleConfig:
    """Aggregate the example's env-backed settings."""

    app: AppSettings = field(default_factory=AppSettings)
