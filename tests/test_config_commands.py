from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

import apprc as rc
from apprc.definition.paths import Layout, Paths
from apprc.interfaces.cli.mount import mount_app_cli
from apprc.user_files.app_home.application import AppFiles


def _root_cli(app_rc: rc.AppRC) -> tuple[typer.Typer, dict[str, typer.Typer]]:
    app = typer.Typer()
    groups = mount_app_cli(app, app_rc)
    return app, groups


def test_root_paths_is_zero_write_and_uses_captured_config_location(
    tmp_path: Path,
) -> None:
    kit = rc.AppRC(
        app_id="read_only_paths",
        paths=Paths(config=True),
        layout=Layout.single_root(tmp_path / "home"),
        user_dotenv=rc.UserDotenv(),
    )
    app, groups = _root_cli(kit)

    result = CliRunner().invoke(app, ["paths", "--json"])

    assert result.exit_code == 0, result.output
    assert set(groups) >= {"config"}
    payload = json.loads(result.output)
    config_dir = kit.paths(environment={}).require("config")
    assert payload["paths"]["config"] == str(config_dir)
    assert payload["exists"]["config"] is False
    assert not config_dir.exists()


def test_config_setup_and_edit_are_persisted_and_reload(tmp_path: Path) -> None:
    kit = rc.AppRC(
        app_id="saved_config",
        paths=Paths(config=True),
        layout=Layout.single_root(tmp_path / "home"),
        user_dotenv=rc.UserDotenv(),
    )

    @kit.config("global", prefix="SAVED_CONFIG_")
    class Settings(rc.Config):
        profile: str = rc.field("SAVED_CONFIG_PROFILE", default="default")

    app, _ = _root_cli(kit)
    runner = CliRunner()
    setup = runner.invoke(app, ["config", "setup", "--yes"])
    update = runner.invoke(
        app,
        ["config", "set", "global.profile", "local", "--scope", "user"],
    )

    assert setup.exit_code == 0, setup.output
    assert update.exit_code == 0, update.output
    assert (
        kit.resolve(environment={}).source.values["SAVED_CONFIG_PROFILE"]
        == "local"
    )
    assert (tmp_path / "home" / "config" / "apprc.user.env").read_text(
        encoding="utf-8"
    ) == 'SAVED_CONFIG_PROFILE="local"\n'


def test_workspace_lifecycle_is_root_group_and_config_setup_does_not_initialize_it(
    tmp_path: Path,
) -> None:
    kit = rc.AppRC(
        app_id="workspace_commands",
        paths=Paths(config=True),
        layout=Layout.single_root(tmp_path / "home"),
        user_dotenv=rc.UserDotenv(),
        workspaces=rc.Workspaces(),
    )
    app, groups = _root_cli(kit)
    runner = CliRunner()
    setup = runner.invoke(app, ["config", "setup", "--yes"])
    root = tmp_path / "workspace"
    assert setup.exit_code == 0, setup.output
    assert not root.exists()
    add = runner.invoke(app, ["workspace", "add", "work", str(root)])
    listing = runner.invoke(app, ["workspace", "list", "--json"])

    assert "workspace" in groups
    assert add.exit_code == 0, add.output
    assert (root / "apprc.workspace.env").is_file()
    assert listing.exit_code == 0, listing.output
    payload = json.loads(listing.output)
    assert payload["registry"]["selected_workspace"] == "work"
    assert payload["registry"]["workspaces"] == [
        {"name": "work", "root": str(root.resolve())}
    ]


def test_workspace_registration_owns_config_and_purge_preserves_workspace(
    tmp_path: Path,
) -> None:
    kit = rc.AppRC(
        app_id="workspace_owned_config",
        paths=Paths(config=True),
        layout=Layout.single_root(tmp_path / "home"),
        workspaces=rc.Workspaces(),
    )
    manager = kit.workspaces(environment={})
    config = kit.paths(environment={}).require("config")
    root = tmp_path / "workspace"
    root.mkdir()
    data = root / "data.txt"
    data.write_text("external workspace data", encoding="utf-8")
    assert not config.exists()

    registry = manager.register_workspace("work", root)

    assert registry.workspaces["work"].root == root
    assert manager.registry().selected_workspace == "work"
    assert json.loads(
        (config / ".apprc-owner.json").read_text(encoding="utf-8")
    ) == {
        "schema_version": 1,
        "app_id": "workspace_owned_config",
        "category": "config",
    }
    assert not (config / "apprc.user.env").exists()
    workspace_files = {
        path: path.read_bytes() for path in root.iterdir() if path.is_file()
    }
    maintenance = kit.maintain(environment={})
    plans = maintenance.plan_purge(("config",))
    assert manager.registry_path() in plans[0].targets

    (result,) = maintenance.apply_purge(plans)

    assert manager.registry_path() in result.removed
    assert not config.exists()
    assert data.read_text(encoding="utf-8") == "external workspace data"
    assert {
        path: path.read_bytes() for path in root.iterdir() if path.is_file()
    } == workspace_files


def test_workspace_registration_refuses_nonempty_unowned_config(
    tmp_path: Path,
) -> None:
    kit = rc.AppRC(
        app_id="workspace_unowned_config",
        paths=Paths(config=True),
        layout=Layout.single_root(tmp_path / "home"),
        workspaces=rc.Workspaces(),
    )
    config = kit.paths(environment={}).require("config")
    config.mkdir(parents=True)
    user_file = config / "apprc.user.env"
    user_file.write_text("USER_VALUE=keep\n", encoding="utf-8")
    manager = kit.workspaces(environment={})
    root = tmp_path / "workspace"

    with pytest.raises(ValueError, match="nonempty unowned"):
        manager.register_workspace("work", root)

    assert not manager.registry_path().exists()
    assert not (config / ".apprc-owner.json").exists()
    assert user_file.read_text(encoding="utf-8") == "USER_VALUE=keep\n"
    assert set(config.iterdir()) == {user_file}
    assert not root.exists()



def test_secret_migration_moves_value_to_private_companion(
    tmp_path: Path,
) -> None:
    kit = rc.AppRC(
        app_id="secret_migration",
        paths=Paths(config=True),
        layout=Layout.single_root(tmp_path / "home"),
        user_dotenv=rc.UserDotenv(),
    )

    @kit.config("credentials", prefix="SECRET_MIGRATION_")
    class Credentials(rc.Config):
        token: str = rc.field("SECRET_MIGRATION_TOKEN", secret=True)

    manager = kit.manage(environment={})
    manager.setup()
    files = AppFiles(kit.schema, manager.paths)
    ordinary = files.user_dotenv_path()
    secret = files.user_secret_dotenv_path()
    ordinary.write_text(
        'SECRET_MIGRATION_TOKEN="private-value"\n', encoding="utf-8"
    )
    plan = manager.plan_secret_migration("user")

    assert plan.keys == ("SECRET_MIGRATION_TOKEN",)
    assert "private-value" not in repr(plan)
    manager.apply_secret_migration(plan)

    assert "SECRET_MIGRATION_TOKEN" not in ordinary.read_text(encoding="utf-8")
    assert "SECRET_MIGRATION_TOKEN" in secret.read_text(encoding="utf-8")
    assert "private-value" not in repr(manager.inspect())
    assert (
        manager.resolve().source.values["SECRET_MIGRATION_TOKEN"]
        == "private-value"
    )
