"""Application settings for the process-environment example."""

import apprc as rc
from process_env.config.app import MyRC


@MyRC.config("app", prefix="APPRC_EXAMPLE_PROCESS_", title="Application")
class AppSettings(rc.Config):
    """Settings resolved without AppRC-managed user files."""

    profile: str = rc.field(
        "APPRC_EXAMPLE_PROCESS_PROFILE",
        default="default",
        title="Profile",
        explanation_short="Named profile read from the process environment.",
    )
    debug: bool = rc.field(
        "APPRC_EXAMPLE_PROCESS_DEBUG",
        default=False,
        title="Debug",
        explanation_short="Boolean value used to show type coercion.",
    )
