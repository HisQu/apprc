"""AppRC declarations for the explicit env precedence example app."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path

# == Internal ================================
import apprc as rc


MyRC = rc.AppRC.storage_only(
    app_name="apprc-example-explicit-env-precedence",
    display_name="AppRC Explicit Env Precedence Example",
    config_package="apprc_explicit_env_precedence_example",
    storage_env_key="APPRC_EXAMPLE_PRECEDENCE_ROOT",
    command_name="apprc-explicit-env-precedence",
)


@MyRC.config(
    "precedence",
    prefix="APPRC_EXAMPLE_PRECEDENCE_",
    title="Precedence",
)
class ExplicitEnvPrecedenceConfig(rc.Config):
    """Storage fields used to demonstrate explicit env-file precedence."""

    storage_root: Path = rc.field(
        "APPRC_EXAMPLE_PRECEDENCE_ROOT",
        editable=False,
        required=True,
        title="Storage root",
        explanation_short="Storage selector used in precedence examples.",
    )
    label: str = rc.field(
        "APPRC_EXAMPLE_PRECEDENCE_LABEL",
        default="default",
        title="Label",
        explanation_short="Value overridden by shell and explicit env files.",
    )


KIT = MyRC.kit
