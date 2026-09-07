"""Application settings for the user-dotenv example."""

import apprc as rc
from user_dotenv.config.app import MyRC


@MyRC.config("app", prefix="APPRC_EXAMPLE_USER_", title="Application")
class AppSettings(rc.Config):
    """Settings that may be overridden in a user-wide dotenv."""

    profile: str = rc.field(
        "APPRC_EXAMPLE_USER_PROFILE",
        default="default",
        title="Profile",
        explanation_short="Named profile saved in the user dotenv.",
    )
    debug: bool = rc.field(
        "APPRC_EXAMPLE_USER_DEBUG",
        default=False,
        title="Debug",
        explanation_short="Boolean value used to show type coercion.",
    )
