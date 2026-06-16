from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from apprc.config.registry_loading import load_existing_registry
from apprc.config.storage.registry import (
    load_storage_registry_or_empty,
    suggested_storage_root,
)
from tests.support_config import (
    ApprcExampleAppConfigState,
    build_apprc_example_app_kit,
    register_storage_for_kit,
    set_apprc_example_app_apprc_toml,
)

pytestmark = [pytest.mark.requires_apprc_env("APPRC_EXAMPLE_APP")]


def test_generated_config_setup_creates_single_storage_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("APPRC_EXAMPLE_APP_APPRC_TOML", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    kit = build_apprc_example_app_kit()
    monkeypatch.setenv(
        "APPRC_EXAMPLE_APP_STORAGE",
        str(suggested_storage_root(kit.spec.app_name)),
    )
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()

    result = runner.invoke(app, ["setup", "--yes"])

    storage_root = (
        tmp_path / "data" / "apprc_example_app" / "apprc_example_app_stor-1"
    )
    assert result.exit_code == 0, result.output
    assert kit.spec.optional_apprc_toml_path() is None
    assert "APPRC_EXAMPLE_APP_STORAGE" not in (
        storage_root / ".env.apprc_example_app"
    ).read_text(encoding="utf-8")
    assert "export APPRC_EXAMPLE_APP_APPRC_TOML" not in result.output
    assert (
        f'export APPRC_EXAMPLE_APP_STORAGE="{storage_root.resolve()}"'
        in result.output
    )
    assert "APPRC_EXAMPLE_APP_APPRC_TOML=" not in result.output
    assert (
        f'APPRC_EXAMPLE_APP_STORAGE="{storage_root.resolve()}"' in result.output
    )
    assert "Example App setup files are ready." in result.output
    assert "Add these to your environment:" in result.output
    assert "Shell:" in result.output
    assert "Or Dotenv:" in result.output
    assert "Without APPRC_EXAMPLE_APP_STORAGE" in result.output
    assert "apprc_example_app config edit" in result.output
    assert "apprc_example_app config show" in result.output
    assert "apprc_example_app config doctor" in result.output


@pytest.mark.allow_missing_apprc_env
def test_generated_config_setup_accepts_apprc_dir_without_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    kit = build_apprc_example_app_kit()
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()
    custom_dir = tmp_path / "custom"
    custom_registry = custom_dir / "apprc_example_app.apprc.toml"
    storage_root = tmp_path / "storage"

    result = runner.invoke(
        app,
        [
            "setup",
            "--yes",
            "-d",
            str(custom_dir),
            "--storage-root",
            str(storage_root),
            "--multi-storage",
        ],
    )

    registry = load_storage_registry_or_empty(custom_registry)
    assert result.exit_code == 0, result.output
    assert registry.path == custom_registry
    assert custom_registry.is_file()
    assert (
        f'export APPRC_EXAMPLE_APP_APPRC_TOML="{custom_registry}"'
        in result.output
    )
    assert (
        f'export APPRC_EXAMPLE_APP_STORAGE="{storage_root.resolve()}"'
        in result.output
    )
    assert f'APPRC_EXAMPLE_APP_APPRC_TOML="{custom_registry}"' in result.output
    assert (
        f'APPRC_EXAMPLE_APP_STORAGE="{storage_root.resolve()}"' in result.output
    )
    assert kit.spec.optional_apprc_toml_path() is None


def test_generated_config_setup_accepts_apprc_dir_env_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    other_registry = tmp_path / "other.toml"
    monkeypatch.setenv(
        "APPRC_EXAMPLE_APP_APPRC_TOML",
        str(other_registry),
    )
    kit = build_apprc_example_app_kit()
    monkeypatch.setenv(
        "APPRC_EXAMPLE_APP_STORAGE",
        str(suggested_storage_root(kit.spec.app_name)),
    )
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()
    custom_dir = tmp_path / "custom"
    custom_registry = custom_dir / "apprc_example_app.apprc.toml"

    result = runner.invoke(
        app,
        ["setup", "--yes", "--apprc-dir", str(custom_dir), "--multi-storage"],
    )

    registry = load_storage_registry_or_empty(custom_registry)
    assert result.exit_code == 0, result.output
    assert registry.path == custom_registry
    assert custom_registry.is_file()
    assert not other_registry.exists()
    assert (
        f'export APPRC_EXAMPLE_APP_APPRC_TOML="{custom_registry}"'
        in result.output
    )


def test_generated_config_setup_accepts_matching_custom_registry_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    custom_registry = tmp_path / "custom" / "apprc_example_app.apprc.toml"
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("APPRC_EXAMPLE_APP_APPRC_TOML", str(custom_registry))
    kit = build_apprc_example_app_kit()
    monkeypatch.setenv(
        "APPRC_EXAMPLE_APP_STORAGE",
        str(suggested_storage_root(kit.spec.app_name)),
    )
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()

    result = runner.invoke(app, ["setup", "--yes", "--multi-storage"])

    registry = load_existing_registry(kit.spec)
    assert result.exit_code == 0, result.output
    assert registry.path == custom_registry
    assert custom_registry.is_file()
    assert "export APPRC_EXAMPLE_APP_APPRC_TOML" in result.output


def test_generated_config_setup_accepts_custom_multi_storage_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    storage_root = tmp_path / "custom-storage"
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    monkeypatch.setenv(
        "APPRC_EXAMPLE_APP_STORAGE",
        str(storage_root.resolve()),
    )
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "setup",
            "--yes",
            "--storage-root",
            str(storage_root),
            "--multi-storage",
            "--name",
            "alpha",
        ],
    )

    registry = load_existing_registry(kit.spec)
    assert result.exit_code == 0, result.output
    assert registry.selected("alpha").root == storage_root.resolve()
    assert (storage_root / ".env.apprc_example_app").is_file()
    assert (
        f'export APPRC_EXAMPLE_APP_STORAGE="{storage_root.resolve()}"'
        in result.output
    )


