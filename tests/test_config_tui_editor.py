from __future__ import annotations

from pathlib import Path

import pytest
from textual.coordinate import Coordinate
from textual.pilot import Pilot
from textual.widgets import Button, DataTable, Input, ListView, Static

import apprc as rc
from apprc.definition.resolution import ResolveOptions
from apprc.interfaces.tui._primitives import (
    PathInputResult,
    WorkspaceNameResult,
)
from apprc.interfaces.tui.editor import ConfigEditorApp
from apprc.interfaces.tui.modals.screens import ArchiveOptionsResult
from apprc.user_files.app_home.application import AppFiles
from apprc.user_files.env_files import (
    ensure_workspace_dotenv_file,
    read_env_file,
)
from apprc.user_files.workspace_roots.model import WorkspaceRegistry
from tests.support_config import (
    build_config_only_example_app,
    build_workspace_example_app,
)
from tests.support_tui import open_field_editor, static_text


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
async def test_field_table_keeps_explicit_columns_and_edit_keys_aligned(
    tmp_path: Path,
) -> None:
    kit = build_workspace_example_app()

    @kit.config("second", title="Second", prefix="SECOND_", rc_path=("second",))
    class SecondSection(rc.Config):
        value: str = rc.field("SECOND_VALUE", default="second-default")

    explicit = tmp_path / "explicit.env"
    explicit.write_text(
        'APPRC_EXAMPLE_APP_PROFILE="explicit-profile"\n',
        encoding="utf-8",
    )
    options = ResolveOptions(
        layout=rc.Layout.single_root(tmp_path / "application"),
        env_files=(explicit,),
    )
    paths = kit.paths(options, environment={})
    manager = kit._manage_with_paths(options, {}, paths)
    manager.setup()
    workspace_manager = kit.workspaces(options=options, environment={})
    editor = ConfigEditorApp(
        apprc=kit,
        manager=manager,
        workspace_manager=workspace_manager,
    )
    screen = editor.editor_screen

    async with editor.run_test() as pilot:
        await pilot.pause()
        table = screen.query_one("#field-table", DataTable)
        columns = tuple(str(column.label) for column in table.columns.values())
        assert "Workspace dotenv" in columns
        assert "Explicit dotenv" in columns
        assert "APPRC_EXAMPLE_APP_WORKSPACE" not in screen.row_env_keys
        profile_row = screen.row_env_keys.index("APPRC_EXAMPLE_APP_PROFILE")
        profile_cells = table.get_row_at(profile_row)
        assert str(profile_cells[columns.index("Explicit dotenv")]) == (
            "explicit-profile"
        )

        separator_row = screen.row_env_keys.index(None)
        table.cursor_coordinate = Coordinate(separator_row, 0)
        original_screen = editor.screen
        screen._open_selected_field_editor()
        await pilot.pause()
        assert editor.screen is original_screen

        await open_field_editor(editor, "SECOND_VALUE", pilot)
        assert (
            static_text(editor.screen.query_one("#edit-env-key", Static)).plain
            == "SECOND_VALUE"
        )
        editor.screen.query_one(
            "#edit-value-input", Input
        ).value = "second-edited"
        await pilot.click("#edit-save-user")
        await pilot.pause()
        assert screen.row_env_keys.index("SECOND_VALUE") > separator_row
        second_row = screen.row_env_keys.index("SECOND_VALUE")
        second_cells = table.get_row_at(second_row)
        assert str(second_cells[columns.index("Effective")]) == "second-edited"
        assert (
            screen._inspected_resolution().values["SECOND_VALUE"]
            == "second-edited"
        )
        profile_row = screen.row_env_keys.index("APPRC_EXAMPLE_APP_PROFILE")
        assert (
            str(table.get_row_at(profile_row)[columns.index("Explicit dotenv")])
            == "explicit-profile"
        )

    files = AppFiles(kit.schema, paths)
    assert read_env_file(files.user_dotenv_path())["SECOND_VALUE"] == (
        "second-edited"
    )
    assert explicit.read_text(encoding="utf-8") == (
        'APPRC_EXAMPLE_APP_PROFILE="explicit-profile"\n'
    )


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
async def test_workspace_action_context_tracks_sequential_operations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kit = build_workspace_example_app()
    options = _single_root(tmp_path)
    paths = kit.paths(options, environment={})
    manager = kit._manage_with_paths(options, {}, paths)
    manager.setup()
    workspace_manager = kit.workspaces(options=options, environment={})
    workspace_manager.register_workspace("alpha", tmp_path / "alpha")
    editor = ConfigEditorApp(
        apprc=kit,
        manager=manager,
        workspace_manager=workspace_manager,
        initial_workspace="alpha",
    )
    screen = editor.editor_screen
    reconnected_root = tmp_path / "reconnected"
    reconnected_root.mkdir()
    ensure_workspace_dotenv_file(
        reconnected_root, filename=kit.schema.workspace_dotenv_filename
    )
    moved_root = tmp_path / "moved"
    archive_path = tmp_path / "renamed.apprc.tar.xz"
    restored_root = tmp_path / "restored"
    responses: list[object] = [
        None,
        WorkspaceNameResult(name="renamed"),
        "rename",
        PathInputResult(path=reconnected_root),
        "update",
        PathInputResult(path=moved_root),
        "move",
        ArchiveOptionsResult(archive_path=archive_path),
        "remove",
        WorkspaceNameResult(name="renamed"),
        PathInputResult(path=restored_root),
        "remove",
    ]

    async def respond(_dialog: object) -> object:
        return responses.pop(0)

    async def click_action(pilot: Pilot[None], selector: str) -> None:
        await pilot.click(selector)
        await editor.workers.wait_for_complete(tuple(editor.workers))
        await pilot.pause()

    monkeypatch.setattr(editor, "push_screen_wait", respond)
    async with editor.run_test() as pilot:
        await pilot.pause()
        await click_action(pilot, "#workspace-rename")
        assert (
            "alpha"
            in static_text(screen.query_one("#scope-title", Static)).plain
        )
        assert not screen.query_one("#workspace-rename", Button).disabled

        await click_action(pilot, "#workspace-rename")
        assert (
            "renamed"
            in static_text(screen.query_one("#scope-title", Static)).plain
        )
        await click_action(pilot, "#workspace-location")
        assert (
            str(reconnected_root)
            in static_text(screen.query_one("#scope-title", Static)).plain
        )
        await click_action(pilot, "#workspace-move")
        assert (
            str(moved_root)
            in static_text(screen.query_one("#scope-title", Static)).plain
        )
        await click_action(pilot, "#workspace-archive")
        assert archive_path.is_file()

        await click_action(pilot, "#workspace-delete")
        assert (
            str(archive_path)
            in static_text(screen.query_one("#scope-title", Static)).plain
        )
        workspace_list = screen.query_one("#workspace-list", ListView)
        await pilot.click(workspace_list.children[0])
        await editor.workers.wait_for_complete(tuple(editor.workers))
        await pilot.pause()
        assert (
            str(restored_root)
            in static_text(screen.query_one("#scope-title", Static)).plain
        )

        await click_action(pilot, "#workspace-delete")
        assert screen.query_one("#workspace-rename", Button).disabled
        assert not screen.query_one("#field-table", DataTable).disabled
        await screen._save_env_key(
            "APPRC_EXAMPLE_APP_PROFILE",
            "user-after-removal",
            scope="user",
        )

    files = AppFiles(kit.schema, paths)
    assert files.workspace_dotenv_path(restored_root).is_file()
    assert (
        read_env_file(files.user_dotenv_path())["APPRC_EXAMPLE_APP_PROFILE"]
        == "user-after-removal"
    )
    assert "renamed" not in workspace_manager.registry().workspaces


