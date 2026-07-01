"""Shared Example App config declarations for AppRC tests.

The production package expects applications to provide their own config owner
inventory. Tests use this tiny fake application so storage, dotenv, CLI, and
TUI behavior can be exercised without depending on a downstream app.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pytest import MonkeyPatch
from typer.testing import Result

from apprc import AppConfigKit
from apprc import (
    EnvConfig,
    EnvBootstrapResult,
    config_owner_for,
    env_field,
    env_owner,
)
from apprc.definition.env_config.sentinels import CONFIG_MISSING
from apprc.user_files.storage_roots.registry import (
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


@env_owner(
    key="global",
    title="Global",
    env_prefix="STORAGE_FREE_APP_",
    rc_path=("global",),
)
class StorageFreeExampleEnv(EnvConfig):
    """Storage-free env section used by AppRC integration tests."""

    profile: str = env_field(
        "PROFILE",
        default="default",
        title="Profile",
        explanation_short="Named profile used by the storage-free app.",
    )
    enabled: bool = env_field(
        "ENABLED",
        default=True,
        title="Enabled",
        explanation_short="Turns the storage-free app on or off.",
    )


STORAGE_FREE_EXAMPLE_OWNER = config_owner_for(StorageFreeExampleEnv)


def assert_config_home_cli_error(result: Result) -> None:
    """Assert that a CLI failure reports AppRC config-home readiness.

    :param result: Captured Typer invocation result.
    """
    assert result.exit_code != 0, result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "config-home" in result.output
    assert (
        "AppRC config home" in result.output
        or "AppRC-managed file" in result.output
    )
    assert "Traceback" not in result.output
    assert "ConfigHomeError" not in result.output
    assert "Invalid value for KEY" not in result.output
    assert "Invalid value for 'KEY'" not in result.output
    assert "Invalid value for --storage" not in result.output
    assert 'Invalid value for "--storage"' not in result.output
    assert "Invalid value for '--storage'" not in result.output
    assert "Invalid value for --name" not in result.output
    assert 'Invalid value for "--name"' not in result.output
    assert "Invalid value for '--name'" not in result.output


def block_config_home_with_file(kit: AppConfigKit) -> Path:
    """Replace the app config home directory with a blocking file.

    :param kit: App config facade under test.
    :return: Path that now blocks config-home creation.
    """
    config_home = kit.spec.config_home()
    config_home.parent.mkdir(parents=True, exist_ok=True)
    config_home.write_text("not a directory", encoding="utf-8")
    return config_home


@dataclass(slots=True)
class ApprcExampleAppConfigState:
    """Host CLI state used by generated config app tests."""

    env_bootstrap: EnvBootstrapResult | None
    storage: str | None = None


@dataclass(slots=True)
class StorageFreeExampleConfigState:
    """Host CLI state used by storage-free generated config tests."""

    env_bootstrap: EnvBootstrapResult | None = None
    storage: str | None = None


@dataclass(slots=True)
class StorageFreeExampleConfigStateWithoutStorage:
    """Storage-free host CLI state that has no storage selector field."""

    env_bootstrap: EnvBootstrapResult | None = None


def build_apprc_example_app_kit() -> AppConfigKit:
    """Return a tiny AppConfigKit that behaves like a real application."""
    return AppConfigKit.storage_only(
        app_name="apprc_example_app",
        display_name="Example App",
        config_package="apprc_storage_only_example",
        envs=(ApprcExampleAppEnv,),
        storage_env_key="APPRC_EXAMPLE_APP_STORAGE",
        index_filename="apprc_example_app.apprc.toml",
    )


def build_storage_free_example_kit() -> AppConfigKit:
    """Return a tiny AppConfigKit that does not use storage."""
    return AppConfigKit.app_wide_config(
        app_name="storage_free_app",
        display_name="Storage-Free App",
        config_package="apprc_env_only_example",
        envs=(StorageFreeExampleEnv,),
        index_filename="storage_free_app.apprc.toml",
    )


def set_apprc_example_app_apprc_toml(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> Path:
    """Point the example app at a test AppRC TOML file."""
    index_path, _ = set_apprc_example_app_bootstrap(monkeypatch, tmp_path)
    return index_path


def create_empty_apprc_example_app_apprc_toml(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> Path:
    """Point the example app at an empty AppRC TOML file."""
    index_path = set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text("", encoding="utf-8")
    return index_path


def set_apprc_example_app_bootstrap(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    *,
    apprc_toml: Path | None = None,
    storage_root: Path | None = None,
) -> tuple[Path, Path]:
    """Point the example app at explicit bootstrap environment variables."""
    index_path = (
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
        str(index_path),
    )
    monkeypatch.setenv(
        "APPRC_EXAMPLE_APP_STORAGE",
        str(active_storage_root.resolve()),
    )
    return index_path, active_storage_root


def apprc_example_app_state(
    kit: AppConfigKit,
    storage_root: Path,
) -> ApprcExampleAppConfigState:
    """Return generic CLI state with one active storage root."""
    return ApprcExampleAppConfigState(
        env_bootstrap=EnvBootstrapResult(
            shared_env=None,
            storage_env=storage_root / kit.spec.storage_env_filename,
            env_files=(),
            index_path=kit.spec.required_index_path(),
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
        path=kit.spec.required_index_path(),
        storage_env_filename=kit.spec.storage_env_filename,
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
        path=kit.spec.required_index_path(),
    )
