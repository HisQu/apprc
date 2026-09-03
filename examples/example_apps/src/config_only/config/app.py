"""AppRC application contract for the config-only example."""

import apprc as rc


MyRC = rc.AppRC(
    app_name="apprc-example-config-only",
    display_name="AppRC Config Only Example",
    config_package="config_only.config",
    command_name="apprc-config-only",
)
