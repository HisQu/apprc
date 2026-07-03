"""AppRC declarations for the env-only example app."""

from __future__ import annotations

# == Internal ================================
import apprc as rc


MyRC = rc.AppRC.env_only(
    app_name="apprc-example-env-only",
    display_name="AppRC Env Only Example",
    config_package="apprc_env_only_example",
    command_name="apprc-env-only",
)


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


KIT = MyRC.kit
