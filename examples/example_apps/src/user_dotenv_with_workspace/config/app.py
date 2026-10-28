"""AppRC application contract for the user-dotenv and workspace example."""

import apprc as rc

MyRC = rc.AppRC(
    app_id="apprc-example-user-dotenv-with-workspace",
    display_name="AppRC User Dotenv With Workspace Example",
    paths=rc.Paths(config=True),
    config_package="user_dotenv_with_workspace.config",
    user_dotenv=rc.UserDotenv(),
    workspaces=rc.Workspaces(selector_env_key="APPRC_EXAMPLE_BOTH_WORKSPACE"),
    command_name="apprc-user-dotenv-with-workspace",
)
