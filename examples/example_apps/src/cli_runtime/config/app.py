"""AppRC application contract for the CLI runtime example."""

import apprc as rc


MyRC = rc.AppRC(
    app_id="apprc-example-cli-runtime",
    display_name="AppRC CLI Runtime Example",
    config_package="cli_runtime.config",
    storage=rc.Storage(selector_env_key="APPRC_EXAMPLE_RUNTIME_STORAGE"),
    command_name="apprc-cli-runtime",
)
