from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from textual.widgets import Button, DataTable, Input, Static
from typer.testing import CliRunner

from apprc import AppConfigKit
from apprc.config import (
    CONFIG_MISSING,
    ConfigOwner,
    EnvBootstrapResult,
    config_field,
)

DEMO_OWNER = ConfigOwner(
    key="runtime",
    title="Runtime",
    env_prefix="DEMO_",
    rc_path=("runtime",),
    runtime_cls=None,
    fields=(
        config_field(
            "storage_root",
            "D_STORAGE",
            Path,
            default=CONFIG_MISSING,
            editable=False,
            required=True,
        ),
        config_field(
            "model",
            "MODEL",
            str,
            default="demo-model",
            title="Demo model",
            explanation=(
                "Model used by the demo runtime. Longer context appears in "
                "the modal editor."
            ),
        ),
        config_field(
            "api_token",
            "API_TOKEN",
            str,
            default=CONFIG_MISSING,
            title="API token",
            explanation_short="Required provider token.",
            explanation_long=(
                "Secret token required by the demo runtime when no shell "
                "environment or local override provides one."
            ),
            required=True,
            secret=True,
        ),
        config_field(
            "strategy",
            "STRATEGY",
            str,
            default="VECTOR",
            title="Strategy",
            explanation="Selection strategy for demo candidates.",
            choices=("VECTOR", "WEIGHT"),
        ),
    ),
)
DEMO_OWNERS = (DEMO_OWNER,)


@dataclass(slots=True)
class _ConfigState:
    env_bootstrap: EnvBootstrapResult | None
    storage: str | None = None


def _kit() -> AppConfigKit:
    """Return a tiny app config kit for tests."""
    return AppConfigKit(
        app_name="demo",
        display_name="Demo",
        config_package="apprc.config",
        owners=DEMO_OWNERS,
        storage_root_env_key="DEMO_D_STORAGE",
        registry_filename="demo.toml",
        local_env_filename=".env.demo",
    )


def _state(kit: AppConfigKit, storage_root: Path) -> _ConfigState:
    """Return generic CLI state with one active storage root."""
    return _ConfigState(
        env_bootstrap=EnvBootstrapResult(
            shared_env=None,
            local_env=storage_root / ".env.demo",
            env_file=None,
            registry_path=kit.registry_path(),
            storage_name="alpha",
            storage_root=storage_root,
            used_default_storage=True,
            storage_count=1,
        ),
        storage="alpha",
    )


def test_kit_registers_storage_and_reports_doctor_payload(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    kit = _kit()
    storage_root = tmp_path / "storage"

    registry = kit.register_storage(
        name="alpha",
        root=storage_root,
        make_default=True,
    )
    payload = kit.doctor_payload()

    assert registry.path == tmp_path / "config" / "demo" / "demo.toml"
    assert (storage_root / ".env.demo").is_file()
    assert payload["ok"] is True
    assert payload["default_storage"] == "alpha"
    assert payload["selected_storage_root"] == str(storage_root.resolve())
    assert payload["selected_local_env_exists"] is True


def test_generated_config_app_sets_local_values_and_shows_payload(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    kit = _kit()
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    state = _state(kit, storage_root)
    app = kit.typer_app(
        state_type=_ConfigState,
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


def test_kit_builds_generic_editor_with_spec_defaults(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    kit = _kit()
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
async def test_editor_table_hides_storage_root_and_formats_rows(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("DEMO_STRATEGY", "WEIGHT")
    kit = _kit()
    registry = kit.register_storage(
        name="alpha",
        root=tmp_path / "storage",
        make_default=True,
    )
    editor = kit.editor_app(registry=registry)

    async with editor.run_test():
        table = editor.query_one("#field-table", DataTable)
        rows = [table.get_row_at(i) for i in range(table.row_count)]

    column_labels = [column.label.plain for column in table.columns.values()]
    row_text = [[str(cell) for cell in row] for row in rows]

    assert column_labels == [
        "#",
        "Section",
        "Key",
        "Status",
        "Local",
        "Default",
        "Explanation",
    ]
    assert "DEMO_D_STORAGE" not in {row[2] for row in row_text}
    assert [
        "1",
        "Runtime",
        "DEMO_MODEL",
        "unset",
        "",
        "demo-model",
    ] == row_text[0][:6]
    assert row_text[1][2] == "DEMO_API_TOKEN"
    assert row_text[1][5] == "<required>"
    assert rows[1][5].style == "bold white on red"
    assert row_text[2][2] == "DEMO_STRATEGY"
    assert row_text[2][3] == "shell"
    assert rows[0][6].style == "dim"


@pytest.mark.asyncio
async def test_editor_modal_saves_local_value(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    kit = _kit()
    storage_root = tmp_path / "storage"
    registry = kit.register_storage(
        name="alpha",
        root=storage_root,
        make_default=True,
    )
    editor = kit.editor_app(registry=registry)

    async with editor.run_test() as pilot:
        table = editor.query_one("#field-table", DataTable)
        table.cursor_coordinate = (0, 0)
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
    kit = _kit()
    registry = kit.register_storage(
        name="alpha",
        root=tmp_path / "storage",
        make_default=True,
    )
    editor = kit.editor_app(registry=registry)

    async with editor.run_test() as pilot:
        table = editor.query_one("#field-table", DataTable)
        table.cursor_coordinate = (2, 0)
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
