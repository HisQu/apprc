"""AppRC application contract for the process-environment example."""

import apprc as rc


MyRC = rc.AppRC(
    app_id="apprc-example-process-env",
    display_name="AppRC Process Environment Example",
    config_package="process_env.config",
    command_name="apprc-process-env",
)
