"""CLI runtime example AppRC section."""

# == Standard Library ========================
from pathlib import Path

# == Internal ================================
import apprc as rc
from apprc_cli_runtime_example.config.app import MyRC


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
