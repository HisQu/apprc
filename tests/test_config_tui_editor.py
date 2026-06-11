from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from textual.coordinate import Coordinate
from textual.widgets import Button, DataTable, Input, ListView, Static

from tests.support_config import (
    APPRC_EXAMPLE_APP_OWNERS,
    build_apprc_example_app_kit,
    set_apprc_example_app_apprc_toml,
)

pytestmark = [pytest.mark.requires_apprc_env("APPRC_EXAMPLE_APP")]


def test_kit_builds_generic_editor_with_spec_defaults(
    monkeypatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    registry = kit.register_storage(
        name="alpha",
        root=tmp_path / "storage",
        make_default=True,
    )

    editor = kit.editor_app(registry=registry)

    assert editor.owners == APPRC_EXAMPLE_APP_OWNERS
    assert editor.local_env_filename == ".env.apprc_example_app"
    assert editor.init_command == (
        "apprc_example_app config init STORAGE_ROOT --name NAME"
    )
    assert editor.registry_label == "apprc_example_app.apprc.toml"


@pytest.mark.asyncio
async def test_editor_launches_with_empty_registry_and_new_storage_button(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    editor = kit.editor_app(registry=kit.load_registry())

    async with editor.run_test():
        title = editor.query_one("#storage-title", Static).content
        table = editor.query_one("#field-table", DataTable)
        new_button = editor.query_one("#storage-new", Button)
        default_button = editor.query_one("#storage-set-default", Button)

    assert "No storages registered" in str(title)
    assert table.disabled is True
    assert new_button.disabled is False
    assert default_button.disabled is True


@pytest.mark.asyncio
async def test_editor_launches_with_missing_default_storage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    storage_root = tmp_path / "alpha"
    registry = kit.register_storage(
        name="alpha",
        root=storage_root,
        make_default=True,
    )
    shutil.rmtree(storage_root)
    editor = kit.editor_app(registry=registry)

    async with editor.run_test():
        title = editor.query_one("#storage-title", Static).content
        table = editor.query_one("#field-table", DataTable)
        default_button = editor.query_one("#storage-set-default", Button)
        delete_button = editor.query_one("#storage-delete", Button)
        archive_button = editor.query_one("#storage-archive", Button)

    assert editor.current_storage_kind == "missing"
    assert "Missing storage root" in str(title)
    assert str(storage_root.resolve()) in str(title)
    assert table.disabled is True
    assert default_button.disabled is True
    assert delete_button.disabled is False
    assert archive_button.disabled is True
    assert not storage_root.exists()


@pytest.mark.asyncio
async def test_editor_registers_missing_storage_directory_from_modal_flow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    editor = kit.editor_app(registry=kit.load_registry())
    storage_root = tmp_path / "alpha"

    async with editor.run_test() as pilot:
        worker = editor.run_worker(
            editor.storage_workflows.register_storage_directory_flow(
                storage_root,
                default_name="alpha",
            )
        )
        await pilot.pause()
        editor.screen.query_one("#create", Button).press()
        await pilot.pause()
        editor.screen.query_one("#name-continue", Button).press()
        await worker.wait()

    registry = kit.load_registry()
    assert registry.default_storage == "alpha"
    assert registry.selected("alpha").root == storage_root.resolve()
    assert (storage_root / ".env.apprc_example_app").is_file()


@pytest.mark.asyncio
async def test_editor_unregisters_missing_non_default_storage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    beta_root = tmp_path / "beta"
    alpha_root = tmp_path / "alpha"
    kit.register_storage(name="beta", root=beta_root, make_default=True)
    registry = kit.register_storage(
        name="alpha",
        root=alpha_root,
        make_default=False,
    )
    shutil.rmtree(alpha_root)
    editor = kit.editor_app(registry=registry, initial_storage="alpha")

    async with editor.run_test() as pilot:
        worker = editor.run_worker(
            editor.storage_workflows.open_delete_storage_flow()
        )
        await pilot.pause()
        assert editor.current_storage_kind == "missing"
        assert list(editor.screen.query("#delete-content")) == []
        editor.screen.query_one("#unregister", Button).press()
        await pilot.pause()
        await worker.wait()

    registry = kit.load_registry()
    assert registry.default_storage == "beta"
    assert sorted(registry.storages) == ["beta"]
    assert registry.selected("beta").root == beta_root.resolve()
    assert not alpha_root.exists()


@pytest.mark.asyncio
async def test_editor_set_default_and_unregister_non_default_storage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    kit.register_storage(
        name="alpha", root=tmp_path / "alpha", make_default=True
    )
    registry = kit.register_storage(
        name="beta",
        root=tmp_path / "beta",
        make_default=False,
    )
    editor = kit.editor_app(registry=registry)

    async with editor.run_test():
        editor._select_storage("beta")
        await editor.storage_workflows.set_current_as_default()
        editor._select_storage("alpha")
        removed = await editor.storage_workflows.remove_live_storage(
            "alpha",
            delete_content=False,
        )

    registry = kit.load_registry()
    assert removed is True
    assert registry.default_storage == "beta"
    assert sorted(registry.storages) == ["beta"]
    assert (tmp_path / "alpha").is_dir()


@pytest.mark.asyncio
async def test_editor_default_replacement_skips_missing_storages(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    alpha_root = tmp_path / "alpha"
    beta_root = tmp_path / "beta"
    gamma_root = tmp_path / "gamma"
    kit.register_storage(name="alpha", root=alpha_root, make_default=True)
    kit.register_storage(name="beta", root=beta_root, make_default=False)
    registry = kit.register_storage(
        name="gamma",
        root=gamma_root,
        make_default=False,
    )
    shutil.rmtree(beta_root)
    editor = kit.editor_app(registry=registry)

    async with editor.run_test() as pilot:
        worker = editor.run_worker(
            editor.storage_workflows.remove_live_storage(
                "alpha",
                delete_content=False,
            )
        )
        await pilot.pause()
        assert list(editor.screen.query("#default-beta")) == []
        editor.screen.query_one("#default-gamma", Button).press()
        await pilot.pause()
        removed = await worker.wait()

    registry = kit.load_registry()
    assert removed is True
    assert registry.default_storage == "gamma"
    assert sorted(registry.storages) == ["beta", "gamma"]
    assert registry.selected("gamma").root == gamma_root.resolve()


@pytest.mark.asyncio
async def test_editor_recreates_last_default_with_host_storage_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    kit = build_apprc_example_app_kit()
    registry = kit.register_storage(
        name="alpha",
        root=tmp_path / "alpha",
        make_default=True,
    )
    editor = kit.editor_app(registry=registry)

    async with editor.run_test() as pilot:
        worker = editor.run_worker(
            editor.storage_workflows.remove_live_storage(
                "alpha",
                delete_content=False,
            )
        )
        await pilot.pause()
        message = editor.screen.query_one(
            "#default-path-message", Static
        ).content
        assert "Example App" in str(message)
        assert "AppRC" not in str(message)
        editor.screen.query_one("#default-create", Button).press()
        await pilot.pause()
        removed = await worker.wait()

    new_storage_root = (
        tmp_path / "data" / "apprc_example_app" / "apprc_example_app_stor-1"
    )
    registry = kit.load_registry()
    assert removed is True
    assert registry.default_storage == "apprc_example_app_stor-1"
    assert sorted(registry.storages) == ["apprc_example_app_stor-1"]
    assert registry.selected("apprc_example_app_stor-1").root == (
        new_storage_root.resolve()
    )


@pytest.mark.asyncio
async def test_editor_shows_and_prunes_stale_archived_rows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    registry = kit.record_archived_storage(
        name="alpha",
        archive=tmp_path / "alpha.apprc.tar.xz",
        source_root=tmp_path / "alpha",
    )
    editor = kit.editor_app(registry=registry)

    async with editor.run_test():
        storage_list = editor.query_one("#storage-list", ListView)
        assert storage_list.index == 0
        assert editor.current_storage_kind == "archived"
        await editor.storage_workflows.restore_or_prune_archived_storage(
            "alpha"
        )

    assert kit.load_registry().archived_storages == {}


@pytest.mark.allow_missing_apprc_env
@pytest.mark.asyncio
async def test_editor_table_shows_storage_root_and_formats_rows(
    monkeypatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    monkeypatch.delenv("APPRC_EXAMPLE_APP_STORAGE", raising=False)
    monkeypatch.setenv("APPRC_EXAMPLE_APP_MODE", "MANUAL")
    kit = build_apprc_example_app_kit()
    registry = kit.register_storage(
        name="alpha",
        root=tmp_path / "storage",
        make_default=True,
    )
    local_env = tmp_path / "storage" / ".env.apprc_example_app"
    local_env.write_text(
        f'APPRC_EXAMPLE_APP_STORAGE="{(tmp_path / "storage").resolve()}"\n'
        'APPRC_EXAMPLE_APP_ACCESS_TOKEN="super-secret"\n'
        'APPRC_EXAMPLE_APP_PROFILE="local-profile"\n'
        'APPRC_EXAMPLE_APP_RETRY_COUNT="7"\n',
        encoding="utf-8",
    )
    editor = kit.editor_app(registry=registry)

    async with editor.run_test():
        table = editor.query_one("#field-table", DataTable)
        rows = [table.get_row_at(i) for i in range(table.row_count)]

    column_labels = [column.label.plain for column in table.columns.values()]
    row_text = [[str(cell) for cell in row] for row in rows]
    rows_by_key = {row[2]: row for row in row_text}
    rich_rows_by_key = {str(row[2]): row for row in rows}

    assert column_labels == [
        "#",
        "Section",
        "Key",
        "Status",
        "Local",
        "Default",
        "Explanation",
    ]
    assert rows_by_key["APPRC_EXAMPLE_APP_STORAGE"][3] == "unset"
    assert rows_by_key["APPRC_EXAMPLE_APP_STORAGE"][4] == str(
        (tmp_path / "storage").resolve()
    )
    assert rows_by_key["APPRC_EXAMPLE_APP_PROFILE"][:6] == [
        "2",
        "App",
        "APPRC_EXAMPLE_APP_PROFILE",
        "unset",
        "local-profile",
        "default",
    ]
    assert rich_rows_by_key["APPRC_EXAMPLE_APP_PROFILE"][4].style == "white"
    assert rich_rows_by_key["APPRC_EXAMPLE_APP_PROFILE"][5].style == "white"
    assert rows_by_key["APPRC_EXAMPLE_APP_ACCESS_TOKEN"][4] == "<secret>"
    assert rich_rows_by_key["APPRC_EXAMPLE_APP_ACCESS_TOKEN"][4].style == (
        "dim italic"
    )
    assert rows_by_key["APPRC_EXAMPLE_APP_ACCESS_TOKEN"][5] == ""
    assert rows_by_key["APPRC_EXAMPLE_APP_MODE"][3] == "shell"
    assert rich_rows_by_key["APPRC_EXAMPLE_APP_MODE"][5].style == "bold cyan"
    assert (
        rich_rows_by_key["APPRC_EXAMPLE_APP_ENABLED"][5].style == "bold magenta"
    )
    assert (
        rich_rows_by_key["APPRC_EXAMPLE_APP_RETRY_COUNT"][4].style == "yellow"
    )
    assert (
        rich_rows_by_key["APPRC_EXAMPLE_APP_RETRY_COUNT"][5].style == "yellow"
    )
    assert rich_rows_by_key["APPRC_EXAMPLE_APP_CACHE_DIR"][5].style == "green"
    assert rich_rows_by_key["APPRC_EXAMPLE_APP_STORAGE"][6].style == "dim"


@pytest.mark.asyncio
async def test_editor_table_required_missing_keeps_red_fill(
    monkeypatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    registry = kit.register_storage(
        name="alpha",
        root=tmp_path / "storage",
        make_default=True,
    )
    editor = kit.editor_app(registry=registry)

    async with editor.run_test():
        table = editor.query_one("#field-table", DataTable)
        rows = [table.get_row_at(i) for i in range(table.row_count)]
    rows_by_key = {str(row[2]): row for row in rows}

    assert str(rows_by_key["APPRC_EXAMPLE_APP_ACCESS_TOKEN"][5]) == "<required>"
    assert rows_by_key["APPRC_EXAMPLE_APP_ACCESS_TOKEN"][5].style == (
        "bold white on red"
    )


@pytest.mark.asyncio
async def test_editor_modal_saves_local_value(
    monkeypatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    storage_root = tmp_path / "storage"
    registry = kit.register_storage(
        name="alpha",
        root=storage_root,
        make_default=True,
    )
    editor = kit.editor_app(registry=registry)

    async with editor.run_test() as pilot:
        table = editor.query_one("#field-table", DataTable)
        table.cursor_coordinate = Coordinate(1, 0)
        editor._open_selected_field_editor()
        await pilot.pause()
        input_widget = editor.screen.query_one("#edit-value-input", Input)
        input_widget.value = "other-profile"
        editor.screen.query_one("#edit-save", Button).press()
        await pilot.pause()

    assert 'APPRC_EXAMPLE_APP_PROFILE="other-profile"\n' in (
        storage_root / ".env.apprc_example_app"
    ).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_editor_modal_shows_type_choices_and_long_explanation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    registry = kit.register_storage(
        name="alpha",
        root=tmp_path / "storage",
        make_default=True,
    )
    editor = kit.editor_app(registry=registry)

    async with editor.run_test() as pilot:
        table = editor.query_one("#field-table", DataTable)
        table.cursor_coordinate = Coordinate(2, 0)
        editor._open_selected_field_editor()
        await pilot.pause()
        metadata = editor.screen.query_one("#edit-metadata", Static).content
        long_explanation = editor.screen.query_one(
            "#edit-long-explanation",
            Static,
        ).content

    assert "Type: str" in str(metadata)
    assert "Possible values: AUTO, MANUAL" in str(metadata)
    assert "Operating mode used by Example App commands." in str(
        long_explanation
    )
