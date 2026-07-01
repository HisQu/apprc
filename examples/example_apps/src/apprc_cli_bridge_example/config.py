"""AppRC declarations for the CLI bridge example app."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path

# == Internal ================================
import apprc


@apprc.env_owner(
    key="bridge",
    title="Bridge",
    env_prefix="APPRC_EXAMPLE_BRIDGE_",
    rc_path=("bridge",),
)
class BridgeConfig(apprc.EnvConfig):
    """Storage fields used by the host-owned callback bridge example."""

    storage_root: Path = apprc.env_field(
        "ROOT",
        editable=False,
        required=True,
        title="Storage root",
        explanation_short="Active storage root selected through the bridge.",
    )
    profile: str = apprc.env_field(
        "PROFILE",
        default="default",
        title="Profile",
        explanation_short="Runtime profile resolved after bridge bootstrap.",
    )
    api_token: str = apprc.env_field(
        "API_TOKEN",
        required=True,
        secret=True,
        title="API token",
        explanation_short="Required secret redacted by bridge output.",
    )


KIT = apprc.AppConfigKit.storage_only(
    app_name="apprc-example-cli-bridge",
    display_name="AppRC CLI Bridge Example",
    config_package="apprc_cli_bridge_example",
    envs=(BridgeConfig,),
    storage_env_key="APPRC_EXAMPLE_BRIDGE_ROOT",
    command_name="apprc-cli-bridge",
)

OWNERS = (apprc.config_owner_for(BridgeConfig),)
