from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from apprc.runtime_config.kit import AppConfigKit
from tests.support_config import (
    ApprcExampleAppConfigState,
    ApprcExampleAppEnv,
    StorageFreeExampleConfigState,
    StorageFreeExampleEnv,
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
        config_package="apprc.runtime_config",
        envs=(StorageFreeExampleEnv,),
    )
    app = kit.typer_app(state_type=StorageFreeExampleConfigState)

    result = CliRunner().invoke(app, ["setup"])

    assert result.exit_code == 0, result.output
    assert "writes: none" in result.output
    assert not kit.spec.app_wide_env_path().exists()
    assert not kit.spec.index_path().exists()


def test_storage_only_setup_creates_storage_env_only(
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
    assert "export APPRC_EXAMPLE_APP_STORAGE" in result.output


def test_app_wide_config_setup_creates_app_wide_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    kit = build_storage_free_example_kit()
    app = kit.typer_app(state_type=StorageFreeExampleConfigState)

    result = CliRunner().invoke(app, ["setup"])

    assert result.exit_code == 0, result.output
    assert kit.spec.app_wide_env_path().is_file()
    assert not kit.spec.index_path().exists()


def test_app_wide_storage_setup_creates_app_and_storage_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    kit = AppConfigKit.app_wide_storage(
        app_name="wide_storage",
        display_name="Wide Storage",
        config_package="apprc.runtime_config",
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
    assert kit.spec.app_wide_env_path().is_file()
    assert (storage_root / ".env.apprc-storage").is_file()
    assert not kit.spec.index_path().exists()


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
    assert kit.spec.app_wide_env_path().is_file()
    assert kit.spec.index_path().is_file()
