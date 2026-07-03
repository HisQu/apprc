"""AppRC application contract for the app-wide config example."""

import apprc as rc


MyRC = rc.AppRC.app_wide_config(
    app_name="apprc-example-app-wide-config",
    display_name="AppRC App-Wide Config Example",
    config_package="apprc_app_wide_config_example.config",
    command_name="apprc-app-wide-config",
)
