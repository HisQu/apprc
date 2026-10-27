"""AppRC application contract for the CLI runtime example."""

import apprc as rc

MyRC = rc.AppRC(
    app_id="apprc-example-cli-runtime",
    display_name="AppRC CLI Runtime Example",
    paths=rc.Paths(config=True),
    config_package="cli_runtime.config",
    user_dotenv=rc.UserDotenv(),
    workspaces=rc.Workspaces(
        selector_env_key="APPRC_EXAMPLE_RUNTIME_WORKSPACE"
    ),
    command_name="apprc-cli-runtime",
)
