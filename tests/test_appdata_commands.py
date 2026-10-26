from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

import apprc as rc
from apprc.user_files.env_files.secrets import secret_companion_path
from apprc.user_files.storage_roots.model import StorageRecord, StorageRegistry
from apprc.user_files.storage_roots.registry import (
    register_storage,
    write_storage_registry,
)


def _app(*, storage: bool = True) -> tuple[typer.Typer, rc.AppRC]:
    declaration = rc.AppRC(
        app_id="appdata-test",
        user_dotenv=rc.UserDotenv(),
        storage=rc.Storage() if storage else None,
    )
    app = typer.Typer()
    rc.cli.mount_appdata_cli(app, declaration)
    return app, declaration


def test_paths_json_reports_exact_plan_inventory(tmp_path: Path) -> None:
    app, _ = _app()
    apprc_dir = tmp_path / "apprc"
    (apprc_dir / "apprc.user.env").parent.mkdir()
    (apprc_dir / "apprc.user.env").write_text("VALUE=1\n", encoding="utf-8")

    result = CliRunner().invoke(
        app, ["appdata", "paths", "--apprc-dir", str(apprc_dir), "--json"]
    )

    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload == {
        "apprc_dir": str(apprc_dir),
        "managed_files": [
            str(apprc_dir / "apprc.user.env"),
            str(secret_companion_path(apprc_dir / "apprc.user.env")),
            str(apprc_dir / "apprc.toml"),
        ],
        "internal_storage_roots": [],
        "external_storage_roots": [],
        "stale_storage": False,
        "stale_user_dotenv": False,
    }
    assert (apprc_dir / "apprc.user.env").is_file()


