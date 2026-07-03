"""AppRC declarations for the CLI runtime example app."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path

# == Internal ================================
import apprc as rc


MyRC = rc.AppRC.storage_only(
    app_name="apprc-example-cli-runtime",
    display_name="AppRC CLI Runtime Example",
    config_package="apprc_cli_runtime_example",
    storage_env_key="APPRC_EXAMPLE_RUNTIME_ROOT",
    command_name="apprc-cli-runtime",
)


@MyRC.config("runtime", prefix="APPRC_EXAMPLE_RUNTIME_", title="Runtime")
class CliRuntimeConfig(rc.Config):
    """Storage fields used by the app-owned callback runtime example."""

    storage_root: Path = rc.field(
        "APPRC_EXAMPLE_RUNTIME_ROOT",
        editable=False,
        required=True,
        title="Storage root",
        explanation_short="Active storage root selected through the runtime.",
    )
    profile: str = rc.field(
        "APPRC_EXAMPLE_RUNTIME_PROFILE",
        default="default",
        title="Profile",
        explanation_short="Runtime profile resolved after AppRC setup.",
    )
    api_token: str = rc.field(
        "APPRC_EXAMPLE_RUNTIME_API_TOKEN",
        required=True,
        secret=True,
        title="API token",
        explanation_short="Required secret redacted by runtime output.",
    )


KIT = MyRC.kit
OWNERS = KIT.spec.owners
