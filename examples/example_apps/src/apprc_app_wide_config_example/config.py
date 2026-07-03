"""AppRC declarations for the app-wide config example app."""

from __future__ import annotations

# == Internal ================================
import apprc as rc


MyRC = rc.AppRC.app_wide_config(
    app_name="apprc-example-app-wide-config",
    display_name="AppRC App-Wide Config Example",
    config_package="apprc_app_wide_config_example",
    command_name="apprc-app-wide-config",
)


@MyRC.config("app_wide", prefix="APPRC_EXAMPLE_APP_WIDE_", title="App Wide")
class AppWideConfig(rc.Config):
    """Config fields resolved from the app-wide dotenv layer."""

    region: str = rc.field(
        "APPRC_EXAMPLE_APP_WIDE_REGION",
        default="local",
        title="Region",
        explanation_short="App-wide deployment region.",
    )
    workers: int = rc.field(
        "APPRC_EXAMPLE_APP_WIDE_WORKERS",
        default=1,
        title="Workers",
        explanation_short="App-wide worker count.",
    )


KIT = MyRC.kit
OWNERS = KIT.spec.owners
