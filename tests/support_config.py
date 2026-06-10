"""Shared example config declarations for AppRC tests.

The production package expects applications to provide their own config owner
inventory. Tests use this tiny fake application so storage, dotenv, CLI, and
TUI behavior can be exercised without depending on a downstream app.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from apprc import AppConfigKit
from apprc.config import (
    CONFIG_MISSING,
    ConfigOwner,
    EnvBootstrapResult,
    config_field,
)

EXAMPLE_OWNER = ConfigOwner(
    key="app",
    title="App",
    env_prefix="EXAMPLE_",
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
            explanation="Operating mode used by example-app commands.",
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
EXAMPLE_OWNERS = (EXAMPLE_OWNER,)


@dataclass(slots=True)
class ExampleConfigState:
    """Root CLI state used by generated config app tests."""

    env_bootstrap: EnvBootstrapResult | None
    storage: str | None = None


def build_example_kit() -> AppConfigKit:
    """Return a tiny AppConfigKit that behaves like a real application."""
    return AppConfigKit(
        app_name="example",
        display_name="Example",
        config_package="apprc.config",
        owners=EXAMPLE_OWNERS,
        storage_root_env_key="EXAMPLE_D_STORAGE",
        registry_filename="example.toml",
        local_env_filename=".env.example",
    )


def example_state(
    kit: AppConfigKit,
    storage_root: Path,
) -> ExampleConfigState:
    """Return generic CLI state with one active storage root."""
    return ExampleConfigState(
        env_bootstrap=EnvBootstrapResult(
            shared_env=None,
            local_env=storage_root / ".env.example",
            env_file=None,
            registry_path=kit.registry_path(),
            storage_name="alpha",
            storage_root=storage_root,
            used_default_storage=True,
            storage_count=1,
        ),
        storage="alpha",
    )
