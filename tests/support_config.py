"""Shared Example App config declarations for AppRC tests.

The production package expects applications to provide their own config owner
inventory. Tests use this tiny fake application so storage, dotenv, CLI, and
TUI behavior can be exercised without depending on a downstream app.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pytest import MonkeyPatch

from apprc import AppConfigKit
from apprc.config import (
    CONFIG_MISSING,
    ConfigOwner,
    EnvBootstrapResult,
    config_field,
)

APPRC_EXAMPLE_APP_OWNER = ConfigOwner(
    key="app",
    title="App",
    env_prefix="APPRC_EXAMPLE_APP_",
    rc_path=("app",),
    fields=(
        config_field(
            "storage_root",
            "D_STORAGE",
            Path,
            default=CONFIG_MISSING,
            editable=False,
            required=True,
        ),
        config_field(
            "profile",
            "PROFILE",
            str,
            default="default",
            title="Profile",
            explanation=(
                "Named profile used by the example app. Longer context "
                "appears in the modal editor."
            ),
        ),
        config_field(
            "mode",
            "MODE",
            str,
            default="AUTO",
            title="Mode",
            explanation="Operating mode used by Example App commands.",
            choices=("AUTO", "MANUAL"),
        ),
        config_field(
            "enabled",
            "ENABLED",
            bool,
            default=True,
            title="Enabled",
            explanation="Turns the example app on or off.",
        ),
        config_field(
            "retry_count",
            "RETRY_COUNT",
            int,
            default=3,
            title="Retry count",
            explanation="Maximum number of retry attempts.",
        ),
        config_field(
            "cache_dir",
            "CACHE_DIR",
            Path,
            default=Path("cache"),
            title="Cache directory",
            explanation="Storage-local cache path.",
        ),
        config_field(
            "access_token",
            "ACCESS_TOKEN",
            str,
            default=CONFIG_MISSING,
            title="Access token",
            explanation_short="Required secret token.",
            explanation_long=(
                "Secret token required by the example app when no shell "
                "environment or local override provides one."
            ),
            required=True,
            secret=True,
        ),
    ),
)
APPRC_EXAMPLE_APP_OWNERS = (APPRC_EXAMPLE_APP_OWNER,)


@dataclass(slots=True)
class ApprcExampleAppConfigState:
    """Root CLI state used by generated config app tests."""

    env_bootstrap: EnvBootstrapResult | None
    storage: str | None = None


def build_apprc_example_app_kit() -> AppConfigKit:
    """Return a tiny AppConfigKit that behaves like a real application."""
    return AppConfigKit(
        app_name="apprc_example_app",
        display_name="Example App",
        config_package="apprc.config",
        owners=APPRC_EXAMPLE_APP_OWNERS,
        storage_root_env_key="APPRC_EXAMPLE_APP_D_STORAGE",
        registry_filename="apprc_example_app.toml",
        local_env_filename=".env.apprc_example_app",
    )


def set_apprc_example_app_config_file(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> Path:
    """Point the example app at a test registry file."""
    registry_path = (
        tmp_path / "config" / "apprc_example_app" / "apprc_example_app.toml"
    )
    monkeypatch.setenv("APPRC_EXAMPLE_APP_CONFIG_FILE", str(registry_path))
    return registry_path


def apprc_example_app_state(
    kit: AppConfigKit,
    storage_root: Path,
) -> ApprcExampleAppConfigState:
    """Return generic CLI state with one active storage root."""
    return ApprcExampleAppConfigState(
        env_bootstrap=EnvBootstrapResult(
            shared_env=None,
            local_env=storage_root / ".env.apprc_example_app",
            env_file=None,
            registry_path=kit.registry_path(),
            storage_name="alpha",
            storage_root=storage_root,
            used_default_storage=True,
            storage_count=1,
        ),
        storage="alpha",
    )
