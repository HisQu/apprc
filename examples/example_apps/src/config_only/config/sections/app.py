"""Application settings for the config-only example."""

# == Internal ================================
import apprc as rc
from config_only.config.app import MyRC


@MyRC.config("app", prefix="APPRC_EXAMPLE_CONFIG_", title="Application")
class AppSettings(rc.Config):
    """Settings read without selecting a storage root."""

    profile: str = rc.field(
        "APPRC_EXAMPLE_CONFIG_PROFILE",
        default="default",
        title="Profile",
        explanation_short="Named profile resolved from env layers.",
    )
    debug: bool = rc.field(
        "APPRC_EXAMPLE_CONFIG_DEBUG",
        default=False,
        title="Debug",
        explanation_short="Boolean value used to show type coercion.",
    )
