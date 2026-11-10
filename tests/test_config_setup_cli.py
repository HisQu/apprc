from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

import apprc as rc
from apprc.definition.paths import Layout, Paths
from apprc.interfaces.cli import setup_command
from apprc.interfaces.cli.mount import mount_app_cli
from apprc.user_files.app_home.application import AppFiles
from apprc.user_files.setup.flow import ConfigSetupError


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


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory mode check")
def test_setup_repairs_only_an_unsafe_secret_parent_after_consent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_rc = _app(tmp_path)
    manager = app_rc.manage(environment={})
    manager.setup()
    config_dir = app_rc.paths(environment={}).require("config")
    config_dir.chmod(0o755)
    monkeypatch.setattr(setup_command.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(setup_command.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(
        setup_command.typer, "confirm", lambda *args, **kwargs: True
    )

    result = setup_command._run_setup_with_user_secret_repair(
        manager,
        assume_yes=False,
        allow_interactive_secret_repair=False,
        adopt=False,
    )

    assert result.user_dotenv.is_file()
    assert config_dir.stat().st_mode & 0o777 == 0o700


def test_setup_does_not_repair_blocked_secret_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_rc = _app(tmp_path)
    config_dir = app_rc.paths(environment={}).require("config")
    config_dir.parent.mkdir(parents=True)
    config_dir.write_text("blocking file", encoding="utf-8")
    manager = app_rc.manage(environment={})
    monkeypatch.setattr(setup_command.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(setup_command.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(
        setup_command.typer, "confirm", lambda *args, **kwargs: True
    )
    monkeypatch.setattr(
        manager,
        "repair_secret_permissions",
        lambda *args, **kwargs: pytest.fail("blocked paths are not repairable"),
    )

    with pytest.raises(ConfigSetupError):
        setup_command._run_setup_with_user_secret_repair(
            manager,
            assume_yes=False,
            allow_interactive_secret_repair=False,
            adopt=False,
        )

    assert config_dir.is_file()


def test_setup_prompts_for_missing_field_despite_changed_display_prose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_rc = _app(tmp_path)
    manager = app_rc.manage(environment={})
    manager.setup()
    original_inspect = manager.inspect

    def inspect_with_changed_prose(*args, **kwargs):
        inspection = original_inspect(*args, **kwargs)
        item = inspection.fields[0]
        return replace(
            inspection,
            fields=(
                replace(item, issue="Rephrased display text."),
                *inspection.fields[1:],
            ),
        )

    monkeypatch.setattr(manager, "inspect", inspect_with_changed_prose)
    monkeypatch.setattr(
        setup_command, "prompt", lambda *args, **kwargs: "saved"
    )

    setup_command._prompt_required_fields(manager)

    assert manager.inspect().fields[0].value == "saved"


def test_setup_does_not_prompt_for_invalid_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_rc = _app(tmp_path)
    manager = app_rc.manage(environment={})
    manager.setup()
    original_inspect = manager.inspect

    def inspect_as_invalid(*args, **kwargs):
        inspection = original_inspect(*args, **kwargs)
        item = inspection.fields[0]
        return replace(
            inspection,
            fields=(replace(item, reason="invalid"), *inspection.fields[1:]),
        )

    monkeypatch.setattr(manager, "inspect", inspect_as_invalid)

    def fail_prompt(*args, **kwargs):
        pytest.fail("invalid fields must not be prompted as missing")

    monkeypatch.setattr(setup_command, "prompt", fail_prompt)

    setup_command._prompt_required_fields(manager)
