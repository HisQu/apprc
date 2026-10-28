"""Application settings for the combined-capability example."""

from pathlib import Path

import apprc as rc
from user_dotenv_with_workspace.config.app import MyRC


@MyRC.config("app", prefix="APPRC_EXAMPLE_BOTH_", title="Application")
class AppSettings(rc.Config):
    """Settings with user-wide and workspace-local override scopes."""

    workspace_root: Path = rc.field(
        "APPRC_EXAMPLE_BOTH_WORKSPACE",
        editable=False,
        required=True,
        title="Workspace root",
        explanation_short="Active workspace root selected for this run.",
    )
    profile: str = rc.field(
        "APPRC_EXAMPLE_BOTH_PROFILE",
        default="default",
        title="Profile",
        explanation_short="Value that may be user-wide or workspace-local.",
    )
    api_token: str = rc.field(
        "APPRC_EXAMPLE_BOTH_API_TOKEN",
        required=True,
        secret=True,
        title="API token",
        explanation_short="Required secret redacted by example output.",
    )
