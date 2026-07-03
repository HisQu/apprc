"""Env-only example AppRC section."""

# == Internal ================================
import apprc as rc
from env_only.config.app import MyRC


@MyRC.config("env_only", prefix="APPRC_EXAMPLE_ENV_ONLY_", title="Env Only")
class EnvOnlyConfig(rc.Config):
    """Config fields for the setup-light env-only example."""

    profile: str = rc.field(
        "APPRC_EXAMPLE_ENV_ONLY_PROFILE",
        default="default",
        title="Profile",
        explanation_short="Named profile resolved from env layers.",
    )
    debug: bool = rc.field(
        "APPRC_EXAMPLE_ENV_ONLY_DEBUG",
        default=False,
        title="Debug",
        explanation_short="Boolean value used to show type coercion.",
    )
