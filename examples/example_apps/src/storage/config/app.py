"""AppRC application contract for the storage example."""

import apprc as rc


MyRC = rc.AppRC(
    app_id="apprc-example-storage",
    display_name="AppRC Storage Example",
    config_package="storage.config",
    storage=rc.Storage(selector_env_key="APPRC_EXAMPLE_STORAGE_STORAGE"),
    command_name="apprc-storage",
)
