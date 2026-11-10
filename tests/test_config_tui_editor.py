from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Button, Static

import apprc as rc
from apprc.definition.resolution import ResolveOptions
from apprc.interfaces.tui._primitives import WorkspaceNameResult
from apprc.interfaces.tui.editor import ConfigEditorApp
from apprc.user_files.app_home.application import AppFiles
from tests.support_config import (
    build_config_only_example_app,
    build_workspace_example_app,
)
from tests.support_tui import static_text


def _single_root(root: Path) -> ResolveOptions:
    return ResolveOptions(layout=rc.Layout.single_root(root))


def _workspace_editor(kit: rc.AppRC, root: Path) -> ConfigEditorApp:
    options = _single_root(root)
    paths = kit.paths(options, environment={})
    return ConfigEditorApp(
        apprc=kit,
        manager=kit._manage_with_paths(options, {}, paths),
        workspace_manager=kit.workspaces(options=options, environment={}),
    )


@pytest.mark.asyncio
async def test_config_only_editor_saves_user_setting_without_workspace_service(
    tmp_path: Path,
) -> None:
    kit = build_config_only_example_app()
    options = _single_root(tmp_path)
    manager = kit.manage(options=options, environment={})
    manager.setup()
    editor = ConfigEditorApp(apprc=kit, manager=manager)
    screen = editor.editor_screen

    async with editor.run_test() as pilot:
        await pilot.pause()
        await screen._save_env_key(
            "CONFIG_ONLY_APP_PROFILE", "edited", scope="user"
        )
        assert (
            screen._inspected_resolution().values["CONFIG_ONLY_APP_PROFILE"]
            == "edited"
        )

    files = AppFiles(kit.schema, manager.paths)
    assert files.user_dotenv_path().read_text(encoding="utf-8") == (
        'CONFIG_ONLY_APP_PROFILE="edited"\n'
    )
    assert not files.config_file().exists()


@pytest.mark.asyncio
async def test_registry_editor_selects_and_renames_workspace_through_action_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kit = build_workspace_example_app()
    options = _single_root(tmp_path)
    paths = kit.paths(options, environment={})
    manager = kit._manage_with_paths(options, {}, paths)
    workspace_manager = kit.workspaces(options=options, environment={})
    workspace_manager.register_workspace("alpha", tmp_path / "alpha")
    workspace_manager.register_workspace("beta", tmp_path / "beta")
    editor = ConfigEditorApp(
        apprc=kit,
        manager=manager,
        workspace_manager=workspace_manager,
        initial_workspace="alpha",
    )
    screen = editor.editor_screen
    responses: list[object] = [
        WorkspaceNameResult(name="renamed"),
        "rename",
    ]

    async def respond(_dialog: object) -> object:
        return responses.pop(0)

    monkeypatch.setattr(editor, "push_screen_wait", respond)
    async with editor.run_test() as pilot:
        await pilot.pause()
        assert not screen.query_one("#workspace-rename", Button).disabled
        assert (
            "alpha"
            in static_text(screen.query_one("#scope-title", Static)).plain
        )
        await screen._save_env_key(
            "APPRC_EXAMPLE_APP_PROFILE", "workspace-value", scope="workspace"
        )
        await pilot.click("#workspace-rename")
        await editor.workers.wait_for_complete(tuple(editor.workers))
        await pilot.pause()
        assert (
            "renamed"
            in static_text(screen.query_one("#scope-title", Static)).plain
        )
        assert not screen.query_one("#workspace-rename", Button).disabled

    files = AppFiles(kit.schema, paths)
    assert (
        files.workspace_dotenv_path(tmp_path / "alpha").read_text(
            encoding="utf-8"
        )
        == 'APPRC_EXAMPLE_APP_PROFILE="workspace-value"\n'
    )
    assert not files.user_dotenv_path().exists()


@pytest.mark.asyncio
async def test_workspace_actions_require_manager_and_unregister_keeps_payload(
    tmp_path: Path,
) -> None:
    kit = build_workspace_example_app()
    options = _single_root(tmp_path)
    manager = kit.manage(options=options, environment={})
    with pytest.raises(ValueError, match="Workspace controls require"):
        ConfigEditorApp(apprc=kit, manager=manager)

    editor = _workspace_editor(kit, tmp_path)
    screen = editor.editor_screen
    assert screen.workspace_manager is not None
    payload_root = tmp_path / "retained"
    screen.workspace_manager.register_workspace("retained", payload_root)
    payload = payload_root / "payload.txt"
    payload.write_text("keep", encoding="utf-8")
    screen.workspace_manager.remove_workspace("retained")
    assert payload.read_text(encoding="utf-8") == "keep"


@pytest.mark.asyncio
async def test_editor_keeps_captured_paths_after_process_environment_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kit = build_config_only_example_app()
    first_root = tmp_path / "first"
    environment = {
        "CONFIG_ONLY_APP_LAYOUT": "single-root",
        "CONFIG_ONLY_APP_ROOT": str(first_root),
    }
    manager = kit.manage(environment=environment)
    manager.setup()
    editor = ConfigEditorApp(apprc=kit, manager=manager)
    screen = editor.editor_screen
    captured = screen.paths

    async with editor.run_test() as pilot:
        await pilot.pause()
        monkeypatch.setenv("CONFIG_ONLY_APP_LAYOUT", "native")
        monkeypatch.setenv("CONFIG_ONLY_APP_ROOT", str(tmp_path / "second"))
        assert screen.paths is captured
        assert screen.manager.paths is captured
        assert screen._inspected_resolution().paths is captured

    assert AppFiles(kit.schema, captured).user_dotenv_path().is_file()
    assert not (tmp_path / "second").exists()
