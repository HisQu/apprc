"""AppRC application contract for the user-dotenv example."""

import apprc as rc


MyRC = rc.AppRC(
    app_id="apprc-example-user-dotenv",
    display_name="AppRC User Dotenv Example",
    config_package="user_dotenv.config",
    user_dotenv=rc.UserDotenv(),
    command_name="apprc-user-dotenv",
)
