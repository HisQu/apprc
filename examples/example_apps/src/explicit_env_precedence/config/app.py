"""AppRC application contract for the explicit env precedence example."""

import apprc as rc


MyRC = rc.AppRC.storage_only(
    app_name="apprc-example-explicit-env-precedence",
    display_name="AppRC Explicit Env Precedence Example",
    config_package="explicit_env_precedence.config",
    storage_env_key="APPRC_EXAMPLE_PRECEDENCE_ROOT",
    command_name="apprc-explicit-env-precedence",
)
