"""AppRC declarations for the storage-only example app."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path

# == Internal ================================
import apprc as rc


MyRC = rc.AppRC.storage_only(
    app_name="apprc-example-storage-only",
    display_name="AppRC Storage Only Example",
    config_package="apprc_storage_only_example",
    storage_env_key="APPRC_EXAMPLE_STORAGE_ROOT",
    command_name="apprc-storage-only",
)


@MyRC.config(
    "storage_only",
    prefix="APPRC_EXAMPLE_STORAGE_",
    title="Storage Only",
)
class StorageOnlyConfig(rc.Config):
    """Storage-scoped config fields with typed and secret values."""

    storage_root: Path = rc.field(
        "APPRC_EXAMPLE_STORAGE_ROOT",
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
    mode: str = rc.field(
        "APPRC_EXAMPLE_STORAGE_MODE",
        default="AUTO",
        title="Mode",
        explanation_short="Choice field rendered by CLI and TUI surfaces.",
        choices=("AUTO", "MANUAL"),
    )
    enabled: bool = rc.field(
        "APPRC_EXAMPLE_STORAGE_ENABLED",
        default=True,
        title="Enabled",
        explanation_short="Boolean storage-local feature switch.",
    )
    retry_count: int = rc.field(
        "APPRC_EXAMPLE_STORAGE_RETRY_COUNT",
        default=3,
        title="Retry count",
        explanation_short="Integer value used to show type coercion.",
    )
    cache_dir: Path = rc.field(
        "APPRC_EXAMPLE_STORAGE_CACHE_DIR",
        default=Path("cache"),
        title="Cache directory",
        explanation_short="Storage-local relative path value.",
    )
    api_token: str = rc.field(
        "APPRC_EXAMPLE_STORAGE_API_TOKEN",
        required=True,
        secret=True,
        title="API token",
        explanation_short="Required secret redacted by example output.",
    )


KIT = MyRC.kit
OWNERS = KIT.spec.owners