def test_paths_json_does_not_create_a_missing_directory(tmp_path: Path) -> None:
    app, _ = _app()
    apprc_dir = tmp_path / "absent"

    result = CliRunner().invoke(
        app, ["appdata", "paths", "--json", "--apprc-dir", str(apprc_dir)]
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["apprc_dir"] == str(apprc_dir)
    assert not apprc_dir.exists()


@pytest.mark.parametrize(
    ("confirmation_args", "confirmation_input"),
    [([], "y\n"), (["--yes"], "")],
)
def test_cleanup_preview_decline_and_confirmation_preserve_scope(
    tmp_path: Path,
    confirmation_args: list[str],
    confirmation_input: str,
) -> None:
    apprc_dir = tmp_path / "apprc"
    declaration = rc.AppRC(
        app_id="appdata-clean",
        user_dotenv=rc.UserDotenv(),
        storage=rc.Storage(),
        apprc_dir=apprc_dir,
    )
    manager = declaration.manage(environment={})
    internal = apprc_dir / "storage"
    external = tmp_path / "external"
    manager.setup(storage_root=internal)
    register_storage(
        name="external",
        root=external,
        path=apprc_dir / "apprc.toml",
    )
    user_secret = manager.writable_path("user", secret=True)
    storage_secret = manager.writable_path("storage", secret=True)
    user_secret.write_text(
        "APPDATA_PRIVATE_TOKEN=secret-value\n",
        encoding="utf-8",
    )
    storage_secret.write_text(
        "APPDATA_STORAGE_PRIVATE_TOKEN=storage-secret\n", encoding="utf-8"
    )
    internal_payload = internal / "payload.txt"
    external_payload = external / "payload.txt"
    internal_payload.write_text("internal", encoding="utf-8")
    external_payload.write_text("external", encoding="utf-8")
    unmanaged = apprc_dir / "keep.txt"
    unmanaged.write_text("keep", encoding="utf-8")
    registry = apprc_dir / "apprc.toml"
    app = typer.Typer()
    rc.cli.mount_appdata_cli(app, declaration)
    runner = CliRunner()

    inventory_result = runner.invoke(app, ["appdata", "paths", "--json"])
    assert inventory_result.exit_code == 0, inventory_result.output
    inventory = json.loads(inventory_result.stdout)
    assert inventory_result.stderr == ""
    assert inventory["internal_storage_roots"] == [str(internal)]
    assert inventory["external_storage_roots"] == [str(external)]
    assert str(user_secret) in inventory["managed_files"]
    assert str(storage_secret) in inventory["managed_files"]

    dry_run = runner.invoke(app, ["appdata", "clean", "--dry-run"])
    declined = runner.invoke(app, ["appdata", "clean"], input="n\n")
    assert dry_run.exit_code == 0, dry_run.output
    assert declined.exit_code == 1
    assert internal_payload.read_text(encoding="utf-8") == "internal"
    assert external_payload.read_text(encoding="utf-8") == "external"
    assert user_secret.read_text(encoding="utf-8").endswith("secret-value\n")
    assert storage_secret.read_text(encoding="utf-8").endswith("storage-secret\n")
    assert (external / "apprc.storage.env").is_file()
    assert registry.is_file()
    assert unmanaged.read_text(encoding="utf-8") == "keep"

    result = runner.invoke(
        app,
        ["appdata", "clean", *confirmation_args],
        input=confirmation_input,
    )

    assert result.exit_code == 0, result.output
    assert not internal.exists()
    assert not user_secret.exists()
    assert not storage_secret.exists()
    assert not (external / "apprc.storage.env").exists()
    assert external_payload.read_text(encoding="utf-8") == "external"
    assert registry.exists() is False
    assert unmanaged.read_text(encoding="utf-8") == "keep"
    assert "secret-value" not in result.output
    assert "storage-secret" not in result.output


def test_explicit_apprc_dir_overrides_process_and_root_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    declaration = rc.AppRC(app_id="appdata-env", user_dotenv=rc.UserDotenv())
    process_selected = tmp_path / "process-selected"
    root_env_selected = tmp_path / "env-file-selected"
    explicit_selected = tmp_path / "explicit-selected"
    env_key = declaration.schema.apprc_dir_env_key
    monkeypatch.setenv(env_key, str(process_selected))
    env_file = tmp_path / "deployment.env"
    env_file.write_text(
        f'{env_key}="{root_env_selected}"\n', encoding="utf-8"
    )
    sentinels = {
        directory: directory / "apprc.user.env"
        for directory in (process_selected, root_env_selected, explicit_selected)
    }
    for sentinel in sentinels.values():
        sentinel.parent.mkdir()
        sentinel.write_text("VALUE=keep\n", encoding="utf-8")
    app = typer.Typer()
    rc.cli.mount_config_cli(
        app,
        declaration,
        runtime_policy=rc.cli.CliRuntimePolicy(
            runtime_independent_commands={
                "appdata": rc.cli.RuntimeIndependentCommand(
                    action_prefixes={("paths",), ("clean",)},
                    skip_empty=True,
                ),
            },
        ),
    )
    rc.cli.mount_appdata_cli(app, declaration)
    runner = CliRunner()

    default_paths = runner.invoke(
        app,
        ["--env-file", str(env_file), "appdata", "paths", "--json"],
    )
    assert default_paths.exit_code == 0, default_paths.output
    assert json.loads(default_paths.stdout)["apprc_dir"] == str(process_selected)

    paths = runner.invoke(
        app,
        [
            "--env-file",
            str(env_file),
            "appdata",
            "paths",
            "--json",
            "--apprc-dir",
            str(explicit_selected),
        ],
    )
    clean = runner.invoke(
        app,
        [
            "--env-file",
            str(env_file),
            "appdata",
            "clean",
            "--yes",
            "--apprc-dir",
            str(explicit_selected),
        ],
    )

    assert paths.exit_code == 0, paths.output
    path_inventory = json.loads(paths.stdout)
    assert path_inventory["apprc_dir"] == str(explicit_selected)
    assert str(sentinels[explicit_selected]) in path_inventory["managed_files"]
    assert clean.exit_code == 0, clean.output
    assert not sentinels[explicit_selected].exists()
    assert sentinels[process_selected].read_text(encoding="utf-8") == (
        "VALUE=keep\n"
    )
    assert sentinels[root_env_selected].read_text(encoding="utf-8") == (
        "VALUE=keep\n"
    )


@pytest.mark.parametrize(
    ("action_args", "error_hint"),
    [
        (["paths", "--json"], "appdata paths"),
        (["clean", "--yes"], "appdata clean"),
    ],
)
def test_malformed_registry_fails_before_managed_file_deletion(
    tmp_path: Path,
    action_args: list[str],
    error_hint: str,
) -> None:
    app, _ = _app()
    apprc_dir = tmp_path / "apprc"
    managed = apprc_dir / "apprc.user.env"
    managed.parent.mkdir()
    managed.write_text("VALUE=1\n", encoding="utf-8")
    (apprc_dir / "apprc.toml").write_text("[invalid", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        ["appdata", *action_args, "--apprc-dir", str(apprc_dir)],
    )

    assert result.exit_code != 0
    assert error_hint in result.output
    assert managed.read_text(encoding="utf-8") == "VALUE=1\n"


def test_mount_preserves_host_callback_and_rejects_collision() -> None:
    _, declaration = _app()
    app = typer.Typer()
    callback_calls: list[bool] = []

    @app.callback()
    def host_callback() -> None:
        callback_calls.append(True)

    mounted = rc.cli.mount_appdata_cli(app, declaration)
    result = CliRunner().invoke(app, ["appdata", "paths", "--json"])
    assert isinstance(mounted, typer.Typer)
    assert result.exit_code == 0, result.output
    assert callback_calls == [True]

    colliding = typer.Typer()
    existing_group = typer.Typer()

    @existing_group.command("preserve")
    def preserve_group() -> None:
        typer.echo("existing group command")

    colliding.add_typer(existing_group, name="appdata")
    with pytest.raises(RuntimeError, match="already has a command or group"):
        rc.cli.mount_appdata_cli(colliding, declaration)
    group_result = CliRunner().invoke(colliding, ["appdata", "preserve"])
    assert group_result.exit_code == 0, group_result.output
    assert group_result.stdout.strip() == "existing group command"

    implicit_command_app = typer.Typer()

    @implicit_command_app.command()
    def appdata() -> None:
        typer.echo("existing command")

    @implicit_command_app.command("other")
    def other() -> None:
        typer.echo("other command")

    with pytest.raises(RuntimeError, match="already has a command or group"):
        rc.cli.mount_appdata_cli(implicit_command_app, declaration)
    command_result = CliRunner().invoke(implicit_command_app, ["appdata"])
    assert command_result.exit_code == 0, command_result.output
    assert command_result.stdout.strip() == "existing command"


def test_paths_reports_stale_registry_and_internal_roots(tmp_path: Path) -> None:
    app, _ = _app(storage=False)
    apprc_dir = tmp_path / "apprc"
    storage = apprc_dir / "storage"
    storage.mkdir(parents=True)
    write_storage_registry(
        StorageRegistry(
            path=apprc_dir / "apprc.toml",
            storages={"old": StorageRecord(name="old", root=storage)},
            selected_storage="old",
        )
    )
    result = CliRunner().invoke(
        app, ["appdata", "paths", "--json", "--apprc-dir", str(apprc_dir)]
    )
    assert result.exit_code == 0, result.output
    assert result.stderr
    payload = json.loads(result.stdout)
    assert payload["stale_storage"] is True
    assert payload["internal_storage_roots"] == [str(storage)]
    assert "stale storage configuration" in result.stderr


def test_paths_reports_stale_user_dotenv(tmp_path: Path) -> None:
    declaration = rc.AppRC(app_id="appdata-stale")
    apprc_dir = tmp_path / "apprc"
    user_dotenv = apprc_dir / "apprc.user.env"
    user_dotenv.parent.mkdir()
    user_dotenv.write_text("VALUE=1\n", encoding="utf-8")
    app = typer.Typer()
    rc.cli.mount_appdata_cli(app, declaration)

    result = CliRunner().invoke(
        app, ["appdata", "paths", "--json", "--apprc-dir", str(apprc_dir)]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["stale_user_dotenv"] is True
    assert "apprc.user.env exists" in result.stderr
