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
        "prompt_toolkit.prompt", lambda *args, **kwargs: "saved"
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

    monkeypatch.setattr("prompt_toolkit.prompt", fail_prompt)

    setup_command._prompt_required_fields(manager)


@pytest.mark.parametrize("maintenance_group", ["app", "manage"])
def test_setup_guidance_uses_mounted_verification_commands(
    tmp_path: Path, maintenance_group: str
) -> None:
    """The wizard's suggested commands resolve in the actual host CLI."""
    import shlex

    app_rc = rc.AppRC(
        app_id="wizard-demo",
        command_name="demo",
        paths=Paths(config=True),
        layout=Layout.single_root(tmp_path / "home"),
        user_dotenv=rc.UserDotenv(),
    )
    app = typer.Typer()
    mount_app_cli(app, app_rc, maintenance_group_name=maintenance_group)
    runner = CliRunner()
    result = runner.invoke(app, ["config", "setup", "--yes"])
    assert result.exit_code == 0, result.output
    guidance = result.output.split("Then verify:\n", 1)[1]
    commands = [
        shlex.split(line) for line in guidance.splitlines() if line.strip()
    ]
    assert commands == [
        ["demo", maintenance_group, "paths", "--json"],
        ["demo", maintenance_group, "doctor", "--json"],
    ]
    for _executable, *arguments in commands:
        verified = runner.invoke(app, arguments)
        assert verified.exit_code in {0, 1}, verified.output
        assert "No such command" not in verified.output
        assert "status" in verified.output or "paths" in verified.output


@pytest.mark.parametrize(
    "scenario",
    [
        "noninteractive",
        "assume-yes",
        "supplied",
        "environment",
        "no-fields",
        "default",
        "inactive",
        "workspace",
        "noneditable",
        "invalid",
        "no-scope",
    ],
)
def test_optional_setup_skips_without_applicable_missing_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    scenario: str,
) -> None:
    """The installation offer uses effective field state, not config capability."""
    import sys

    app_rc = _app(tmp_path)
    if scenario in {"no-fields", "default"}:
        app_rc = rc.AppRC(
            app_id="optional-setup",
            paths=Paths(config=True),
            layout=Layout.single_root(tmp_path / "optional"),
            user_dotenv=rc.UserDotenv(),
        )
        if scenario == "default":

            @app_rc.config("settings", prefix="OPTIONAL_SETUP_")
            class Settings(rc.Config):
                value: str = rc.field(
                    "OPTIONAL_SETUP_VALUE", default="provided"
                )

    manager = app_rc.manage(environment={})
    if scenario != "no-scope":
        manager.setup()
    if scenario == "environment":
        item = manager.inspect().fields[0]
        manager = app_rc.manage(
            environment={
                item.owner.env_key(item.field.name): "from-environment"
            }
        )
    if scenario == "supplied":
        item = manager.inspect().fields[0]
        manager.apply_edit(
            manager.plan_update(
                item.owner.env_key(item.field.name),
                "already-saved",
                scope="user",
            )
        )
    if scenario in {"inactive", "workspace", "noneditable", "invalid"}:
        original = manager.inspect

        def inspect(*args, **kwargs):
            result = original(*args, **kwargs)
            item = result.fields[0]
            if scenario == "inactive":
                item = replace(item, active=False)
            elif scenario == "workspace":
                item = replace(
                    item, owner=replace(item.owner, requires_workspace=True)
                )
            elif scenario == "noneditable":
                item = replace(item, field=replace(item.field, editable=False))
            else:
                item = replace(item, reason="invalid")
            return replace(result, fields=(item,))

        monkeypatch.setattr(manager, "inspect", inspect)
    monkeypatch.setattr(
        sys.stdin, "isatty", lambda: scenario != "noninteractive"
    )

    def unexpected(*args, **kwargs):
        pytest.fail("Optional setup must not prompt or initialize")

    monkeypatch.setattr(typer, "confirm", unexpected)
    monkeypatch.setattr(manager, "setup", unexpected)
    setup_command.run_config_setup(
        app_rc,
        manager=manager,
        offer_missing=True,
        assume_yes=scenario == "assume-yes",
    )
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("accept", [False, True])
def test_optional_setup_offers_and_saves_missing_required_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    accept: bool,
) -> None:
    """Accepted offers reuse normal validation and secret persistence."""
    import sys

    app_rc = _app(tmp_path)
    manager = app_rc.manage(environment={})
    manager.setup()
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    offers: list[str] = []

    def confirm(message, **kwargs):
        offers.append(message)
        assert kwargs["default"] is False
        return accept

    prompts: list[bool] = []

    def prompt(*args, **kwargs):
        prompts.append(kwargs["is_password"])
        return "saved-secret"

    monkeypatch.setattr(typer, "confirm", confirm)
    monkeypatch.setattr("prompt_toolkit.prompt", prompt)
    setup_command.run_config_setup(app_rc, manager=manager, offer_missing=True)
    assert "saved-secret" not in capsys.readouterr().out
    assert len(offers) == 1
    assert prompts == ([True] if accept else [])
    assert manager.inspect().fields[0].value == (
        "saved-secret" if accept else None
    )


def test_setup_completion_and_known_paths_use_semantic_colors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    app_rc = _app(tmp_path)
    app = typer.Typer(context_settings={"color": True})
    mount_app_cli(app, app_rc)
    result = CliRunner().invoke(app, ["config", "setup", "--yes"], color=True)
    assert result.exit_code == 0, result.output
    assert (
        "\x1b[32m" in result.stdout and "AppRC setup complete." in result.stdout
    )
    assert (
        f"\x1b[36m{app_rc.paths(environment={}).require('config')}"
        in result.stdout
    )
