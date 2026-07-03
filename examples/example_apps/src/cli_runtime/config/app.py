"""AppRC application contract for the CLI runtime example."""

import apprc as rc


MyRC = rc.AppRC.storage_only(
    app_name="apprc-example-cli-runtime",
    display_name="AppRC CLI Runtime Example",
    config_package="cli_runtime.config",
    storage_env_key="APPRC_EXAMPLE_RUNTIME_ROOT",
    command_name="apprc-cli-runtime",
)
