"""Application settings for the combined-capability example."""

from pathlib import Path

import apprc as rc
from user_dotenv_with_storage.config.app import MyRC


@MyRC.config("app", prefix="APPRC_EXAMPLE_BOTH_", title="Application")
class AppSettings(rc.Config):
    """Settings with user-wide and storage-local override scopes."""

    storage_root: Path = rc.field(
        "APPRC_EXAMPLE_BOTH_STORAGE",
        editable=False,
        required=True,
        title="Storage root",
        explanation_short="Active storage root selected for this run.",
    )
    profile: str = rc.field(
        "APPRC_EXAMPLE_BOTH_PROFILE",
        default="default",
        title="Profile",
        explanation_short="Value that may be user-wide or storage-local.",
    )
    api_token: str = rc.field(
        "APPRC_EXAMPLE_BOTH_API_TOKEN",
        required=True,
        secret=True,
        title="API token",
        explanation_short="Required secret redacted by example output.",
    )
