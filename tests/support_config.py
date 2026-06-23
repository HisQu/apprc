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
    EnvConfig,
    EnvBootstrapResult,
    config_owner_for,
    env_field,
    env_owner,
)
from apprc.config.sentinels import CONFIG_MISSING
from apprc.config.storage.registry import (
    StorageRegistry,
    record_archived_storage,
    register_storage,
)


@env_owner(
    key="app",
    title="App",
    env_prefix="APPRC_EXAMPLE_APP_",
    rc_path=("app",),
)
class ApprcExampleAppEnv(EnvConfig):
    """Example App env section used by AppRC integration tests."""

    storage_root: Path = env_field(
        "STORAGE",
        editable=False,
        required=True,
    )
    profile: str = env_field(
        "PROFILE",
        default="default",
        title="Profile",
        explanation_short="Named profile used by the example app.",
        explanation_long=(
            "Named profile used by the example app. Longer context appears in "
            "the modal editor."
        ),
    )
    mode: str = env_field(
        "MODE",
        default="AUTO",
        title="Mode",
        explanation_short="Operating mode used by Example App commands.",
        choices=("AUTO", "MANUAL"),
    )
    enabled: bool = env_field(
        "ENABLED",
        default=True,
        title="Enabled",
        explanation_short="Turns the example app on or off.",
    )
    retry_count: int = env_field(
        "RETRY_COUNT",
        default=3,
        title="Retry count",
        explanation_short="Maximum number of retry attempts.",
    )
    cache_dir: Path = env_field(
        "CACHE_DIR",
        default=Path("cache"),
        title="Cache directory",
        explanation_short="Storage-local cache path.",
    )
    access_token: str = env_field(
        "ACCESS_TOKEN",
        default=CONFIG_MISSING,
        title="Access token",
        explanation_short="Required secret token.",
        explanation_long=(
            "Secret token required by the example app when no shell "
            "environment or local override provides one."
        ),
        required=True,
        secret=True,
    )


APPRC_EXAMPLE_APP_OWNER = config_owner_for(ApprcExampleAppEnv)
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
        envs=(ApprcExampleAppEnv,),
        storage_env_key="APPRC_EXAMPLE_APP_STORAGE",
        apprc_toml_filename="apprc_example_app.apprc.toml",
        local_env_filename=".env.apprc_example_app",
    )


def set_apprc_example_app_apprc_toml(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> Path:
    """Point the example app at a test AppRC TOML file."""
    apprc_toml_path, _ = set_apprc_example_app_bootstrap(monkeypatch, tmp_path)
    return apprc_toml_path


def create_empty_apprc_example_app_apprc_toml(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> Path:
    """Point the example app at an empty AppRC TOML file."""
    apprc_toml_path = set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    apprc_toml_path.parent.mkdir(parents=True, exist_ok=True)
    apprc_toml_path.write_text("", encoding="utf-8")
    return apprc_toml_path


def set_apprc_example_app_bootstrap(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    *,
    apprc_toml: Path | None = None,
    storage_root: Path | None = None,
) -> tuple[Path, Path]:
    """Point the example app at explicit bootstrap environment variables."""
    apprc_toml_path = (
        apprc_toml
        if apprc_toml is not None
        else tmp_path
        / "config"
        / "apprc_example_app"
        / "apprc_example_app.apprc.toml"
    )
    active_storage_root = (
        storage_root
        if storage_root is not None
        else tmp_path / "default-storage"
    )
    active_storage_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv(
        "APPRC_EXAMPLE_APP_APPRC_TOML",
        str(apprc_toml_path),
    )
    monkeypatch.setenv(
        "APPRC_EXAMPLE_APP_STORAGE",
        str(active_storage_root.resolve()),
    )
    return apprc_toml_path, active_storage_root


def apprc_example_app_state(
    kit: AppConfigKit,
    storage_root: Path,
) -> ApprcExampleAppConfigState:
    """Return generic CLI state with one active storage root."""
    return ApprcExampleAppConfigState(
        env_bootstrap=EnvBootstrapResult(
            shared_env=None,
            local_env=storage_root / ".env.apprc_example_app",
            env_files=(),
            apprc_toml_path=kit.spec.required_apprc_toml_path(),
            storage_selector_source="--storage",
            storage_selector_value="alpha",
            storage_name="alpha",
            storage_root=storage_root,
            storage_count=1,
        ),
        storage="alpha",
    )


def register_storage_for_kit(
    kit: AppConfigKit,
    *,
    name: str,
    root: Path,
) -> StorageRegistry:
    """Register a storage root through the kit's app contract in tests.

    :param kit: App config facade under test.
    :param name: Storage selector to write.
    :param root: Storage root directory.
    :return: Updated storage registry.
    """
    return register_storage(
        name=name,
        root=root,
        path=kit.spec.required_apprc_toml_path(),
        local_env_filename=kit.spec.local_env_filename,
    )


def record_archived_storage_for_kit(
    kit: AppConfigKit,
    *,
    name: str,
    archive: Path,
    source_root: Path,
) -> StorageRegistry:
    """Record an archived storage through the kit's app contract in tests.

    :param kit: App config facade under test.
    :param name: Storage selector to write.
    :param archive: Archive path to remember.
    :param source_root: Storage directory that produced the archive.
    :return: Updated storage registry.
    """
    return record_archived_storage(
        name=name,
        archive=archive,
        source_root=source_root,
        path=kit.spec.required_apprc_toml_path(),
    )
