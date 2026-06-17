from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Button, DataTable, Input, ListView, Static

from apprc.config.storage_registry_loading import load_existing_storage_registry
from apprc.config.tui import ConfigEditorApp
from apprc.config.tui.modals import ArchiveOptionsScreen
from apprc.config.tui.storage.selection import (
    ActivePathStorageSelection,
    ArchivedStorageSelection,
    MissingStorageSelection,
)
from apprc.config.tui.styles import (
    CHOICE_STYLE,
    EFFECTIVE_SOURCE_STYLE,
    GENERIC_VALUE_STYLE,
    LABEL_STYLE,
    NUMBER_STYLE,
    PATH_INPUT_CLASS,
    PATH_STYLE,
    REQUIRED_STYLE,
    SECRET_STYLE,
    TEXT_STYLE,
)
from tests.support_config import (
    APPRC_EXAMPLE_APP_OWNERS,
    build_apprc_example_app_kit,
    create_empty_apprc_example_app_apprc_toml,
    record_archived_storage_for_kit,
    register_storage_for_kit,
    set_apprc_example_app_apprc_toml,
)
from tests.support_tui import (
    open_field_editor,
    region_bottom,
    region_right,
    static_text,
    text_has_span,
)

pytestmark = [pytest.mark.requires_apprc_env("APPRC_EXAMPLE_APP")]


