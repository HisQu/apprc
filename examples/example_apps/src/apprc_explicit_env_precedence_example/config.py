"""AppRC declarations for the explicit env precedence example app."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path

# == Internal ================================
import apprc


@apprc.env_owner(
    key="precedence",
    title="Precedence",
    env_prefix="APPRC_EXAMPLE_PRECEDENCE_",
    rc_path=("precedence",),
)
class ExplicitEnvPrecedenceConfig(apprc.EnvConfig):
    """Storage fields used to demonstrate explicit env-file precedence."""

    storage_root: Path = apprc.env_field(
        "ROOT",
        editable=False,
        required=True,
        title="Storage root",
        explanation_short="Storage selector used in precedence examples.",
    )
    label: str = apprc.env_field(
        "LABEL",
        default="default",
        title="Label",
        explanation_short="Value overridden by shell and explicit env files.",
    )


KIT = apprc.AppConfigKit.storage_only(
    app_name="apprc-example-explicit-env-precedence",
    display_name="AppRC Explicit Env Precedence Example",
    config_package="apprc_explicit_env_precedence_example",
    envs=(ExplicitEnvPrecedenceConfig,),
    storage_env_key="APPRC_EXAMPLE_PRECEDENCE_ROOT",
    command_name="apprc-explicit-env-precedence",
)
