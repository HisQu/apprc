"""AppRC application contract for the app-wide storage example."""

import apprc as rc


MyRC = rc.AppRC.app_wide_storage(
    app_name="apprc-example-app-wide-storage",
    display_name="AppRC App-Wide Storage Example",
    config_package="apprc_app_wide_storage_example.config",
    storage_env_key="APPRC_EXAMPLE_APP_WIDE_STORAGE_ROOT",
    command_name="apprc-app-wide-storage",
)
