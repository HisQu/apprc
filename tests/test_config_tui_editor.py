from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Button, DataTable

from apprc.runtime_config.app_spec import CapabilityState, StorageLayerState
from apprc.runtime_config.kit import AppConfigKit
from apprc.runtime_config.tui.editor import ConfigEditorApp
from tests.support_config import (
    ApprcExampleAppEnv,
    build_apprc_example_app_kit,
    build_storage_free_example_kit,
)


def test_editor_uses_new_storage_env_and_index_labels() -> None:
    kit = build_apprc_example_app_kit()
    editor = ConfigEditorApp(
        kit=kit,
        storage_registry=None,
        active_storage_root=Path("/tmp/storage"),
    )

    assert editor.kit.spec.storage_env_filename == ".env.apprc-storage"
    assert editor.index_label == "apprc_example_app.apprc.toml"
    assert editor.init_command.endswith("config storage add NAME PATH")


@pytest.mark.asyncio
async def test_editor_open_does_not_create_storage_env_file(
    tmp_path: Path,
) -> None:
    kit = build_apprc_example_app_kit()
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    editor = ConfigEditorApp(
        kit=kit,
        storage_registry=None,
        active_storage_root=storage_root,
    )

    async with editor.run_test() as pilot:
        await pilot.pause()
        table = editor.query_one("#field-table", DataTable)

        assert not (storage_root / ".env.apprc-storage").exists()
        assert table.row_count > 0


@pytest.mark.asyncio
async def test_editor_disables_named_storage_controls_without_index(
    tmp_path: Path,
) -> None:
    kit = build_apprc_example_app_kit()
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    editor = ConfigEditorApp(
        kit=kit,
        storage_registry=None,
        active_storage_root=storage_root,
    )

    async with editor.run_test() as pilot:
        await pilot.pause()

        assert editor.query_one("#storage-new", Button).disabled is True
        assert (
            editor.query_one("#storage-register-active", Button).disabled
            is True
        )


@pytest.mark.asyncio
async def test_editor_hides_storage_management_for_storage_free_app() -> None:
    kit = build_storage_free_example_kit()
    editor = ConfigEditorApp(
        kit=kit,
        storage_registry=None,
    )

    async with editor.run_test() as pilot:
        await pilot.pause()

        assert list(editor.query("#storage-list")) == []
        assert list(editor.query("#storage-new")) == []
        assert editor.query_one("#field-table", DataTable).row_count > 0


@pytest.mark.asyncio
async def test_editor_hides_named_storage_controls_when_disabled(
    tmp_path: Path,
) -> None:
    kit = AppConfigKit(
        app_name="path_only_app",
        display_name="Path-Only App",
        config_package="apprc.runtime_config",
        envs=(ApprcExampleAppEnv,),
        storage_env_key="PATH_ONLY_APP_STORAGE",
        storage_layer=StorageLayerState.REQUIRED,
        named_storage_layer=CapabilityState.DISABLED,
        index_filename="path_only_app.apprc.toml",
    )
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    editor = ConfigEditorApp(
        kit=kit,
        storage_registry=None,
        active_storage_root=storage_root,
    )

    async with editor.run_test() as pilot:
        await pilot.pause()

        assert list(editor.query("#storage-list")) == []
        assert list(editor.query("#storage-new")) == []
        assert editor.query_one("#field-table", DataTable).row_count > 0
        assert not (storage_root / ".env.apprc-storage").exists()


@pytest.mark.asyncio
async def test_editor_saving_to_app_creates_only_app_env_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    kit = build_storage_free_example_kit()
    editor = ConfigEditorApp(
        kit=kit,
        storage_registry=None,
    )

    async with editor.run_test() as pilot:
        await pilot.pause()
        app_wide_env = kit.spec.app_wide_env_path()

        assert not app_wide_env.exists()
        editor._save_env_key(
            "STORAGE_FREE_APP_PROFILE",
            "app-profile",
            scope="app",
        )

        assert app_wide_env.is_file()
        assert 'STORAGE_FREE_APP_PROFILE="app-profile"\n' in (
            app_wide_env.read_text(encoding="utf-8")
        )


@pytest.mark.asyncio
async def test_editor_saving_to_storage_creates_only_storage_env_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    kit = build_apprc_example_app_kit()
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    editor = ConfigEditorApp(
        kit=kit,
        storage_registry=None,
        active_storage_root=storage_root,
    )

    async with editor.run_test() as pilot:
        await pilot.pause()
        storage_env = storage_root / ".env.apprc-storage"
        app_wide_env = kit.spec.app_wide_env_path()

        assert not storage_env.exists()
        assert not app_wide_env.exists()
        editor._save_env_key(
            "APPRC_EXAMPLE_APP_PROFILE",
            "storage-profile",
            scope="storage",
        )

        assert storage_env.is_file()
        assert not app_wide_env.exists()
        assert 'APPRC_EXAMPLE_APP_PROFILE="storage-profile"\n' in (
            storage_env.read_text(encoding="utf-8")
        )
