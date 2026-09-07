"""Top-level config bundle for the user-dotenv example."""

from dataclasses import dataclass, field

from user_dotenv.config.app import MyRC
from user_dotenv.config.sections.app import AppSettings


@MyRC.bundle
@dataclass(kw_only=True)
class UserDotenvExampleConfig:
    """Aggregate the example's env-backed settings."""

    app: AppSettings = field(default_factory=AppSettings)
