"""Application settings for the storage example."""

from pathlib import Path

import apprc as rc
from storage.config.app import MyRC


@MyRC.config("app", prefix="APPRC_EXAMPLE_STORAGE_", title="Application")
class AppSettings(rc.Config):
    """Settings that belong to the selected storage."""

    storage_root: Path = rc.field(
        "APPRC_EXAMPLE_STORAGE_STORAGE",
        editable=False,
        required=True,
        title="Storage root",
        explanation_short="Active storage root selected for this run.",
    )
    profile: str = rc.field(
        "APPRC_EXAMPLE_STORAGE_PROFILE",
        default="default",
        title="Profile",
        explanation_short="Named profile stored in the selected storage.",
    )
    api_token: str = rc.field(
        "APPRC_EXAMPLE_STORAGE_API_TOKEN",
        required=True,
        secret=True,
        title="API token",
        explanation_short="Required secret redacted by example output.",
    )
