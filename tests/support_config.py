"""Shared Example App config declarations for AppRC tests.

The production package expects applications to provide their own config
inventory. Tests use this tiny fake application so storage, dotenv, CLI, and
TUI behavior can be exercised without depending on a downstream app.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pytest import MonkeyPatch
from rich.text import Text
from typer.testing import Result

import apprc as rc
from apprc.definition.app_config.kit import AppConfigKit
from apprc.runtime.result import EnvBootstrapResult
from apprc.user_files.storage_roots.registry import (
    StorageRegistry,
    record_archived_storage,
    register_storage,
)


def compact_cli_output(result: Result) -> str:
    """Return rendered CLI text without terminal presentation details.

    Typer and Rich may insert ANSI codes, whitespace, or table borders inside
    a phrase according to the host terminal. Content assertions use this
    representation so those presentation details cannot change their result.

    :param result: Captured command result.
    :return: Command text without styling, whitespace, or box-drawing glyphs.
    """
    plain = Text.from_ansi(result.output).plain
    return "".join(
        character
        for character in plain
        if not character.isspace() and not "\u2500" <= character <= "\u257f"
    )


_APPRC_EXAMPLE_APP_RC = rc.AppRC(
    app_id="apprc_example_app",
    display_name="Example App",
    config_package="user_dotenv_with_storage.config",
    user_dotenv=rc.UserDotenv(),
    storage=rc.Storage(selector_env_key="APPRC_EXAMPLE_APP_STORAGE"),
)


@_APPRC_EXAMPLE_APP_RC.config(
    "app",
    title="App",
    prefix="APPRC_EXAMPLE_APP_",
    rc_path=("app",),
)
class ApprcExampleAppEnv(rc.Config):
    """Example App env section used by AppRC integration tests."""

    storage_root: Path = rc.field(
        "APPRC_EXAMPLE_APP_STORAGE",
        editable=False,
        required=True,
    )
    profile: str = rc.field(
        "APPRC_EXAMPLE_APP_PROFILE",
        default="default",
        title="Profile",
        explanation_short="Named profile used by the example app.",
        explanation_long=(
            "Named profile used by the example app. Longer context appears in "
            "the modal editor."
        ),
    )
    mode: str = rc.field(
        "APPRC_EXAMPLE_APP_MODE",
        default="AUTO",
        title="Mode",
        explanation_short="Operating mode used by Example App commands.",
        choices=("AUTO", "MANUAL"),
    )
    enabled: bool = rc.field(
        "APPRC_EXAMPLE_APP_ENABLED",
        default=True,
        title="Enabled",
        explanation_short="Turns the example app on or off.",
    )
    retry_count: int = rc.field(
        "APPRC_EXAMPLE_APP_RETRY_COUNT",
        default=3,
        title="Retry count",
        explanation_short="Maximum number of retry attempts.",
    )
    cache_dir: Path = rc.field(
        "APPRC_EXAMPLE_APP_CACHE_DIR",
        default=Path("cache"),
        title="Cache directory",
        explanation_short="Storage-local cache path.",
    )
    access_token: str = rc.field(
        "APPRC_EXAMPLE_APP_ACCESS_TOKEN",
        title="Access token",
        explanation_short="Required secret token.",
        explanation_long=(
            "Secret token required by the example app when no shell "
            "environment or local override provides one."
        ),
        required=True,
        secret=True,
    )


APPRC_EXAMPLE_APP_OWNER = rc.schema.owner_for(ApprcExampleAppEnv)
APPRC_EXAMPLE_APP_OWNERS = (APPRC_EXAMPLE_APP_OWNER,)


_STORAGE_FREE_APP_RC = rc.AppRC(
    app_id="storage_free_app",
    display_name="Storage-Free App",
    config_package="user_dotenv.config",
    user_dotenv=rc.UserDotenv(),
)


@_STORAGE_FREE_APP_RC.config(
    "global",
    title="Global",
    prefix="STORAGE_FREE_APP_",
    rc_path=("global",),
)
class StorageFreeExampleEnv(rc.Config):
    """Storage-free env section used by AppRC integration tests."""

    profile: str = rc.field(
        "STORAGE_FREE_APP_PROFILE",
        default="default",
        title="Profile",
        explanation_short="Named profile used by the storage-free app.",
    )
    enabled: bool = rc.field(
        "STORAGE_FREE_APP_ENABLED",
        default=True,
        title="Enabled",
        explanation_short="Turns the storage-free app on or off.",
    )


STORAGE_FREE_EXAMPLE_OWNER = rc.schema.owner_for(StorageFreeExampleEnv)


def assert_apprc_dir_cli_error(result: Result) -> None:
    """Assert that a CLI failure reports AppRC-directory readiness.

    :param result: Captured Typer invocation result.
    """
    assert result.exit_code != 0, result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "AppRC" in result.output
    assert (
        "AppRC directory" in result.output
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


def block_apprc_dir_with_file(kit: AppConfigKit) -> Path:
    """Replace the AppRC directory with a blocking file.

    :param kit: App config facade under test.
    :return: Path that now blocks config-home creation.
    """
    apprc_dir = kit.spec.apprc_dir()
    apprc_dir.parent.mkdir(parents=True, exist_ok=True)
    apprc_dir.write_text("not a directory", encoding="utf-8")
    return apprc_dir


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


def build_apprc_example_app_kit(
    *,
    storage_required: bool = True,
) -> AppConfigKit:
    """Return a tiny storage-capable AppConfigKit.

    :param storage_required: Whether runtime requires an active storage by
        default.
    :return: Isolated application config kit for tests.
    """
    app_rc = rc.AppRC(
        app_id="apprc_example_app",
        display_name="Example App",
        config_package="user_dotenv_with_storage.config",
        user_dotenv=rc.UserDotenv(),
        storage=rc.Storage(
            selector_env_key="APPRC_EXAMPLE_APP_STORAGE",
            required=storage_required,
        ),
    )
    app_rc.config(
        "app",
        title="App",
        prefix="APPRC_EXAMPLE_APP_",
        rc_path=("app",),
    )(ApprcExampleAppEnv)
    return app_rc.kit


def build_storage_free_example_kit() -> AppConfigKit:
    """Return a tiny AppConfigKit that does not use storage."""
    app_rc = rc.AppRC(
        app_id="storage_free_app",
        display_name="Storage-Free App",
        config_package="user_dotenv.config",
        user_dotenv=rc.UserDotenv(),
    )
    app_rc.config(
        "global",
        title="Global",
        prefix="STORAGE_FREE_APP_",
        rc_path=("global",),
    )(StorageFreeExampleEnv)
    return app_rc.kit


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
        else tmp_path / "config" / "apprc_example_app" / "apprc.toml"
    )
    active_storage_root = (
        storage_root
        if storage_root is not None
        else tmp_path / "default-storage"
    )
    active_storage_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("APPRC_EXAMPLE_APP_APPRC_DIR", str(index_path.parent))
    register_storage(
        name="default",
        root=active_storage_root,
        path=index_path,
    )
    monkeypatch.setenv(
        "APPRC_EXAMPLE_APP_STORAGE",
        "default",
    )
    return index_path, active_storage_root


def apprc_example_app_state(
    kit: AppConfigKit,
    storage_root: Path,
) -> ApprcExampleAppConfigState:
    """Return generic CLI state with one active storage root."""
    return ApprcExampleAppConfigState(
        env_bootstrap=EnvBootstrapResult(
            defaults_dotenv=None,
            storage_dotenv=storage_root / kit.spec.storage_dotenv_filename,
            env_files=(),
            apprc_toml=kit.spec.preferred_apprc_toml_path(),
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
        path=kit.spec.preferred_apprc_toml_path(),
        storage_dotenv_filename=kit.spec.storage_dotenv_filename,
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
        path=kit.spec.preferred_apprc_toml_path(),
    )
