"""Top-level config bundle for the env-only example."""

from env_only.config.app import MyRC
from env_only.config.sections.app import EnvOnlyConfig


@MyRC.bundle
class EnvOnlyExampleConfig:
    """Aggregate env-only example sections."""

    env_only: EnvOnlyConfig
