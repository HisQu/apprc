from __future__ import annotations

import os
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

import apprc as rc
from apprc.definition.paths import Layout, Paths
from apprc.interfaces.cli.mount import mount_app_cli
from apprc.user_files.app_home.application import AppFiles


def _app(tmp_path: Path, *, workspaces: bool = False) -> rc.AppRC:
    app = rc.AppRC(
        app_id="setup_preferences",
        paths=Paths(config=True),
        layout=Layout.single_root(tmp_path / "home"),
        user_dotenv=rc.UserDotenv(),
        workspaces=rc.Workspaces() if workspaces else None,
        setup_next_step="demo run" if workspaces else None,
    )

    @app.config("global", prefix="SETUP_PREFERENCES_")
    class Settings(rc.Config):
        token: str = rc.field(
            "SETUP_PREFERENCES_TOKEN", required=True, secret=True
        )

    return app


def test_setup_initializes_only_user_preferences_without_workspace_prompt(
    tmp_path: Path,
) -> None:
    app_rc = _app(tmp_path, workspaces=True)
    app = typer.Typer()
    groups = mount_app_cli(app, app_rc)
    result = CliRunner().invoke(app, ["config", "setup", "--yes"])
    files = AppFiles(app_rc.schema, app_rc.paths(environment={}))

    assert result.exit_code == 0, result.output
    assert files.user_dotenv_path().is_file()
    assert files.user_secret_dotenv_path().is_file()
    assert "workspace" in groups
    registry = app_rc.workspaces(environment={}).registry()
    assert not registry.workspaces
    assert not (tmp_path / "home" / "workspace").exists()


def test_setup_requires_explicit_adoption_of_existing_unowned_config(
    tmp_path: Path,
) -> None:
    app_rc = _app(tmp_path)
    config_dir = app_rc.paths(environment={}).require("config")
    config_dir.mkdir(parents=True)
    existing = config_dir / "keep.txt"
    existing.write_text("keep", encoding="utf-8")
    app = typer.Typer()
    mount_app_cli(app, app_rc)

    refused = CliRunner().invoke(app, ["config", "setup", "--yes"])
    adopted = CliRunner().invoke(app, ["config", "setup", "--yes", "--adopt"])

    assert refused.exit_code != 0
    assert existing.read_text(encoding="utf-8") == "keep"
    assert adopted.exit_code == 0, adopted.output
    assert existing.read_text(encoding="utf-8") == "keep"
    files = AppFiles(app_rc.schema, app_rc.paths(environment={}))
    assert files.user_dotenv_path().is_file()


def test_setup_rejects_blocking_config_path_without_creating_preferences(
    tmp_path: Path,
) -> None:
    app_rc = _app(tmp_path)
    config_dir = app_rc.paths(environment={}).require("config")
    config_dir.parent.mkdir(parents=True)
    config_dir.write_text("not a directory", encoding="utf-8")
    app = typer.Typer()
    mount_app_cli(app, app_rc)

    result = CliRunner().invoke(app, ["config", "setup", "--yes"])

    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert config_dir.is_file()
    assert not (config_dir.parent / "apprc.user.env").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory mode check")
def test_config_secret_repair_restores_private_directory_permissions(
    tmp_path: Path,
) -> None:
    app_rc = _app(tmp_path)
    config_dir = app_rc.paths(environment={}).require("config")
    app = typer.Typer()
    mount_app_cli(app, app_rc)
    setup = CliRunner().invoke(app, ["config", "setup", "--yes"])
    config_dir.chmod(0o755)

    repaired = CliRunner().invoke(
        app, ["config", "secrets", "repair", "--scope", "user", "--yes"]
    )

    assert setup.exit_code == 0, setup.output
    assert repaired.exit_code == 0, repaired.output
    assert config_dir.stat().st_mode & 0o777 == 0o700
