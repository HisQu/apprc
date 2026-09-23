"""Settings used when the client is constructed."""

import apprc as rc
from library_client.config.app import MyRC


@MyRC.config("client", prefix="APPRC_EXAMPLE_LIBRARY_", title="Client")
class ClientSettings(rc.Config):
    """Client timeout supplied by AppRC's configuration layers."""

    request_timeout: int = rc.field(
        "APPRC_EXAMPLE_LIBRARY_REQUEST_TIMEOUT",
        default=30,
        title="Request timeout",
        explanation_short="Seconds allowed for one client request.",
    )
