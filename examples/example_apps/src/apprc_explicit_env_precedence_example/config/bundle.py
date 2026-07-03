"""Top-level config bundle for the explicit env precedence example."""

from apprc_explicit_env_precedence_example.config.app import MyRC
from apprc_explicit_env_precedence_example.config.sections import (
    ExplicitEnvPrecedenceConfig,
)


@MyRC.bundle
class ExplicitEnvPrecedenceExampleConfig:
    """Aggregate explicit env precedence example sections."""

    precedence: ExplicitEnvPrecedenceConfig
