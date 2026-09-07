"""AppRC application contract for the combined-capability example."""

import apprc as rc


MyRC = rc.AppRC(
    app_id="apprc-example-user-dotenv-with-storage",
    display_name="AppRC User Dotenv With Storage Example",
    config_package="user_dotenv_with_storage.config",
    user_dotenv=rc.UserDotenv(),
    storage=rc.Storage(selector_env_key="APPRC_EXAMPLE_BOTH_STORAGE"),
    command_name="apprc-user-dotenv-with-storage",
)
