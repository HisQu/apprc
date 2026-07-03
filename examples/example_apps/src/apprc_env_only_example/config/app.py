"""AppRC application contract for the env-only example."""

import apprc as rc


MyRC = rc.AppRC.env_only(
    app_name="apprc-example-env-only",
    display_name="AppRC Env Only Example",
    config_package="apprc_env_only_example.config",
    command_name="apprc-env-only",
)
