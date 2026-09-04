"""AppRC application contract for the config-with-storage example."""

import apprc as rc


MyRC = rc.AppRC(
    app_id="apprc-example-config-with-storage",
    display_name="AppRC Config With Storage Example",
    config_package="config_with_storage.config",
    storage=rc.Storage(selector_env_key="APPRC_EXAMPLE_STORAGE_STORAGE"),
    command_name="apprc-config-with-storage",
)
