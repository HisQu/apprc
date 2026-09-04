from __future__ import annotations

from pathlib import Path

import pytest
from rich.text import Text

from apprc.interfaces.tui._primitives import (
    ConfirmScreen,
    PathInputResult,
    PathInputScreen,
)
from apprc.interfaces.tui.editor import ConfigEditorApp
from apprc.user_files.setup.text import setup_overview_text
from apprc.user_files.storage_roots.registry import (
    load_storage_registry_or_empty,
)
from tests.support_config import (
    build_apprc_example_app_kit,
    build_storage_free_example_kit,
)


def test_setup_overview_describes_fixed_storage_files() -> None:
    text = setup_overview_text(build_apprc_example_app_kit())

    assert "apprc.user.env" in text
    assert "storage named default" in text
    assert "apprc.toml" in text


def test_setup_overview_describes_storage_free_user_dotenv() -> None:
    text = setup_overview_text(build_storage_free_example_kit())

    assert "empty apprc.user.env" in text
    assert "registers" not in text


@pytest.mark.asyncio
async def test_editor_setup_registers_default_storage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    apprc_dir = tmp_path / "relocated-apprc"
    monkeypatch.setenv("APPRC_EXAMPLE_APP_APPRC_DIR", str(apprc_dir))
    kit = build_apprc_example_app_kit()
    storage_root = tmp_path / "storage"
    editor = ConfigEditorApp(kit=kit, storage_registry=None)
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

    registry = load_storage_registry_or_empty(
        kit.spec.preferred_apprc_toml_path()
    )
    assert registry.selected_storage == "default"
    assert registry.selected("default").root == storage_root.resolve()
    assert kit.spec.user_dotenv_path().is_file()
    assert kit.spec.storage_dotenv_path(storage_root).is_file()
    path_prompt = screens[0]
    assert isinstance(path_prompt, PathInputScreen)
    assert path_prompt.value == str(apprc_dir / "storage")
    summary = screens[-1]
    assert isinstance(summary, ConfirmScreen)
    assert isinstance(summary.message, Text)
    assert "user_dotenv:" in summary.message.plain


@pytest.mark.asyncio
async def test_storage_free_editor_setup_creates_user_dotenv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kit = build_storage_free_example_kit()
    editor = ConfigEditorApp(kit=kit, storage_registry=None)

    async def push_screen_wait(_: object) -> object | None:
        return "done"

    monkeypatch.setattr(editor, "push_screen_wait", push_screen_wait)

    async with editor.run_test() as pilot:
        await pilot.pause()
        await editor.setup_workflow.open_setup_flow()

    assert kit.spec.user_dotenv_path().read_text(encoding="utf-8") == ""
    assert not kit.spec.preferred_apprc_toml_path().exists()
