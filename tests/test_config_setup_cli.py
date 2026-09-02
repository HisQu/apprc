from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from apprc.definition.app_config.kit import AppConfigKit
from tests.support_config import (
    ApprcExampleAppConfigState,
    ApprcExampleAppEnv,
    StorageFreeExampleConfigState,
    StorageFreeExampleEnv,
    assert_config_home_cli_error,
    block_config_home_with_file,
    build_apprc_example_app_kit,
    build_storage_free_example_kit,
)


def test_env_only_setup_prints_guidance_without_writes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    kit = AppConfigKit.env_only(
        app_name="env_app",
        display_name="Env App",
        config_package="apprc",
        envs=(StorageFreeExampleEnv,),
    )
    app = kit.typer_app(state_type=StorageFreeExampleConfigState)

    result = CliRunner().invoke(app, ["setup"])

    assert result.exit_code == 0, result.output
    assert "writes: none" in result.output
    assert not kit.spec.app_env_path().exists()
    assert not kit.spec.apprc_toml_path().exists()


def test_storage_setup_creates_storage_env_and_app_selector(
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
    assert (storage_root / "apprc.storage.env").is_file()
    assert kit.spec.app_env_path().is_file()
    assert not kit.spec.apprc_toml_path().exists()
    assert "selector_saved:" in result.output


def test_storage_only_setup_rejects_blank_storage_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    kit = build_apprc_example_app_kit()
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)

    result = CliRunner().invoke(
        app,
        ["setup", "--yes", "--storage-root", ""],
    )

    assert result.exit_code != 0, result.output
    assert "must not be empty" in result.output
    assert not (tmp_path / "apprc.storage.env").exists()


def test_config_only_setup_reports_no_required_writes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    kit = build_storage_free_example_kit()
    app = kit.typer_app(state_type=StorageFreeExampleConfigState)

    result = CliRunner().invoke(app, ["setup"])

    assert result.exit_code == 0, result.output
    assert "writes: none" in result.output
    assert not kit.spec.app_env_path().exists()
    assert not kit.spec.apprc_toml_path().exists()


def test_app_wide_storage_setup_creates_app_and_storage_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    kit = AppConfigKit.app_wide_storage(
        app_name="wide_storage",
        display_name="Wide Storage",
        config_package="apprc",
        envs=(ApprcExampleAppEnv,),
        storage_env_key="WIDE_STORAGE",
    )
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    storage_root = tmp_path / "storage"

    result = CliRunner().invoke(
        app,
        ["setup", "--yes", "--storage-root", str(storage_root)],
    )

    assert result.exit_code == 0, result.output
    assert kit.spec.app_env_path().is_file()
    assert (storage_root / ".env.apprc-storage").is_file()
    assert not kit.spec.apprc_toml_path().exists()


def test_app_wide_storage_setup_reports_config_home_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    kit = AppConfigKit.app_wide_storage(
        app_name="wide_storage",
        display_name="Wide Storage",
        config_package="apprc",
        envs=(ApprcExampleAppEnv,),
        storage_env_key="WIDE_STORAGE",
    )
    block_config_home_with_file(kit)
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)

    storage_root = tmp_path / "storage"
    result = CliRunner().invoke(
        app,
        ["setup", "--yes", "--storage-root", str(storage_root)],
    )

    assert_config_home_cli_error(result)
    assert not storage_root.exists()


def test_failed_setup_preserves_preexisting_storage_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Rollback never removes a storage directory or dotenv it did not make."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    kit = build_apprc_example_app_kit()
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    storage_env = storage_root / "apprc.storage.env"
    storage_env.write_text("KEEP=1\n", encoding="utf-8")
    block_config_home_with_file(kit)
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)

    result = CliRunner().invoke(
        app,
        ["setup", "--yes", "--storage-root", str(storage_root)],
    )

    assert_config_home_cli_error(result)
    assert storage_root.is_dir()
    assert storage_env.read_text(encoding="utf-8") == "KEEP=1\n"


def test_storage_only_can_upgrade_to_app_wide_and_named_storage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    kit = build_apprc_example_app_kit()
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()

    app_init = runner.invoke(app, ["app", "init"])
    storage_add = runner.invoke(
        app,
        ["storage", "add", "alpha", str(tmp_path / "alpha"), "--yes"],
    )

    assert app_init.exit_code == 0, app_init.output
    assert storage_add.exit_code == 0, storage_add.output
    assert kit.spec.app_env_path().is_file()
    assert kit.spec.apprc_toml_path().is_file()