def test_generated_config_setup_options_require_yes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()
    storage_root = tmp_path / "custom-storage"
    storage_root.mkdir()
    (storage_root / "payload.txt").write_text("demo", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "setup",
            "--storage-root",
            str(storage_root),
            "--name",
            "alpha",
        ],
    )

    assert result.exit_code == 2, result.output
    assert "Setup options run non-interactively" in result.output
    assert not kit.spec.required_apprc_toml_path().exists()


def test_generated_config_setup_name_requires_multi_storage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "setup",
            "--yes",
            "--storage-root",
            str(tmp_path / "storage"),
            "--name",
            "alpha",
        ],
    )

    assert result.exit_code == 2, result.output
    assert "--name is only used with --multi-storage" in result.output
    assert not kit.spec.required_apprc_toml_path().exists()


@pytest.mark.allow_missing_apprc_env
def test_generated_config_setup_rejects_apprc_dir_that_is_file(
    tmp_path: Path,
) -> None:
    kit = build_apprc_example_app_kit()
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()
    file_path = tmp_path / "not-a-directory"
    file_path.write_text("payload", encoding="utf-8")

    result = runner.invoke(
        app,
        ["setup", "--yes", "--apprc-dir", str(file_path), "--multi-storage"],
    )

    assert result.exit_code == 2, result.output
    assert "APPRC_DIR" in result.output
    assert "AppRC directory is not a directory" in result.output


def test_generated_config_setup_keeps_existing_registry_rows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    storage_root = tmp_path / "alpha"
    register_storage_for_kit(kit, name="alpha", root=storage_root)
    monkeypatch.setenv(
        "APPRC_EXAMPLE_APP_STORAGE",
        str(storage_root.resolve()),
    )
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()

    result = runner.invoke(app, ["setup", "--yes"])

    registry = load_existing_registry(kit.spec)
    assert result.exit_code == 0, result.output
    assert registry.selected("alpha").root == storage_root.resolve()
    assert "Example App setup files are ready." in result.output
    assert (
        f'export APPRC_EXAMPLE_APP_STORAGE="{storage_root.resolve()}"'
        in result.output
    )
    assert f'APPRC_EXAMPLE_APP_STORAGE="{storage_root.resolve()}"' in (
        result.output
    )


def test_generated_config_setup_reset_orphans_registered_storage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    kit = build_apprc_example_app_kit()
    monkeypatch.setenv(
        "APPRC_EXAMPLE_APP_STORAGE",
        str(suggested_storage_root(kit.spec.app_name)),
    )
    old_storage_root = tmp_path / "alpha"
    register_storage_for_kit(kit, name="alpha", root=old_storage_root)
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["setup", "--yes", "--existing-action", "reset", "--multi-storage"],
    )

    new_storage_root = (
        tmp_path / "data" / "apprc_example_app" / "apprc_example_app_stor-1"
    )
    registry = load_existing_registry(kit.spec)
    assert result.exit_code == 0, result.output
    assert old_storage_root.is_dir()
    assert registry.selected("apprc_example_app_stor-1").root == (
        new_storage_root.resolve()
    )
    assert (new_storage_root / ".env.apprc_example_app").is_file()
    assert "Example App setup files are ready." in result.output
    assert (
        f'APPRC_EXAMPLE_APP_STORAGE="{new_storage_root.resolve()}"'
        in result.output
    )


def test_generated_config_setup_moves_existing_registry_to_apprc_dir_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    storage_root = tmp_path / "alpha"
    register_storage_for_kit(kit, name="alpha", root=storage_root)
    monkeypatch.setenv(
        "APPRC_EXAMPLE_APP_STORAGE",
        str(storage_root.resolve()),
    )
    original_registry = kit.spec.required_apprc_toml_path()
    custom_dir = tmp_path / "custom"
    custom_registry = custom_dir / "apprc_example_app.apprc.toml"
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "setup",
            "--yes",
            "--apprc-dir",
            str(custom_dir),
            "--existing-action",
            "move",
            "--multi-storage",
        ],
    )

    registry = load_storage_registry_or_empty(custom_registry)
    assert result.exit_code == 0, result.output
    assert not original_registry.exists()
    assert custom_registry.is_file()
    assert registry.selected("alpha").root == storage_root.resolve()
    assert (
        f'export APPRC_EXAMPLE_APP_APPRC_TOML="{custom_registry}"'
        in result.output
    )