def test_kit_builds_generic_editor_with_spec_defaults(
    monkeypatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    registry = register_storage_for_kit(
        kit,
        name="alpha",
        root=tmp_path / "storage",
    )

    editor = ConfigEditorApp(kit=kit, storage_registry=registry)

    assert editor.owners == APPRC_EXAMPLE_APP_OWNERS
    assert editor.local_env_filename == ".env.apprc_example_app"
    assert editor.init_command == (
        "apprc_example_app config init STORAGE_ROOT --name NAME"
    )
    assert editor.apprc_toml_label == "apprc_example_app.apprc.toml"


@pytest.mark.asyncio
async def test_editor_launches_with_empty_apprc_toml_and_new_storage_button(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    create_empty_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    editor = ConfigEditorApp(
        kit=kit, storage_registry=load_existing_storage_registry(kit.spec)
    )

    async with editor.run_test():
        title = editor.query_one("#storage-title", Static).content
        table = editor.query_one("#field-table", DataTable)
        new_button = editor.query_one("#storage-new", Button)
        register_button = editor.query_one(
            "#storage-register-active",
            Button,
        )

    assert "No storages registered" in str(title)
    assert table.disabled is True
    assert new_button.disabled is False
    assert register_button.disabled is True


@pytest.mark.asyncio
async def test_editor_launches_with_active_path_without_apprc_toml(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("APPRC_EXAMPLE_APP_APPRC_TOML", raising=False)
    kit = build_apprc_example_app_kit()
    storage_root = tmp_path / "active"
    storage_root.mkdir()
    editor = ConfigEditorApp(
        kit=kit,
        storage_registry=None,
        active_storage_root=storage_root,
    )

    async with editor.run_test():
        title = editor.query_one("#storage-title", Static).content
        table = editor.query_one("#field-table", DataTable)
        register_button = editor.query_one(
            "#storage-register-active",
            Button,
        )
        rows = [table.get_row_at(i) for i in range(table.row_count)]

    row_keys = {str(row[2]) for row in rows}
    assert "Active storage" in str(title)
    assert isinstance(editor.selection, ActivePathStorageSelection)
    assert str(storage_root.resolve()) in str(title)
    assert table.disabled is False
    assert register_button.disabled is True
    assert "APPRC_EXAMPLE_APP_STORAGE" not in row_keys
    assert (storage_root / ".env.apprc_example_app").is_file()


@pytest.mark.asyncio
async def test_editor_launches_with_missing_registered_storage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    storage_root = tmp_path / "alpha"
    registry = register_storage_for_kit(
        kit,
        name="alpha",
        root=storage_root,
    )
    shutil.rmtree(storage_root)
    editor = ConfigEditorApp(kit=kit, storage_registry=registry)

    async with editor.run_test():
        title = editor.query_one("#storage-title", Static).content
        table = editor.query_one("#field-table", DataTable)
        register_button = editor.query_one(
            "#storage-register-active",
            Button,
        )
        delete_button = editor.query_one("#storage-delete", Button)
        archive_button = editor.query_one("#storage-archive", Button)

    assert isinstance(editor.selection, MissingStorageSelection)
    assert "Missing storage root" in str(title)
    assert str(storage_root.resolve()) in str(title)
    assert isinstance(title, Text)
    assert text_has_span(title, str(storage_root.resolve()), PATH_STYLE)
    assert table.disabled is True
    assert register_button.disabled is True
    assert delete_button.disabled is False
    assert archive_button.disabled is True
    assert not storage_root.exists()


@pytest.mark.asyncio
async def test_editor_registers_missing_storage_directory_from_modal_flow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    create_empty_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    editor = ConfigEditorApp(
        kit=kit, storage_registry=load_existing_storage_registry(kit.spec)
    )
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

    registry = load_existing_storage_registry(kit.spec)
    assert registry.selected("alpha").root == storage_root.resolve()
    assert (storage_root / ".env.apprc_example_app").is_file()


@pytest.mark.asyncio
async def test_editor_unregisters_missing_storage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    beta_root = tmp_path / "beta"
    alpha_root = tmp_path / "alpha"
    register_storage_for_kit(kit, name="beta", root=beta_root)
    registry = register_storage_for_kit(
        kit,
        name="alpha",
        root=alpha_root,
    )
    shutil.rmtree(alpha_root)
    editor = ConfigEditorApp(
        kit=kit, storage_registry=registry, initial_storage="alpha"
    )

    async with editor.run_test() as pilot:
        worker = editor.run_worker(
            editor.storage_workflows.open_delete_storage_flow()
        )
        await pilot.pause()
        assert isinstance(editor.selection, MissingStorageSelection)
        assert list(editor.screen.query("#delete-content")) == []
        editor.screen.query_one("#unregister", Button).press()
        await pilot.pause()
        await worker.wait()

    registry = load_existing_storage_registry(kit.spec)
    assert sorted(registry.storages) == ["beta"]
    assert registry.selected("beta").root == beta_root.resolve()
    assert not alpha_root.exists()


@pytest.mark.asyncio
async def test_editor_unregisters_live_storage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    register_storage_for_kit(kit, name="alpha", root=tmp_path / "alpha")
    registry = register_storage_for_kit(
        kit,
        name="beta",
        root=tmp_path / "beta",
    )
    editor = ConfigEditorApp(kit=kit, storage_registry=registry)

    async with editor.run_test():
        editor._select_storage("alpha")
        removed = await editor.storage_workflows.remove_live_storage(
            "alpha",
            delete_content=False,
        )

    registry = load_existing_storage_registry(kit.spec)
    assert removed is True
    assert sorted(registry.storages) == ["beta"]
    assert (tmp_path / "alpha").is_dir()


@pytest.mark.asyncio
async def test_editor_unregisters_live_storage_without_replacement_prompt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    alpha_root = tmp_path / "alpha"
    beta_root = tmp_path / "beta"
    gamma_root = tmp_path / "gamma"
    register_storage_for_kit(kit, name="alpha", root=alpha_root)
    register_storage_for_kit(kit, name="beta", root=beta_root)
    registry = register_storage_for_kit(
        kit,
        name="gamma",
        root=gamma_root,
    )
    shutil.rmtree(beta_root)
    editor = ConfigEditorApp(kit=kit, storage_registry=registry)

    async with editor.run_test():
        removed = await editor.storage_workflows.remove_live_storage(
            "alpha",
            delete_content=False,
        )

    registry = load_existing_storage_registry(kit.spec)
    assert removed is True
    assert sorted(registry.storages) == ["beta", "gamma"]
    assert registry.selected("gamma").root == gamma_root.resolve()


@pytest.mark.asyncio
async def test_editor_registers_active_storage_from_button_flow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    create_empty_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    storage_root = tmp_path / "active"
    storage_root.mkdir()
    editor = ConfigEditorApp(
        kit=kit,
        storage_registry=load_existing_storage_registry(kit.spec),
        active_storage_root=storage_root,
    )

    async with editor.run_test() as pilot:
        worker = editor.run_worker(
            editor.storage_workflows.register_active_storage_flow()
        )
        await pilot.pause()
        editor.screen.query_one("#proceed", Button).press()
        await pilot.pause()
        name_input = editor.screen.query_one("#name-input", Input)
        assert name_input.value == "active"
        editor.screen.query_one("#name-continue", Button).press()
        await pilot.pause()
        await worker.wait()

    registry = load_existing_storage_registry(kit.spec)
    assert sorted(registry.storages) == ["active"]
    assert registry.selected("active").root == storage_root.resolve()


@pytest.mark.asyncio
async def test_editor_shows_and_prunes_stale_archived_rows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    registry = record_archived_storage_for_kit(
        kit,
        name="alpha",
        archive=tmp_path / "alpha.apprc.tar.xz",
        source_root=tmp_path / "alpha",
    )
    editor = ConfigEditorApp(kit=kit, storage_registry=registry)

    async with editor.run_test():
        storage_list = editor.query_one("#storage-list", ListView)
        assert storage_list.index == 0
        assert isinstance(editor.selection, ArchivedStorageSelection)
        await editor.storage_workflows.restore_or_prune_archived_storage(
            "alpha"
        )

    assert load_existing_storage_registry(kit.spec).archived_storages == {}


@pytest.mark.allow_missing_apprc_env
@pytest.mark.asyncio
async def test_editor_table_shows_storage_root_and_formats_rows(
    monkeypatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    monkeypatch.delenv("APPRC_EXAMPLE_APP_STORAGE", raising=False)
    monkeypatch.delenv("APPRC_EXAMPLE_APP_PROFILE", raising=False)
    monkeypatch.delenv("APPRC_EXAMPLE_APP_RETRY_COUNT", raising=False)
    monkeypatch.delenv("APPRC_EXAMPLE_APP_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("APPRC_EXAMPLE_APP_MODE", "MANUAL")
    kit = build_apprc_example_app_kit()
    registry = register_storage_for_kit(
        kit,
        name="alpha",
        root=tmp_path / "storage",
    )
    local_env = tmp_path / "storage" / ".env.apprc_example_app"
    local_env.write_text(
        f'APPRC_EXAMPLE_APP_STORAGE="{(tmp_path / "storage").resolve()}"\n'
        'APPRC_EXAMPLE_APP_ACCESS_TOKEN="super-secret"\n'
        'APPRC_EXAMPLE_APP_PROFILE="local-profile"\n'
        'APPRC_EXAMPLE_APP_RETRY_COUNT="7"\n',
        encoding="utf-8",
    )
    editor = ConfigEditorApp(kit=kit, storage_registry=registry)

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
    assert "APPRC_EXAMPLE_APP_STORAGE" not in rows_by_key
    assert rows_by_key["APPRC_EXAMPLE_APP_PROFILE"][:6] == [
        "1",
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
        SECRET_STYLE
    )
    assert rows_by_key["APPRC_EXAMPLE_APP_ACCESS_TOKEN"][5] == ""
    assert rows_by_key["APPRC_EXAMPLE_APP_MODE"][3] == "shell"
    assert rich_rows_by_key["APPRC_EXAMPLE_APP_MODE"][5].style == CHOICE_STYLE
    assert (
        rich_rows_by_key["APPRC_EXAMPLE_APP_ENABLED"][5].style == "bold magenta"
    )
    assert (
        rich_rows_by_key["APPRC_EXAMPLE_APP_RETRY_COUNT"][4].style
        == NUMBER_STYLE
    )
    assert (
        rich_rows_by_key["APPRC_EXAMPLE_APP_RETRY_COUNT"][5].style
        == NUMBER_STYLE
    )
    assert (
        rich_rows_by_key["APPRC_EXAMPLE_APP_CACHE_DIR"][5].style == PATH_STYLE
    )


@pytest.mark.asyncio
async def test_editor_table_required_missing_keeps_red_fill(
    monkeypatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    registry = register_storage_for_kit(
        kit,
        name="alpha",
        root=tmp_path / "storage",
    )
    editor = ConfigEditorApp(kit=kit, storage_registry=registry)

    async with editor.run_test():
        table = editor.query_one("#field-table", DataTable)
        rows = [table.get_row_at(i) for i in range(table.row_count)]
    rows_by_key = {str(row[2]): row for row in rows}

    assert str(rows_by_key["APPRC_EXAMPLE_APP_ACCESS_TOKEN"][5]) == "<required>"
    assert rows_by_key["APPRC_EXAMPLE_APP_ACCESS_TOKEN"][5].style == (
        REQUIRED_STYLE
    )


@pytest.mark.asyncio
async def test_editor_modal_saves_local_value(
    monkeypatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    storage_root = tmp_path / "storage"
    registry = register_storage_for_kit(
        kit,
        name="alpha",
        root=storage_root,
    )
    editor = ConfigEditorApp(kit=kit, storage_registry=registry)

    async with editor.run_test() as pilot:
        await open_field_editor(
            editor,
            "APPRC_EXAMPLE_APP_PROFILE",
            pilot,
        )
        input_widget = editor.screen.query_one("#edit-value-input", Input)
        input_widget.value = "other-profile"
        editor.screen.query_one("#edit-save", Button).press()
        await pilot.pause()

    assert 'APPRC_EXAMPLE_APP_PROFILE="other-profile"\n' in (
        storage_root / ".env.apprc_example_app"
    ).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_editor_modal_copies_source_values_without_saving(
    monkeypatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    monkeypatch.setenv("APPRC_EXAMPLE_APP_PROFILE", "shell-profile")
    kit = build_apprc_example_app_kit()
    storage_root = tmp_path / "storage"
    registry = register_storage_for_kit(
        kit,
        name="alpha",
        root=storage_root,
    )
    local_env = storage_root / ".env.apprc_example_app"
    local_env.write_text(
        'APPRC_EXAMPLE_APP_PROFILE="local-profile"\n',
        encoding="utf-8",
    )
    editor = ConfigEditorApp(kit=kit, storage_registry=registry)

    async with editor.run_test() as pilot:
        await open_field_editor(
            editor,
            "APPRC_EXAMPLE_APP_PROFILE",
            pilot,
        )

        input_widget = editor.screen.query_one("#edit-value-input", Input)
        input_widget.value = "unsaved-profile"
        effective_value = editor.screen.query_one(
            "#edit-source-effective-value",
            Static,
        ).content
        effective_origin = editor.screen.query_one(
            "#edit-source-effective-origin",
            Static,
        ).content
        shared_value = editor.screen.query_one(
            "#edit-source-shared-value",
            Static,
        ).content

        editor.screen.query_one("#edit-copy-effective", Button).press()
        await pilot.pause()
        assert editor.clipboard == "shell-profile"
        editor.screen.query_one("#edit-copy-local", Button).press()
        await pilot.pause()
        assert editor.clipboard == "unsaved-profile"
        editor.screen.query_one("#edit-copy-shared", Button).press()
        await pilot.pause()

        assert editor.clipboard == "default"
        assert str(effective_value) == "shell-profile"
        assert str(effective_origin) == "from Shell"
        assert str(shared_value) == "default"
        assert editor.screen.query_one("#edit-value-input", Input).value == (
            "unsaved-profile"
        )
        assert (
            editor.screen.query_one(
                "#edit-source-local #edit-value-input",
                Input,
            ).value
            == "unsaved-profile"
        )
        local_row = editor.screen.query_one("#edit-source-local")
        local_label = editor.screen.query_one(
            "#edit-source-local-label",
            Static,
        )
        local_origin = editor.screen.query_one(
            "#edit-source-local-origin",
            Static,
        )
        local_copy = editor.screen.query_one("#edit-copy-local", Button)
        shared_row = editor.screen.query_one("#edit-source-shared")
        shared_copy = editor.screen.query_one("#edit-copy-shared", Button)

        for widget in (
            local_label,
            input_widget,
            local_origin,
            local_copy,
        ):
            assert widget.region.x >= local_row.region.x
            assert region_right(widget) <= region_right(local_row)
        assert region_right(shared_copy) <= region_right(shared_row)

    assert "unsaved-profile" not in local_env.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_editor_modal_keeps_sources_visible_at_compact_height(
    monkeypatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    registry = register_storage_for_kit(
        kit,
        name="alpha",
        root=tmp_path / "storage",
    )
    editor = ConfigEditorApp(kit=kit, storage_registry=registry)

    async with editor.run_test(size=(120, 18)) as pilot:
        await open_field_editor(
            editor,
            "APPRC_EXAMPLE_APP_MODE",
            pilot,
        )

        dialog = editor.screen.query_one("#edit-dialog")
        details = editor.screen.query_one("#edit-details-scroll")
        source_panel = editor.screen.query_one("#edit-source-panel")
        effective = editor.screen.query_one("#edit-source-effective")
        shell = editor.screen.query_one("#edit-source-shell")
        local = editor.screen.query_one("#edit-source-local")
        shared = editor.screen.query_one("#edit-source-shared")
        button_row = editor.screen.query_one("#edit-button-row")
        local_input = editor.screen.query_one("#edit-value-input", Input)

        dialog_bottom = region_bottom(dialog)
        for widget in (
            source_panel,
            effective,
            shell,
            local,
            shared,
            button_row,
        ):
            assert widget.region.y >= dialog.region.y
            assert region_bottom(widget) <= dialog_bottom
        assert region_bottom(details) <= source_panel.region.y
        assert region_bottom(source_panel) <= button_row.region.y
        assert source_panel.region.height == len(
            list(editor.screen.query(".edit-source-row"))
        )
        assert effective.region.height == 1
        assert shell.region.height == 1
        assert local.region.height == 1
        assert shared.region.height == 1
        assert local_input.region.y == local.region.y
        assert local_input.region.x >= local.region.x
        assert region_right(local_input) <= region_right(local)


@pytest.mark.asyncio
async def test_editor_modal_details_scroll_when_height_is_compact(
    monkeypatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    registry = register_storage_for_kit(
        kit,
        name="alpha",
        root=tmp_path / "storage",
    )
    editor = ConfigEditorApp(kit=kit, storage_registry=registry)

    async with editor.run_test(size=(120, 18)) as pilot:
        await open_field_editor(
            editor,
            "APPRC_EXAMPLE_APP_MODE",
            pilot,
        )
        details = editor.screen.query_one(
            "#edit-details-scroll",
            VerticalScroll,
        )

        assert details.allow_vertical_scroll is True
        assert details.show_vertical_scrollbar is True
        assert details.max_scroll_y > 0
        assert details.region.height < details.scrollable_size.height + int(
            details.max_scroll_y
        )


@pytest.mark.asyncio
async def test_editor_modal_enables_local_copy_when_user_types(
    monkeypatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    registry = register_storage_for_kit(
        kit,
        name="alpha",
        root=tmp_path / "storage",
    )
    editor = ConfigEditorApp(kit=kit, storage_registry=registry)

    async with editor.run_test() as pilot:
        await open_field_editor(
            editor,
            "APPRC_EXAMPLE_APP_PROFILE",
            pilot,
        )

        local_copy = editor.screen.query_one("#edit-copy-local", Button)
        input_widget = editor.screen.query_one("#edit-value-input", Input)

        assert local_copy.disabled is True
        input_widget.value = "draft-profile"
        await pilot.pause()
        assert local_copy.disabled is False
        local_copy.press()
        await pilot.pause()

    assert editor.clipboard == "draft-profile"


@pytest.mark.asyncio
async def test_editor_modal_redacts_secret_sources_but_copies_raw_value(
    monkeypatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    monkeypatch.delenv("APPRC_EXAMPLE_APP_ACCESS_TOKEN", raising=False)
    kit = build_apprc_example_app_kit()
    storage_root = tmp_path / "storage"
    registry = register_storage_for_kit(
        kit,
        name="alpha",
        root=storage_root,
    )
    (storage_root / ".env.apprc_example_app").write_text(
        'APPRC_EXAMPLE_APP_ACCESS_TOKEN="super-secret"\n',
        encoding="utf-8",
    )
    editor = ConfigEditorApp(kit=kit, storage_registry=registry)

    async with editor.run_test() as pilot:
        await open_field_editor(
            editor,
            "APPRC_EXAMPLE_APP_ACCESS_TOKEN",
            pilot,
        )

        effective_value = static_text(
            editor.screen.query_one("#edit-source-effective-value", Static)
        )
        effective_origin = static_text(
            editor.screen.query_one("#edit-source-effective-origin", Static)
        )
        shell_value = static_text(
            editor.screen.query_one("#edit-source-shell-value", Static)
        )
        shared_value = static_text(
            editor.screen.query_one("#edit-source-shared-value", Static)
        )
        input_widget = editor.screen.query_one("#edit-value-input", Input)
        editor.screen.query_one("#edit-copy-local", Button).press()
        await pilot.pause()

        assert str(effective_value) == "<secret>"
        assert effective_value.style == EFFECTIVE_SOURCE_STYLE
        assert str(effective_origin) == "from Local"
        assert str(shell_value) == "unset"
        assert shell_value.style == LABEL_STYLE
        assert str(shared_value) == "missing"
        assert input_widget.value == "super-secret"
        assert editor.clipboard == "super-secret"


@pytest.mark.asyncio
async def test_editor_modal_shows_type_choices_and_long_explanation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    monkeypatch.delenv("APPRC_EXAMPLE_APP_MODE", raising=False)
    kit = build_apprc_example_app_kit()
    registry = register_storage_for_kit(
        kit,
        name="alpha",
        root=tmp_path / "storage",
    )
    editor = ConfigEditorApp(kit=kit, storage_registry=registry)

    async with editor.run_test() as pilot:
        await open_field_editor(
            editor,
            "APPRC_EXAMPLE_APP_MODE",
            pilot,
        )
        type_value = static_text(
            editor.screen.query_one("#edit-type-value", Static)
        )
        possible_values = static_text(
            editor.screen.query_one("#edit-possible-values-value", Static)
        )
        explanation_title = static_text(
            editor.screen.query_one("#edit-explanation-title", Static)
        )
        long_explanation = editor.screen.query_one(
            "#edit-long-explanation",
            Static,
        ).content
        effective_label = static_text(
            editor.screen.query_one("#edit-source-effective-label", Static)
        )
        effective_origin = static_text(
            editor.screen.query_one("#edit-source-effective-origin", Static)
        )

    assert str(type_value) == "str"
    assert type_value.style == TEXT_STYLE
    assert str(possible_values) == "AUTO, MANUAL"
    assert possible_values.style == CHOICE_STYLE
    assert str(explanation_title) == "Explanation"
    assert explanation_title.style == "bold"
    assert "Operating mode used by Example App commands." in str(
        long_explanation
    )
    assert str(effective_label) == "Effective"
    assert effective_label.style == EFFECTIVE_SOURCE_STYLE
    assert str(effective_origin) == "from Shared default"


@pytest.mark.asyncio
async def test_editor_modal_styles_generic_possible_values(
    monkeypatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    registry = register_storage_for_kit(
        kit,
        name="alpha",
        root=tmp_path / "storage",
    )
    editor = ConfigEditorApp(kit=kit, storage_registry=registry)

    async with editor.run_test() as pilot:
        await open_field_editor(
            editor,
            "APPRC_EXAMPLE_APP_ACCESS_TOKEN",
            pilot,
        )
        possible_values = static_text(
            editor.screen.query_one("#edit-possible-values-value", Static)
        )

    assert str(possible_values) == "free text"
    assert possible_values.style == GENERIC_VALUE_STYLE


@pytest.mark.asyncio
async def test_editor_modal_marks_path_inputs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    registry = register_storage_for_kit(
        kit,
        name="alpha",
        root=tmp_path / "storage",
    )
    editor = ConfigEditorApp(kit=kit, storage_registry=registry)

    async with editor.run_test() as pilot:
        await open_field_editor(
            editor,
            "APPRC_EXAMPLE_APP_CACHE_DIR",
            pilot,
        )
        input_widget = editor.screen.query_one("#edit-value-input", Input)
        type_value = static_text(
            editor.screen.query_one("#edit-type-value", Static)
        )

    assert input_widget.has_class(PATH_INPUT_CLASS)
    assert str(type_value) == "Path"
    assert type_value.style == PATH_STYLE


@pytest.mark.asyncio
async def test_archive_options_marks_path_input_and_source_path(
    monkeypatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    registry = register_storage_for_kit(
        kit,
        name="alpha",
        root=tmp_path / "storage",
    )
    editor = ConfigEditorApp(kit=kit, storage_registry=registry)
    source_root = registry.selected("alpha").root

    async with editor.run_test() as pilot:
        await editor.push_screen(
            ArchiveOptionsScreen(
                storage_name="alpha",
                source_root=source_root,
                default_archive=tmp_path / "alpha.apprc.tar.xz",
            )
        )
        await pilot.pause()
        input_widget = editor.screen.query_one("#archive-path-input", Input)
        message = editor.screen.query_one("#archive-message", Static).content

    assert input_widget.has_class(PATH_INPUT_CLASS)
    assert isinstance(message, Text)
    assert text_has_span(message, str(source_root), PATH_STYLE)
