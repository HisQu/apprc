"""AppRC declarations for the CLI runtime example app."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path

# == Internal ================================
import apprc


@apprc.env_owner(
    key="runtime",
    title="Runtime",
    env_prefix="APPRC_EXAMPLE_RUNTIME_",
    rc_path=("runtime",),
)
class CliRuntimeConfig(apprc.EnvConfig):
    """Storage fields used by the app-owned callback runtime example."""

    storage_root: Path = apprc.env_field(
        "ROOT",
        editable=False,
        required=True,
        title="Storage root",
        explanation_short="Active storage root selected through the runtime.",
    )
    profile: str = apprc.env_field(
        "PROFILE",
        default="default",
        title="Profile",
        explanation_short="Runtime profile resolved after AppRC setup.",
    )
    api_token: str = apprc.env_field(
        "API_TOKEN",
        required=True,
        secret=True,
        title="API token",
        explanation_short="Required secret redacted by runtime output.",
    )


KIT = apprc.AppConfigKit.storage_only(
    app_name="apprc-example-cli-runtime",
    display_name="AppRC CLI Runtime Example",
    config_package="apprc_cli_runtime_example",
    envs=(CliRuntimeConfig,),
    storage_env_key="APPRC_EXAMPLE_RUNTIME_ROOT",
    command_name="apprc-cli-runtime",
)

OWNERS = (apprc.config_owner_for(CliRuntimeConfig),)
