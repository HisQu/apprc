"""Top-level settings object for CLI resolution."""

from dataclasses import dataclass, field

from library_client.config.app import MyRC
from library_client.config.sections.client import ClientSettings


@MyRC.bundle
@dataclass(kw_only=True)
class LibraryClientConfig:
    """Carry the client's registered config section."""

    client: ClientSettings = field(default_factory=ClientSettings)
