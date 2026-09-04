from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Button, DataTable, Static
from typer.testing import CliRunner

from apprc.interfaces.tui.editor import ConfigEditorApp
from apprc.user_files.storage_roots.registry import register_storage
from tests.support_config import (
    build_apprc_example_app_kit,
    build_storage_free_example_kit,
)


def test_editor_uses_fixed_dotenv_and_registry_labels() -> None:
    kit = build_apprc_example_app_kit()
    editor = ConfigEditorApp(
        kit=kit,
        storage_registry=None,
        active_storage_root=Path("/tmp/storage"),
    )

    assert editor.kit.spec.storage_dotenv_filename == "apprc.storage.env"
    assert editor.apprc_toml_label == "apprc.toml"
    assert editor.init_command.endswith("config storage add NAME PATH")


@pytest.mark.asyncio
async def test_editor_hides_storage_controls_for_storage_free_app() -> None:
    editor = ConfigEditorApp(
        kit=build_storage_free_example_kit(),
        storage_registry=None,
    )

    async with editor.run_test() as pilot:
        await pilot.pause()

        assert list(editor.query("#storage-list")) == []
        for button_id in (
            "storage-new",
            "storage-rename",
            "storage-location",
            "storage-move",
        ):
            assert list(editor.query(f"#{button_id}")) == []
        assert editor.query_one("#field-table", DataTable).row_count > 0


@pytest.mark.asyncio
async def test_editor_exposes_every_user_registered_storage(
    tmp_path: Path,
) -> None:
    kit = build_apprc_example_app_kit()
    registry_path = kit.spec.preferred_apprc_toml_path()
    registry = register_storage(
        name="alpha",
        root=tmp_path / "alpha",
        path=registry_path,
    )
    registry = register_storage(
        name="beta",
        root=tmp_path / "beta",
        path=registry_path,
    )
    editor = ConfigEditorApp(
        kit=kit,
        storage_registry=registry,
        initial_storage="alpha",
        active_storage_root=tmp_path / "alpha",
    )

    async with editor.run_test() as pilot:
        await pilot.pause()

        assert editor.query_one("#storage-list").children.__len__() == 2
        assert editor.query_one("#storage-new", Button).disabled is False


@pytest.mark.asyncio
async def test_editor_saving_user_value_creates_only_user_dotenv() -> None:
    kit = build_storage_free_example_kit()
    editor = ConfigEditorApp(kit=kit, storage_registry=None)

    async with editor.run_test() as pilot:
        await pilot.pause()
        user_dotenv = kit.spec.user_dotenv_path()
        editor._save_env_key(
            "STORAGE_FREE_APP_PROFILE",
            "user-profile",
            scope="user",
        )

        assert user_dotenv.read_text(encoding="utf-8") == (
            'STORAGE_FREE_APP_PROFILE="user-profile"\n'
        )
        assert not kit.spec.preferred_apprc_toml_path().exists()


@pytest.mark.asyncio
async def test_editor_saving_storage_value_creates_only_storage_dotenv(
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
        editor._save_env_key(
            "APPRC_EXAMPLE_APP_PROFILE",
            "storage-profile",
            scope="storage",
        )

        assert (
            kit.spec.storage_dotenv_path(storage_root).read_text(
                encoding="utf-8"
            )
            == 'APPRC_EXAMPLE_APP_PROFILE="storage-profile"\n'
        )
        assert not kit.spec.user_dotenv_path().exists()


@pytest.mark.asyncio
async def test_editor_disables_storage_fields_until_marker_exists(
    tmp_path: Path,
) -> None:
    """A directory alone is not an initialized AppRC storage.

    :param tmp_path: Isolated uninitialized storage directory.
    """
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

        assert editor.query_one("#field-table", DataTable).disabled is True
        assert editor.query_one("#config-setup", Button).disabled is False
        assert "Missing AppRC marker" in str(
            editor.query_one("#scope-title", Static).content
        )


@pytest.mark.asyncio
async def test_editor_keeps_startup_failure_visible() -> None:
    """The recovery message remains visible beside the Setup button."""
    editor = ConfigEditorApp(
        kit=build_apprc_example_app_kit(),
        storage_registry=None,
        storage_registry_error="apprc.toml is malformed",
        storage_startup_error="Unknown storage 'broken'",
    )

    async with editor.run_test() as pilot:
        await pilot.pause()

        status = editor.query_one("#setup-status", Static)
        assert "Unknown storage 'broken'" in str(status.content)
        assert editor.query_one("#config-setup", Button).disabled is False


def test_config_edit_opens_when_storage_selector_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Editor startup converts selector failures into repairable state.

    :param monkeypatch: Process environment mutation fixture.
    :param tmp_path: Isolated AppRC directory.
    """
    kit = build_apprc_example_app_kit()
    monkeypatch.setenv(
        kit.spec.apprc_dir_env_key,
        str(tmp_path / "apprc"),
    )
    monkeypatch.setenv(
        kit.spec.require_storage_selector_env_key(),
        "unknown",
    )
    launched: list[bool] = []

    class HeadlessEditor(ConfigEditorApp):
        """Record editor launch without starting a terminal application."""

        def run(self, *args: object, **kwargs: object) -> None:
            """Record one launch attempt.

            :param args: Ignored Textual positional arguments.
            :param kwargs: Ignored Textual keyword arguments.
            :return: None.
            """
            launched.append(True)

    app = kit.typer_app(editor_app_cls=HeadlessEditor)

    result = CliRunner().invoke(app, ["edit"])

    assert result.exit_code == 0, result.output
    assert launched == [True]
