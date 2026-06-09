"""Shared demo config declarations for AppRC tests.

The production package expects applications to provide their own config owner
inventory. Tests use this tiny fake application so storage, dotenv, CLI, and
TUI behavior can be exercised without depending on Haiu.
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

DEMO_OWNER = ConfigOwner(
    key="runtime",
    title="Runtime",
    env_prefix="DEMO_",
    rc_path=("runtime",),
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
            "model",
            "MODEL",
            str,
            default="demo-model",
            title="Demo model",
            explanation=(
                "Model used by the demo runtime. Longer context appears in "
                "the modal editor."
            ),
        ),
        config_field(
            "api_token",
            "API_TOKEN",
            str,
            default=CONFIG_MISSING,
            title="API token",
            explanation_short="Required provider token.",
            explanation_long=(
                "Secret token required by the demo runtime when no shell "
                "environment or local override provides one."
            ),
            required=True,
            secret=True,
        ),
        config_field(
            "strategy",
            "STRATEGY",
            str,
            default="VECTOR",
            title="Strategy",
            explanation="Selection strategy for demo candidates.",
            choices=("VECTOR", "WEIGHT"),
        ),
        config_field(
            "enabled",
            "ENABLED",
            bool,
            default=True,
            title="Enabled",
            explanation="Turns the demo runtime on or off.",
        ),
        config_field(
            "retry_count",
            "RETRY_COUNT",
            int,
            default=3,
            title="Retry count",
            explanation="Maximum number of demo retries.",
        ),
        config_field(
            "cache_dir",
            "CACHE_DIR",
            Path,
            default=Path("cache"),
            title="Cache directory",
            explanation="Storage-local cache path.",
        ),
    ),
)
DEMO_OWNERS = (DEMO_OWNER,)


@dataclass(slots=True)
class DemoConfigState:
    """Root CLI state used by generated config app tests."""

    env_bootstrap: EnvBootstrapResult | None
    storage: str | None = None


def build_demo_kit() -> AppConfigKit:
    """Return a tiny AppConfigKit that behaves like a real application."""
    return AppConfigKit(
        app_name="demo",
        display_name="Demo",
        config_package="apprc.config",
        owners=DEMO_OWNERS,
        storage_root_env_key="DEMO_D_STORAGE",
        registry_filename="demo.toml",
        local_env_filename=".env.demo",
    )


def demo_state(
    kit: AppConfigKit,
    storage_root: Path,
) -> DemoConfigState:
    """Return generic CLI state with one active storage root."""
    return DemoConfigState(
        env_bootstrap=EnvBootstrapResult(
            shared_env=None,
            local_env=storage_root / ".env.demo",
            env_file=None,
            registry_path=kit.registry_path(),
            storage_name="alpha",
            storage_root=storage_root,
            used_default_storage=True,
            storage_count=1,
        ),
        storage="alpha",
    )
