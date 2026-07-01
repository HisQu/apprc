"""AppRC declarations for the storage-only example app."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path

# == Internal ================================
import apprc


@apprc.env_owner(
    key="storage_only",
    title="Storage Only",
    env_prefix="APPRC_EXAMPLE_STORAGE_",
    rc_path=("storage_only",),
)
class StorageOnlyConfig(apprc.EnvConfig):
    """Storage-scoped config fields with typed and secret values."""

    storage_root: Path = apprc.env_field(
        "ROOT",
        editable=False,
        required=True,
        title="Storage root",
        explanation_short="Active storage root selected for this run.",
    )
    profile: str = apprc.env_field(
        "PROFILE",
        default="default",
        title="Profile",
        explanation_short="Named profile stored in the selected storage.",
    )
    mode: str = apprc.env_field(
        "MODE",
        default="AUTO",
        title="Mode",
        explanation_short="Choice field rendered by CLI and TUI surfaces.",
        choices=("AUTO", "MANUAL"),
    )
    enabled: bool = apprc.env_field(
        "ENABLED",
        default=True,
        title="Enabled",
        explanation_short="Boolean storage-local feature switch.",
    )
    retry_count: int = apprc.env_field(
        "RETRY_COUNT",
        default=3,
        title="Retry count",
        explanation_short="Integer value used to show type coercion.",
    )
    cache_dir: Path = apprc.env_field(
        "CACHE_DIR",
        default=Path("cache"),
        title="Cache directory",
        explanation_short="Storage-local relative path value.",
    )
    api_token: str = apprc.env_field(
        "API_TOKEN",
        required=True,
        secret=True,
        title="API token",
        explanation_short="Required secret redacted by example output.",
    )


KIT = apprc.AppConfigKit.storage_only(
    app_name="apprc-example-storage-only",
    display_name="AppRC Storage Only Example",
    config_package="apprc_storage_only_example",
    envs=(StorageOnlyConfig,),
    storage_env_key="APPRC_EXAMPLE_STORAGE_ROOT",
    command_name="apprc-storage-only",
)

OWNERS = (apprc.config_owner_for(StorageOnlyConfig),)