@pytest.mark.asyncio
async def test_registry_read_failure_after_rename_keeps_editor_usable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kit = build_workspace_example_app()
    options = _single_root(tmp_path)
    paths = kit.paths(options, environment={})
    manager = kit._manage_with_paths(options, {}, paths)
    manager.setup()
    workspace_manager = kit.workspaces(options=options, environment={})
    workspace_manager.register_workspace("alpha", tmp_path / "alpha")
    editor = ConfigEditorApp(
        apprc=kit,
        manager=manager,
        workspace_manager=workspace_manager,
        initial_workspace="alpha",
    )
    screen = editor.editor_screen
    read_registry = workspace_manager.registry
    rename_finished = False
    responses: list[object] = [
        WorkspaceNameResult(name="renamed"),
        "rename",
    ]

    async def respond(_dialog: object) -> object:
        return responses.pop(0)

    rename_workspace = workspace_manager.rename_workspace

    def rename_then_fail_registry(
        *,
        old: str,
        new: str,
    ) -> WorkspaceRegistry:
        nonlocal rename_finished
        registry = rename_workspace(old=old, new=new)
        rename_finished = True
        return registry

    def fail_registry() -> WorkspaceRegistry:
        if rename_finished:
            raise OSError("injected registry read failure")
        return read_registry()

    monkeypatch.setattr(editor, "push_screen_wait", respond)
    monkeypatch.setattr(
        workspace_manager,
        "rename_workspace",
        rename_then_fail_registry,
    )
    monkeypatch.setattr(workspace_manager, "registry", fail_registry)

    async with editor.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#workspace-rename")
        await editor.workers.wait_for_complete(tuple(editor.workers))
        await pilot.pause()

        persisted = read_registry()
        assert "renamed" in persisted.workspaces
        assert "alpha" not in persisted.workspaces
        assert screen.query_one("#workspace-new", Button).disabled
        assert screen.query_one("#workspace-rename", Button).disabled
        assert not screen.query_one("#field-table", DataTable).disabled
        await screen._save_env_key(
            "APPRC_EXAMPLE_APP_PROFILE",
            "user-after-registry-failure",
            scope="user",
        )

    files = AppFiles(kit.schema, paths)
    assert (
        read_env_file(files.user_dotenv_path())["APPRC_EXAMPLE_APP_PROFILE"]
        == "user-after-registry-failure"
    )


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
