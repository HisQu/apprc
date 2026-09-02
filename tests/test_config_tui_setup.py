from __future__ import annotations

# == Standard Library ===========================================
from pathlib import Path

# == 3rd Party ==================================================
import pytest
from rich.text import Text

# == Internal ===================================================
from apprc.definition.app_config.kit import AppConfigKit
from apprc.interfaces.tui._primitives import (
    ConfirmScreen,
    PathInputResult,
    StorageNameResult,
)
from apprc.user_files.setup.text import setup_overview_text
from apprc.interfaces.tui.setup import ConfigSetupApp
from apprc.interfaces.tui.editor import ConfigEditorApp
from apprc.interfaces.tui.storage.selection import ActivePathStorageSelection
from apprc.user_files.storage_roots.registry import (
    load_storage_registry_or_empty,
)
from tests.support_config import (
    StorageFreeExampleEnv,
    build_apprc_example_app_kit,
    build_storage_free_example_kit,
)


def test_setup_overview_text_describes_storage_route() -> None:
    text = setup_overview_text(build_apprc_example_app_kit())

    assert "selected storage root" in text


def test_setup_overview_text_describes_app_wide_route() -> None:
    text = setup_overview_text(build_storage_free_example_kit())

    assert "app-wide config" in text


def test_config_setup_app_stores_kit() -> None:
    kit = build_apprc_example_app_kit()
    app = ConfigSetupApp(kit=kit)

    assert app.kit is kit


@pytest.mark.asyncio
async def test_editor_setup_initializes_path_without_requiring_registration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Create usable storage while leaving the missing index untouched.

    :param monkeypatch: Fixture used to script modal answers.
    :param tmp_path: Temporary root for config and storage files.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    kit = build_apprc_example_app_kit()
    index_path = kit.spec.index_path()
    storage_root = tmp_path / "storage"
    editor = ConfigEditorApp(
        kit=kit,
        storage_registry=load_storage_registry_or_empty(index_path),
    )
    responses: list[object | None] = [
        PathInputResult(path=storage_root),
        "setup",
        "done",
    ]
    screens: list[object] = []

    async def push_screen_wait(screen: object) -> object | None:
        screens.append(screen)
        return responses.pop(0)

    monkeypatch.setattr(editor, "push_screen_wait", push_screen_wait)

    async with editor.run_test() as pilot:
        await pilot.pause()
        await editor.setup_workflow.open_setup_flow()

        assert (storage_root / ".env.apprc-storage").is_file()
        assert not index_path.exists()
        assert editor.active_storage_root == storage_root.resolve()
        assert isinstance(editor.selection, ActivePathStorageSelection)

    summary = screens[-1]
    assert isinstance(summary, ConfirmScreen)
    assert isinstance(summary.message, Text)
    assert f'export APPRC_EXAMPLE_APP_STORAGE="{storage_root.resolve()}"' in (
        summary.message.plain
    )


@pytest.mark.asyncio
async def test_editor_setup_can_register_initialized_storage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Create the first named-storage index after setup when requested.

    :param monkeypatch: Fixture used to script modal answers.
    :param tmp_path: Temporary root for config and storage files.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    kit = build_apprc_example_app_kit()
    index_path = kit.spec.index_path()
    storage_root = tmp_path / "storage"
    editor = ConfigEditorApp(
        kit=kit,
        storage_registry=load_storage_registry_or_empty(index_path),
    )
    responses: list[object | None] = [
        PathInputResult(path=storage_root),
        "setup",
        "register",
        StorageNameResult(name="alpha"),
    ]

    async def push_screen_wait(_: object) -> object | None:
        return responses.pop(0)

    monkeypatch.setattr(editor, "push_screen_wait", push_screen_wait)

    async with editor.run_test() as pilot:
        await pilot.pause()
        await editor.setup_workflow.open_setup_flow()

        assert editor.storage_registry is not None
        assert editor.storage_registry.selected("alpha").root == (
            storage_root.resolve()
        )
        assert index_path.is_file()


@pytest.mark.asyncio
async def test_editor_setup_initializes_app_wide_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Run app-wide setup from an editor without storage controls.

    :param monkeypatch: Fixture used to isolate files and close the summary.
    :param tmp_path: Temporary root for the config home.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    kit = build_storage_free_example_kit()
    editor = ConfigEditorApp(kit=kit, storage_registry=None)

    async def push_screen_wait(_: object) -> object | None:
        return "done"

    monkeypatch.setattr(editor, "push_screen_wait", push_screen_wait)

    async with editor.run_test() as pilot:
        await pilot.pause()
        await editor.setup_workflow.open_setup_flow()

    assert kit.spec.app_wide_env_path().is_file()


@pytest.mark.asyncio
async def test_editor_setup_explains_env_only_mode_without_writes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Explain env-only setup without creating AppRC-managed files.

    :param monkeypatch: Fixture used to isolate files and capture the modal.
    :param tmp_path: Temporary root for the config home.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    kit = AppConfigKit.env_only(
        app_name="env_app",
        display_name="Env App",
        config_package="apprc",
        envs=(StorageFreeExampleEnv,),
    )
    editor = ConfigEditorApp(kit=kit, storage_registry=None)
    screens: list[object] = []

    async def push_screen_wait(screen: object) -> object | None:
        screens.append(screen)
        return "done"

    monkeypatch.setattr(editor, "push_screen_wait", push_screen_wait)

    async with editor.run_test() as pilot:
        await pilot.pause()
        await editor.setup_workflow.open_setup_flow()

    summary = screens[-1]
    assert isinstance(summary, ConfirmScreen)
    assert isinstance(summary.message, Text)
    assert "writes: none" in summary.message.plain
    assert not kit.spec.app_wide_env_path().exists()
    assert not kit.spec.index_path().exists()
