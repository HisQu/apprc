"""Application settings for the workspace example."""

from pathlib import Path

import apprc as rc
from workspace.config.app import MyRC


@MyRC.config("app", prefix="APPRC_EXAMPLE_", title="Application")
class AppSettings(rc.Config):
    """Settings used by the workspace example."""

    workspace_root: Path = rc.field(
        "APPRC_EXAMPLE_WORKSPACE",
        editable=False,
        required=True,
        title="Workspace root",
        explanation_short="Active workspace root selected for this run.",
    )
    profile: str = rc.field(
        "APPRC_EXAMPLE_WORKSPACE_PROFILE",
        default="default",
        title="Profile",
        explanation_short="Named profile stored in the selected workspace.",
    )
    api_token: str = rc.field(
        "APPRC_EXAMPLE_WORKSPACE_API_TOKEN",
        required=True,
        secret=True,
        title="API token",
        explanation_short="Required secret redacted by example output.",
    )
