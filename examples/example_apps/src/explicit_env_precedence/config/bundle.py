"""Top-level config bundle for the explicit env precedence example."""

from explicit_env_precedence.config.app import MyRC
from explicit_env_precedence.config.sections import (
    ExplicitEnvPrecedenceConfig,
)


@MyRC.bundle
class ExplicitEnvPrecedenceExampleConfig:
    """Aggregate explicit env precedence example sections."""

    precedence: ExplicitEnvPrecedenceConfig
