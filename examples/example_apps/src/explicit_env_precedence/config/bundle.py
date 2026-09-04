"""Top-level config bundle for the explicit env precedence example."""

from dataclasses import dataclass, field

from explicit_env_precedence.config.app import MyRC
from explicit_env_precedence.config.sections.app import (
    ExplicitEnvPrecedenceConfig,
)


@MyRC.bundle
@dataclass(kw_only=True)
class ExplicitEnvPrecedenceExampleConfig:
    """Aggregate explicit env precedence example sections."""

    precedence: ExplicitEnvPrecedenceConfig = field(
        default_factory=ExplicitEnvPrecedenceConfig
    )
