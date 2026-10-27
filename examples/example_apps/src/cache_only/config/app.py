"""AppRC declaration for cache-only path initialization."""

import apprc as rc

MyRC = rc.AppRC(
    app_id="apprc-example-cache-only",
    display_name="AppRC Cache Only Example",
    paths=rc.Paths(cache=True),
    command_name="apprc-cache-only",
)
