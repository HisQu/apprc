"""AppRC application contract for the workspace example."""

import apprc as rc

MyRC = rc.AppRC(
    app_id="apprc-example-workspace",
    display_name="AppRC Workspace Example",
    paths=rc.Paths(config=True),
    config_package="workspace.config",
    workspaces=rc.Workspaces(selector_env_key="APPRC_EXAMPLE_WORKSPACE"),
    command_name="apprc-workspace",
)
