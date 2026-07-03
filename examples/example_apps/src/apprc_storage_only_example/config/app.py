"""AppRC application contract for the storage-only example."""

import apprc as rc


MyRC = rc.AppRC.storage_only(
    app_name="apprc-example-storage-only",
    display_name="AppRC Storage Only Example",
    config_package="apprc_storage_only_example.config",
    storage_env_key="APPRC_EXAMPLE_STORAGE_ROOT",
    command_name="apprc-storage-only",
)
