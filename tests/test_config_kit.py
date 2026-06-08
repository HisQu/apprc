from __future__ import annotations

import json
from pathlib import Path

import pytest
from textual.widgets import Button, DataTable, Input, ListView, Static
from typer.testing import CliRunner

from apprc.cli.config_app import config_request_skips_bootstrap
from apprc.config import (
    config_field,
)
from tests.support_config import (
    DEMO_OWNERS,
    DemoConfigState,
    build_demo_kit,
    demo_state,
)


def test_config_init_and_list_skip_runtime_bootstrap() -> None:
    assert config_request_skips_bootstrap(["init", "/tmp/storage"])
    assert config_request_skips_bootstrap(["list"])
    assert config_request_skips_bootstrap(["edit"])


def test_kit_registers_storage_and_reports_doctor_payload(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    kit = build_demo_kit()
    storage_root = tmp_path / "storage"

    registry = kit.register_storage(
        name="alpha",
        root=storage_root,
        make_default=True,
    )
    payload = kit.doctor_payload()

    assert registry.path == tmp_path / "config" / "demo" / "demo.toml"
    assert (storage_root / ".env.demo").is_file()
    assert f'DEMO_D_STORAGE="{storage_root.resolve()}"\n' in (
        storage_root / ".env.demo"
    ).read_text(encoding="utf-8")
    assert payload["ok"] is True
    assert payload["default_storage"] == "alpha"
    assert payload["selected_storage_root"] == str(storage_root.resolve())
    assert payload["selected_local_env_exists"] is True


def test_kit_set_default_syncs_storage_root_local_env(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    kit = build_demo_kit()
    beta_root = tmp_path / "beta"
    kit.register_storage(
        name="alpha",
        root=tmp_path / "alpha",
        make_default=True,
    )
    kit.register_storage(
        name="beta",
        root=beta_root,
        make_default=False,
    )
    beta_local_env = beta_root / ".env.demo"
    beta_local_env.write_text('DEMO_MODEL="custom"\n', encoding="utf-8")

    registry = kit.set_default_storage(name="beta")

    assert registry.default_storage == "beta"
    assert beta_local_env.read_text(encoding="utf-8") == (
        f'DEMO_D_STORAGE="{beta_root.resolve()}"\nDEMO_MODEL="custom"\n'
    )


def test_generated_config_app_sets_local_values_and_shows_payload(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    kit = build_demo_kit()
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    state = demo_state(kit, storage_root)
    app = kit.typer_app(
        state_type=DemoConfigState,
        runtime_payload=lambda current: {
            "storage": str(current.env_bootstrap.storage_root)
            if current.env_bootstrap is not None
            else None,
        },
    )
    runner = CliRunner()

    set_result = runner.invoke(
        app,
        ["set", "runtime.model", "other-model"],
        obj=state,
    )
    show_result = runner.invoke(app, ["show", "--json"], obj=state)

    assert set_result.exit_code == 0, set_result.output
    assert 'DEMO_MODEL="other-model"\n' in (
        storage_root / ".env.demo"
    ).read_text(encoding="utf-8")
    assert show_result.exit_code == 0, show_result.output
    assert json.loads(show_result.output) == {"storage": str(storage_root)}


def test_generated_config_app_inits_existing_storage_after_list_prompt(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    kit = build_demo_kit()
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    (storage_root / "payload.txt").write_text("demo", encoding="utf-8")
    app = kit.typer_app(state_type=DemoConfigState)
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["init", str(storage_root), "--name", "alpha", "--default"],
        input="l\ny\n",
    )

    assert result.exit_code == 0, result.output
    assert "Storage root already exists and is not empty" in result.output
    assert (
        "AppRC will reuse this directory for Demo storage 'alpha'."
        in result.output
    )
    assert "It will create or update only these config files:" in result.output
    assert "storage-local env:" in result.output
    assert "user registry:" in result.output
    assert (
        "Existing files in the storage root will not be deleted, moved, "
        "or overwritten."
    ) in result.output
    assert "It will also mark 'alpha' as the default storage." in result.output
    assert "Answer l to list first-level contents" in result.output
    assert "payload.txt" in result.output
    assert f'DEMO_D_STORAGE="{storage_root.resolve()}"\n' in (
        storage_root / ".env.demo"
    ).read_text(encoding="utf-8")


def test_generated_config_app_rejects_shell_damaged_windows_storage_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    kit = build_demo_kit()
    app = kit.typer_app(state_type=DemoConfigState)
    runner = CliRunner()
    malformed = "C:Projectsdemo-storage"
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ["init", malformed, "--name", "alpha", "--default"],
    )

    assert result.exit_code == 2, result.output
    assert "STORAGE_ROOT" in result.output
    assert "Storage root looks like a Windows drive" in result.output
    assert "path, but it is missing a slash" in result.output
    assert "backslashes are consumed" in result.output
    assert "C:/Projects/demo-storage" in result.output
    assert not Path(malformed).exists()
    assert not kit.registry_path().exists()


def test_generated_config_app_aborts_existing_storage_when_user_says_no(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    kit = build_demo_kit()
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    (storage_root / "payload.txt").write_text("demo", encoding="utf-8")
    app = kit.typer_app(state_type=DemoConfigState)
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["init", str(storage_root), "--name", "alpha"],
        input="n\n",
    )

    assert result.exit_code == 1, result.output
    assert "Aborted." in result.output
    assert not kit.registry_path().exists()
    assert not (storage_root / ".env.demo").exists()


def test_generated_config_app_inits_non_empty_storage_with_yes_option(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    kit = build_demo_kit()
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    (storage_root / "payload.txt").write_text("demo", encoding="utf-8")
    app = kit.typer_app(state_type=DemoConfigState)
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["init", str(storage_root), "--name", "alpha", "--yes"],
    )

    assert result.exit_code == 0, result.output
    assert "Continue? [y/n/l]" not in result.output
    assert (storage_root / ".env.demo").is_file()


def test_generated_config_app_lists_registered_storages_as_rich_tree(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    kit = build_demo_kit()
    alpha_root = tmp_path / "alpha"
    beta_root = tmp_path / "beta"
    kit.register_storage(name="alpha", root=alpha_root, make_default=True)
    kit.register_storage(name="beta", root=beta_root, make_default=False)
    app = kit.typer_app(state_type=DemoConfigState)
    runner = CliRunner()

    result = runner.invoke(app, ["list"])

    assert result.exit_code == 0, result.output
    assert "registry:" in result.output
    assert "default_storage:" in result.output
    assert "storages:" in result.output
    assert "alpha [default]" in result.output
    assert "beta" in result.output
    assert "root:" in result.output
    assert "root_exists:" in result.output
    assert "local_env:" in result.output
    assert "local_env_exists:" in result.output
    root_lines = [
        line
        for line in result.output.splitlines()
        if "root:" in line and "root_exists:" not in line
    ]
    assert root_lines
    assert all(not line.startswith("root:") for line in root_lines)


def test_generated_config_app_lists_registered_storages_as_json(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    kit = build_demo_kit()
    alpha_root = tmp_path / "alpha"
    beta_root = tmp_path / "beta"
    kit.register_storage(name="alpha", root=alpha_root, make_default=True)
    kit.register_storage(name="beta", root=beta_root, make_default=False)
    app = kit.typer_app(state_type=DemoConfigState)
    runner = CliRunner()

    result = runner.invoke(app, ["list", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == {
        "default_storage": "alpha",
        "registry": str(tmp_path / "config" / "demo" / "demo.toml"),
        "storages": [
            {
                "default": True,
                "local_env": str(alpha_root.resolve() / ".env.demo"),
                "local_env_exists": True,
                "name": "alpha",
                "root": str(alpha_root.resolve()),
                "root_exists": True,
            },
            {
                "default": False,
                "local_env": str(beta_root.resolve() / ".env.demo"),
                "local_env_exists": True,
                "name": "beta",
                "root": str(beta_root.resolve()),
                "root_exists": True,
            },
        ],
    }


def test_kit_builds_generic_editor_with_spec_defaults(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    kit = build_demo_kit()
    registry = kit.register_storage(
        name="alpha",
        root=tmp_path / "storage",
        make_default=True,
    )

    editor = kit.editor_app(registry=registry)

    assert editor.owners == DEMO_OWNERS
    assert editor.local_env_filename == ".env.demo"
    assert editor.init_command == "demo config init STORAGE_ROOT --name NAME"
    assert editor.registry_label == "demo.toml"


@pytest.mark.asyncio
async def test_editor_launches_with_empty_registry_and_new_storage_button(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    kit = build_demo_kit()
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
async def test_editor_registers_missing_storage_directory_from_modal_flow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    kit = build_demo_kit()
    editor = kit.editor_app(registry=kit.load_registry())
    storage_root = tmp_path / "alpha"

    async with editor.run_test() as pilot:
        worker = editor.run_worker(
            editor._register_storage_directory_flow(
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
    assert (storage_root / ".env.demo").is_file()


@pytest.mark.asyncio
async def test_editor_set_default_and_unregister_non_default_storage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    kit = build_demo_kit()
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
        await editor._set_current_as_default()
        editor._select_storage("alpha")
        removed = await editor._remove_live_storage(
            "alpha",
            delete_content=False,
        )

    registry = kit.load_registry()
    assert removed is True
    assert registry.default_storage == "beta"
    assert sorted(registry.storages) == ["beta"]
    assert (tmp_path / "alpha").is_dir()


@pytest.mark.asyncio
async def test_editor_shows_and_prunes_stale_archived_rows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    kit = build_demo_kit()
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
        await editor._restore_or_prune_archived_storage("alpha")

    assert kit.load_registry().archived_storages == {}


def test_config_field_splits_short_and_long_explanations() -> None:
    spec = config_field(
        "demo",
        "DEMO",
        str,
        explanation=(
            "Short sentence. Extra detail that should remain available in "
            "the modal."
        ),
    )

    assert spec.explanation_short == "Short sentence."
    assert spec.explanation_long.startswith("Short sentence. Extra detail")
    assert spec.explanation == spec.explanation_long


@pytest.mark.asyncio
async def test_editor_table_shows_storage_root_and_formats_rows(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("DEMO_STRATEGY", "WEIGHT")
    kit = build_demo_kit()
    registry = kit.register_storage(
        name="alpha",
        root=tmp_path / "storage",
        make_default=True,
    )
    local_env = tmp_path / "storage" / ".env.demo"
    local_env.write_text(
        f'DEMO_D_STORAGE="{(tmp_path / "storage").resolve()}"\n'
        'DEMO_API_TOKEN="super-secret"\n'
        'DEMO_MODEL="local-model"\n'
        'DEMO_RETRY_COUNT="7"\n',
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
    assert rows_by_key["DEMO_D_STORAGE"][3] == "unset"
    assert rows_by_key["DEMO_D_STORAGE"][4] == str(
        (tmp_path / "storage").resolve()
    )
    assert rows_by_key["DEMO_MODEL"][:6] == [
        "2",
        "Runtime",
        "DEMO_MODEL",
        "unset",
        "local-model",
        "demo-model",
    ]
    assert rich_rows_by_key["DEMO_MODEL"][4].style == "white"
    assert rich_rows_by_key["DEMO_MODEL"][5].style == "white"
    assert rows_by_key["DEMO_API_TOKEN"][4] == "<secret>"
    assert rich_rows_by_key["DEMO_API_TOKEN"][4].style == "dim italic"
    assert rows_by_key["DEMO_API_TOKEN"][5] == ""
    assert rows_by_key["DEMO_STRATEGY"][3] == "shell"
    assert rich_rows_by_key["DEMO_STRATEGY"][5].style == "bold cyan"
    assert rich_rows_by_key["DEMO_ENABLED"][5].style == "bold magenta"
    assert rich_rows_by_key["DEMO_RETRY_COUNT"][4].style == "yellow"
    assert rich_rows_by_key["DEMO_RETRY_COUNT"][5].style == "yellow"
    assert rich_rows_by_key["DEMO_CACHE_DIR"][5].style == "green"
    assert rich_rows_by_key["DEMO_D_STORAGE"][6].style == "dim"


@pytest.mark.asyncio
async def test_editor_table_required_missing_keeps_red_fill(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    kit = build_demo_kit()
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

    assert str(rows_by_key["DEMO_API_TOKEN"][5]) == "<required>"
    assert rows_by_key["DEMO_API_TOKEN"][5].style == "bold white on red"


@pytest.mark.asyncio
async def test_editor_modal_saves_local_value(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    kit = build_demo_kit()
    storage_root = tmp_path / "storage"
    registry = kit.register_storage(
        name="alpha",
        root=storage_root,
        make_default=True,
    )
    editor = kit.editor_app(registry=registry)

    async with editor.run_test() as pilot:
        table = editor.query_one("#field-table", DataTable)
        table.cursor_coordinate = (1, 0)
        editor._open_selected_field_editor()
        await pilot.pause()
        input_widget = editor.screen.query_one("#edit-value-input", Input)
        input_widget.value = "other-model"
        editor.screen.query_one("#edit-save", Button).press()
        await pilot.pause()

    assert 'DEMO_MODEL="other-model"\n' in (
        storage_root / ".env.demo"
    ).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_editor_modal_shows_type_choices_and_long_explanation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    kit = build_demo_kit()
    registry = kit.register_storage(
        name="alpha",
        root=tmp_path / "storage",
        make_default=True,
    )
    editor = kit.editor_app(registry=registry)

    async with editor.run_test() as pilot:
        table = editor.query_one("#field-table", DataTable)
        table.cursor_coordinate = (3, 0)
        editor._open_selected_field_editor()
        await pilot.pause()
        metadata = editor.screen.query_one("#edit-metadata", Static).content
        long_explanation = editor.screen.query_one(
            "#edit-long-explanation",
            Static,
        ).content

    assert "Type: str" in str(metadata)
    assert "Possible values: VECTOR, WEIGHT" in str(metadata)
    assert "Selection strategy for demo candidates." in str(long_explanation)
