"""Top-level config bundle for the env-only example."""

from apprc_env_only_example.config.app import MyRC
from apprc_env_only_example.config.sections import EnvOnlyConfig


@MyRC.bundle
class EnvOnlyExampleConfig:
    """Aggregate env-only example sections."""

    env_only: EnvOnlyConfig
