from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.support_config import (
    ApprcExampleAppConfigState,
    StorageFreeExampleConfigState,
    apprc_example_app_state,
    build_apprc_example_app_kit,
    build_storage_free_example_kit,
)


def test_config_paths_reports_zero_writes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    kit = build_apprc_example_app_kit()
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)

    result = CliRunner().invoke(app, ["paths", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["writes"] == "none"
    assert payload["capabilities"] == {
        "app_wide": "optional",
        "named_storage": "optional",
        "storage": "required",
    }
    assert not Path(payload["app_wide_env"]).exists()
    assert not Path(payload["index_path"]).exists()


def test_config_app_init_creates_app_wide_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    kit = build_storage_free_example_kit()
    app = kit.typer_app(state_type=StorageFreeExampleConfigState)

    result = CliRunner().invoke(app, ["app", "init"])

    assert result.exit_code == 0, result.output
    assert kit.spec.app_wide_env_path().is_file()
    assert "app_wide_env:" in result.output


def test_config_storage_add_list_and_remove(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    index_path = tmp_path / "config" / "demo.apprc.toml"
    monkeypatch.setenv("APPRC_EXAMPLE_APP_APPRC_TOML", str(index_path))
    kit = build_apprc_example_app_kit()
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()
    storage_root = tmp_path / "alpha"

    add = runner.invoke(
        app,
        ["storage", "add", "alpha", str(storage_root), "--yes"],
    )
    listed = runner.invoke(app, ["storage", "list", "--json"])
    removed = runner.invoke(app, ["storage", "remove", "alpha"])
    listed_after = runner.invoke(app, ["storage", "list", "--json"])

    assert add.exit_code == 0, add.output
    assert index_path.is_file()
    assert (storage_root / ".env.apprc-storage").is_file()
    assert json.loads(listed.output)["storages"][0]["name"] == "alpha"
    assert removed.exit_code == 0, removed.output
    assert json.loads(listed_after.output)["storages"] == []


def test_config_set_infers_storage_scope(tmp_path: Path) -> None:
    kit = build_apprc_example_app_kit()
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    state = apprc_example_app_state(kit, storage_root)
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)

    result = CliRunner().invoke(
        app,
        ["set", "app.profile", "storage-profile"],
        obj=state,
    )

    assert result.exit_code == 0, result.output
    assert 'APPRC_EXAMPLE_APP_PROFILE="storage-profile"\n' in (
        storage_root / ".env.apprc-storage"
    ).read_text(encoding="utf-8")
    assert "storage_env:" in result.output


def test_config_set_requires_scope_when_app_and_storage_are_active(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    kit = build_apprc_example_app_kit()
    kit.spec.ensure_app_wide_env()
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    state = apprc_example_app_state(kit, storage_root)
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()

    ambiguous = runner.invoke(
        app,
        ["set", "app.profile", "ambiguous"],
        obj=state,
    )
    app_scoped = runner.invoke(
        app,
        ["set", "app.profile", "app-profile", "--scope", "app"],
        obj=state,
    )

    assert ambiguous.exit_code != 0
    assert "--scope app or --scope storage" in ambiguous.output
    assert app_scoped.exit_code == 0, app_scoped.output
    assert 'APPRC_EXAMPLE_APP_PROFILE="app-profile"\n' in (
        kit.spec.app_wide_env_path().read_text(encoding="utf-8")
    )


def test_config_setup_storage_only_writes_only_storage_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    kit = build_apprc_example_app_kit()
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    storage_root = tmp_path / "storage"

    result = CliRunner().invoke(
        app,
        ["setup", "--yes", "--storage-root", str(storage_root)],
    )

    assert result.exit_code == 0, result.output
    assert (storage_root / ".env.apprc-storage").is_file()
    assert not kit.spec.app_wide_env_path().exists()
    assert not kit.spec.index_path().exists()
