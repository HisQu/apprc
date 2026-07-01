"""AppRC declarations for the env-only example app."""

from __future__ import annotations

# == Internal ================================
import apprc


@apprc.env_owner(
    key="env_only",
    title="Env Only",
    env_prefix="APPRC_EXAMPLE_ENV_ONLY_",
    rc_path=("env_only",),
)
class EnvOnlyConfig(apprc.EnvConfig):
    """Config fields for the setup-light env-only example."""

    profile: str = apprc.env_field(
        "PROFILE",
        default="default",
        title="Profile",
        explanation_short="Named profile resolved from env layers.",
    )
    debug: bool = apprc.env_field(
        "DEBUG",
        default=False,
        title="Debug",
        explanation_short="Boolean value used to show type coercion.",
    )


KIT = apprc.AppConfigKit.env_only(
    app_name="apprc-example-env-only",
    display_name="AppRC Env Only Example",
    config_package="apprc_env_only_example",
    envs=(EnvOnlyConfig,),
    command_name="apprc-env-only",
)
