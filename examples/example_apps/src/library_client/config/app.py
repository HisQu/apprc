"""One AppRC declaration for the importable client package."""

import apprc as rc


MyRC = rc.AppRC(
    app_id="apprc-example-library-client",
    display_name="AppRC Library Client Example",
    config_package="library_client.config",
    user_dotenv=rc.UserDotenv(),
    command_name="apprc-library-client",
)
