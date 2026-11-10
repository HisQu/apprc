from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Static

import apprc as rc
from apprc.definition.resolution import ResolveOptions
from apprc.interfaces.tui._primitives import (
    ConfirmScreen,
    PathInputResult,
    PathInputScreen,
)
from apprc.interfaces.tui.editor import ConfigEditorApp
from apprc.user_files.app_home.application import AppFiles

from tests.support_config import (
    WorkspaceExampleEnv,
    build_config_only_example_app,
)
from tests.support_tui import static_text


@pytest.mark.asyncio
async def test_config_only_editor_setup_initializes_only_user_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kit = build_config_only_example_app()
    options = ResolveOptions(layout=rc.Layout.single_root(tmp_path))
    manager = kit.manage(options=options, environment={})
    editor = ConfigEditorApp(apprc=kit, manager=manager)
    screen = editor.editor_screen
    shown: list[object] = []

    async def respond(screen: object) -> object:
        shown.append(screen)
        return "done"

    monkeypatch.setattr(editor, "push_screen_wait", respond)
    async with editor.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#config-setup")
        await editor.workers.wait_for_complete(tuple(editor.workers))
        await pilot.pause()
        assert len(screen.query("#config-setup")) == 0

    files = AppFiles(kit.schema, manager.paths)
    assert files.user_dotenv_path().is_file()
    assert files.config_file().parent.is_dir()
    assert not files.config_file().exists()
    assert len(shown) == 1 and isinstance(shown[0], ConfirmScreen)


def _direct_workspace_app() -> rc.AppRC:
    app = rc.AppRC(
        app_id="direct-workspace-test",
        paths=rc.Paths(config=True),
        user_dotenv=rc.UserDotenv(),
        workspaces=rc.Workspaces(registry=False),
    )
    app.config("app", prefix="APPRC_EXAMPLE_APP_")(WorkspaceExampleEnv)
    return app


@pytest.mark.asyncio
async def test_direct_workspace_setup_accepts_relative_path_without_registry_or_name_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    kit = _direct_workspace_app()
    options = ResolveOptions(
        layout=rc.Layout.single_root(tmp_path / "app-config")
    )
    paths = kit.paths(options, environment={})
    manager = kit._manage_with_paths(options, {}, paths)
    workspace_manager = kit.workspaces(options=options, environment={})
    editor = ConfigEditorApp(
        apprc=kit,
        manager=manager,
        workspace_manager=workspace_manager,
        active_workspace_root=None,
    )
    screen = editor.editor_screen
    monkeypatch.setattr(
        workspace_manager,
        "registry",
        lambda: pytest.fail("direct-only setup must not read a registry"),
    )
    shown: list[object] = []
    responses: list[object] = [
        PathInputResult(path=Path("./relative-workspace")),
        "done",
    ]

    async def respond(screen: object) -> object:
        shown.append(screen)
        return responses.pop(0)

    monkeypatch.setattr(editor, "push_screen_wait", respond)
    root = tmp_path / "relative-workspace"
    async with editor.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#config-setup")
        await editor.workers.wait_for_complete(tuple(editor.workers))
        await pilot.pause()
        assert (
            str(root)
            in static_text(screen.query_one("#scope-title", Static)).plain
        )

    assert AppFiles(kit.schema, paths).workspace_dotenv_path(root).is_file()
    assert AppFiles(kit.schema, paths).user_dotenv_path().is_file()
    assert not AppFiles(kit.schema, paths).config_file().exists()
    assert len(shown) == 2
    assert isinstance(shown[0], PathInputScreen)
    assert all(not isinstance(screen, PathInputScreen) for screen in shown[1:])
    assert not any(
        "register" in type(screen).__name__.lower() for screen in shown
    )
