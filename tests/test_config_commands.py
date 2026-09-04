from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from apprc.user_files.storage_roots.registry import (
    load_storage_registry_or_empty,
)
from tests.support_config import (
    ApprcExampleAppConfigState,
    StorageFreeExampleConfigState,
    build_apprc_example_app_kit,
    build_storage_free_example_kit,
)


def test_config_paths_is_zero_write_and_uses_file_specific_names() -> None:
    kit = build_apprc_example_app_kit()
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)

    result = CliRunner().invoke(app, ["paths", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["writes"] == "none"
    assert payload["storage_enabled"] is True
    assert payload["user_dotenv"].endswith("/apprc.user.env")
    assert payload["apprc_toml"].endswith("/apprc.toml")
    assert not Path(payload["user_dotenv"]).exists()
    assert not Path(payload["apprc_toml"]).exists()


def test_storage_free_app_hides_storage_commands() -> None:
    kit = build_storage_free_example_kit()
    app = kit.typer_app(state_type=StorageFreeExampleConfigState)
    runner = CliRunner()

    help_result = runner.invoke(app, ["--help"])
    command_result = runner.invoke(app, ["storage", "list"])
    storage_scope = runner.invoke(
        app,
        ["set", "global.profile", "demo", "--scope", "storage"],
    )

    assert help_result.exit_code == 0, help_result.output
    assert "Manage named storages" not in help_result.output
    assert command_result.exit_code != 0
    assert storage_scope.exit_code != 0
    assert "user" in storage_scope.output.lower()


def test_storage_cli_enforces_selection_lifecycle(tmp_path: Path) -> None:
    kit = build_apprc_example_app_kit()
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()
    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"

    first = runner.invoke(app, ["storage", "add", "alpha", str(alpha), "--yes"])
    second = runner.invoke(app, ["storage", "add", "beta", str(beta), "--yes"])
    duplicate = runner.invoke(
        app, ["storage", "add", "alpha", str(tmp_path / "other"), "--yes"]
    )
    renamed = runner.invoke(app, ["storage", "rename", "alpha", "primary"])
    selected = runner.invoke(app, ["storage", "select", "beta"])
    removed = runner.invoke(app, ["storage", "remove", "beta"])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert duplicate.exit_code != 0
    assert "already registered" in duplicate.output
    assert renamed.exit_code == 0, renamed.output
    assert "selected_storage: primary" in renamed.output
    assert selected.exit_code == 0, selected.output
    assert removed.exit_code == 0, removed.output
    assert "no storage is selected" in removed.output
    registry = load_storage_registry_or_empty(
        kit.spec.preferred_apprc_toml_path()
    )
    assert list(registry.storages) == ["primary"]
    assert registry.selected_storage is None


def test_storage_repoint_changes_only_registry_path(tmp_path: Path) -> None:
    kit = build_apprc_example_app_kit()
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()
    source = tmp_path / "source"
    target = tmp_path / "target"
    add = runner.invoke(app, ["storage", "add", "alpha", str(source), "--yes"])
    target.mkdir()

    repoint = runner.invoke(app, ["storage", "repoint", "alpha", str(target)])

    assert add.exit_code == 0, add.output
    assert repoint.exit_code == 0, repoint.output
    assert "files_moved: no" in repoint.output
    assert source.is_dir()
    assert target.is_dir()
    registry = load_storage_registry_or_empty(
        kit.spec.preferred_apprc_toml_path()
    )
    assert registry.selected("alpha").root == target.resolve()


def test_storage_move_moves_directory_and_updates_registry(
    tmp_path: Path,
) -> None:
    kit = build_apprc_example_app_kit()
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    add = runner.invoke(app, ["storage", "add", "alpha", str(source), "--yes"])
    (source / "payload.txt").write_text("keep", encoding="utf-8")

    moved = runner.invoke(
        app, ["storage", "move", "alpha", str(destination), "--yes"]
    )

    assert add.exit_code == 0, add.output
    assert moved.exit_code == 0, moved.output
    assert not source.exists()
    assert (destination / "payload.txt").read_text(encoding="utf-8") == "keep"
    registry = load_storage_registry_or_empty(
        kit.spec.preferred_apprc_toml_path()
    )
    assert registry.selected("alpha").root == destination.resolve()


def test_relative_storage_roots_resolve_from_apprc_toml(
    monkeypatch,
    tmp_path: Path,
) -> None:
    kit = build_apprc_example_app_kit()
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    unrelated_cwd = tmp_path / "cwd"
    unrelated_cwd.mkdir()
    monkeypatch.chdir(unrelated_cwd)

    result = CliRunner().invoke(
        app, ["storage", "add", "alpha", "relative-root", "--yes"]
    )

    assert result.exit_code == 0, result.output
    registry = load_storage_registry_or_empty(
        kit.spec.preferred_apprc_toml_path()
    )
    assert (
        registry.selected("alpha").root
        == (kit.spec.apprc_dir() / "relative-root").resolve()
    )


def test_config_set_writes_user_dotenv_for_storage_free_app() -> None:
    kit = build_storage_free_example_kit()
    app = kit.typer_app(state_type=StorageFreeExampleConfigState)

    result = CliRunner().invoke(
        app,
        ["set", "global.profile", "local", "--scope", "user"],
    )

    assert result.exit_code == 0, result.output
    assert kit.spec.user_dotenv_path().read_text(encoding="utf-8") == (
        'STORAGE_FREE_APP_PROFILE="local"\n'
    )
