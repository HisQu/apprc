from __future__ import annotations

from pathlib import Path

import pytest

import apprc as rc
from apprc.definition.resolution import ResolveOptions
from apprc.interfaces.tui.editor import ConfigEditorApp
from apprc.user_files.app_home.application import AppFiles
from tests.support_config import (
    build_config_only_example_app,
    build_workspace_example_app,
)


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

    async with editor.run_test() as pilot:
        await pilot.pause()
        await editor._save_env_key(
            "CONFIG_ONLY_APP_PROFILE", "edited", scope="user"
        )
        assert (
            editor._inspected_resolution().values["CONFIG_ONLY_APP_PROFILE"]
            == "edited"
        )

    files = AppFiles(kit.schema, manager.paths)
    assert files.user_dotenv_path().read_text(encoding="utf-8") == (
        'CONFIG_ONLY_APP_PROFILE="edited"\n'
    )
    assert not files.config_file().exists()


@pytest.mark.asyncio
async def test_registry_editor_selects_workspace_and_saves_workspace_overlay(
    tmp_path: Path,
) -> None:
    kit = build_workspace_example_app()
    editor = _workspace_editor(kit, tmp_path)
    assert editor.workspace_manager is not None
    editor.workspace_manager.register_workspace("alpha", tmp_path / "alpha")
    editor.workspace_manager.register_workspace("beta", tmp_path / "beta")
    editor.workspace_registry = editor.workspace_manager.registry()

    async with editor.run_test() as pilot:
        await pilot.pause()
        await editor._refresh_workspace_list(select_name="alpha")
        await editor._save_env_key(
            "APPRC_EXAMPLE_APP_PROFILE", "workspace-value", scope="workspace"
        )
        assert len(editor.query_one("#workspace-list").children) == 2
        assert editor._selected_workspace_name() == "alpha"

    files = AppFiles(kit.schema, editor.paths)
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
    assert editor.workspace_manager is not None
    payload_root = tmp_path / "retained"
    editor.workspace_manager.register_workspace("retained", payload_root)
    payload = payload_root / "payload.txt"
    payload.write_text("keep", encoding="utf-8")
    editor.workspace_manager.remove_workspace("retained")
    assert payload.read_text(encoding="utf-8") == "keep"


@pytest.mark.asyncio
async def test_settings_refresh_keeps_captured_paths(
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
    captured = editor.paths

    async with editor.run_test() as pilot:
        await pilot.pause()
        monkeypatch.setenv("CONFIG_ONLY_APP_LAYOUT", "native")
        monkeypatch.setenv("CONFIG_ONLY_APP_ROOT", str(tmp_path / "second"))
        await editor._refresh_workspace_list()
        assert editor.paths is captured
        assert editor.manager.paths is captured
        assert editor._inspected_resolution().paths is captured

    assert AppFiles(kit.schema, captured).user_dotenv_path().is_file()
    assert not (tmp_path / "second").exists()
