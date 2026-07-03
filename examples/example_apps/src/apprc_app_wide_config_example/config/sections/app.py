"""App-wide config example AppRC section."""

# == Internal ================================
import apprc as rc
from apprc_app_wide_config_example.config.app import MyRC


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
