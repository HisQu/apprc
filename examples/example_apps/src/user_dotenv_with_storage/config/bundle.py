"""Top-level config bundle for the combined-capability example."""

from dataclasses import dataclass, field

from user_dotenv_with_storage.config.app import MyRC
from user_dotenv_with_storage.config.sections.app import AppSettings


@MyRC.bundle
@dataclass(kw_only=True)
class UserDotenvWithStorageExampleConfig:
    """Aggregate the example's env-backed settings."""

    app: AppSettings = field(default_factory=AppSettings)
