"""Public client with library-owned configuration loading."""

from library_client.config.app import MyRC
from library_client.config.sections.client import ClientSettings


class LibraryClient:
    """Read settings when constructed, without requiring caller setup."""

    def __init__(self, settings: ClientSettings | None = None) -> None:
        """Use injected settings or resolve the library's current layers.

        :param settings: Already-built settings for a shared run or test.
        """
        self.settings = (
            settings
            if settings is not None
            else MyRC.resolve().build(ClientSettings)
        )

    @property
    def request_timeout(self) -> int:
        """Return the timeout this client would use for a request."""
        return self.settings.request_timeout
