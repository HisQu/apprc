"""AppRC declarations for the app-wide config example app."""

from __future__ import annotations

# == Internal ================================
import apprc


@apprc.env_owner(
    key="app_wide",
    title="App Wide",
    env_prefix="APPRC_EXAMPLE_APP_WIDE_",
    rc_path=("app_wide",),
)
class AppWideConfig(apprc.EnvConfig):
    """Config fields resolved from the app-wide dotenv layer."""

    region: str = apprc.env_field(
        "REGION",
        default="local",
        title="Region",
        explanation_short="App-wide deployment region.",
    )
    workers: int = apprc.env_field(
        "WORKERS",
        default=1,
        title="Workers",
        explanation_short="App-wide worker count.",
    )


KIT = apprc.AppConfigKit.app_wide_config(
    app_name="apprc-example-app-wide-config",
    display_name="AppRC App-Wide Config Example",
    config_package="apprc_app_wide_config_example",
    envs=(AppWideConfig,),
    command_name="apprc-app-wide-config",
)

OWNERS = (apprc.config_owner_for(AppWideConfig),)
