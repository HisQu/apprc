from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Button, DataTable

from apprc.runtime_config.tui.editor import ConfigEditorApp
from tests.support_config import build_apprc_example_app_kit


def test_editor_uses_new_storage_env_and_index_labels() -> None:
    kit = build_apprc_example_app_kit()
    editor = ConfigEditorApp(
        kit=kit,
        storage_registry=None,
        active_storage_root=Path("/tmp/storage"),
    )

    assert editor.current_env_filename == ".env.apprc-storage"
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
