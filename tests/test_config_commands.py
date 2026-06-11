from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apprc.config.diagnostics import (
    build_config_doctor_payload,
    config_setup_message,
)
from tests.support_config import (
    ApprcExampleAppConfigState,
    apprc_example_app_state,
    build_apprc_example_app_kit,
    set_apprc_example_app_apprc_toml,
)

pytestmark = [pytest.mark.requires_apprc_env("APPRC_EXAMPLE_APP")]


def test_generated_config_app_sets_local_values_and_shows_payload(
    monkeypatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    state = apprc_example_app_state(kit, storage_root)
    app = kit.typer_app(
        state_type=ApprcExampleAppConfigState,
        runtime_payload=lambda current: {
            "storage": str(current.env_bootstrap.storage_root)
            if current.env_bootstrap is not None
            else None,
        },
    )
    runner = CliRunner()

    set_result = runner.invoke(
        app,
        ["set", "app.profile", "other-profile"],
        obj=state,
    )
    show_result = runner.invoke(app, ["show", "--json"], obj=state)

    assert set_result.exit_code == 0, set_result.output
    assert 'APPRC_EXAMPLE_APP_PROFILE="other-profile"\n' in (
        storage_root / ".env.apprc_example_app"
    ).read_text(encoding="utf-8")
    assert show_result.exit_code == 0, show_result.output
    assert json.loads(show_result.output) == {"storage": str(storage_root)}


def test_kit_clears_local_value_with_app_local_env_filename(
    monkeypatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    storage_root = tmp_path / "storage"
    kit.set_local_value(
        storage_root=storage_root,
        reference="app.profile",
        raw_value="other-profile",
    )

    update = kit.clear_local_value(
        storage_root=storage_root,
        reference="APPRC_EXAMPLE_APP_PROFILE",
    )

    assert update is not None
    assert update.path == storage_root.resolve() / ".env.apprc_example_app"
    assert (storage_root / ".env.apprc_example_app").read_text(
        encoding="utf-8"
    ) == "\n"


def test_generated_config_app_inits_existing_storage_after_list_prompt(
    monkeypatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    (storage_root / "payload.txt").write_text("demo", encoding="utf-8")
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["init", str(storage_root), "--name", "alpha", "--default"],
        input="l\ny\n",
    )

    assert result.exit_code == 0, result.output
    assert "Storage Root Already Exists" in result.output
    assert "Directory exists and is not empty." in result.output
    assert str(storage_root) in result.output
    assert (
        "Example App will reuse this directory for Example App storage "
        "'alpha'." in result.output
    )
    assert "Config files to create or update:" in result.output
    assert "storage-local env" in result.output
    assert "AppRC TOML" in result.output
    assert (
        "No existing files will be deleted, moved, or overwritten."
        in result.output
    )
    assert "Default storage: 'alpha'" in result.output
    assert (
        "Choices: y continue  n abort  l list first-level contents"
        in result.output
    )
    assert "payload.txt" in result.output
    assert f'APPRC_EXAMPLE_APP_STORAGE="{storage_root.resolve()}"\n' in (
        storage_root / ".env.apprc_example_app"
    ).read_text(encoding="utf-8")


def test_generated_config_app_rejects_shell_damaged_windows_storage_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()
    malformed = "C:Projectsdemo-storage"
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ["init", malformed, "--name", "alpha", "--default"],
    )

    assert result.exit_code == 2, result.output
    assert "STORAGE_ROOT" in result.output
    assert "Storage root looks like a Windows drive" in result.output
    assert "path, but it is missing a slash" in result.output
    assert "backslashes are consumed" in result.output
    assert "C:/Projects/demo-storage" in result.output
    assert not Path(malformed).exists()
    assert not kit.apprc_toml_path().exists()


def test_generated_config_app_aborts_existing_storage_when_user_says_no(
    monkeypatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    (storage_root / "payload.txt").write_text("demo", encoding="utf-8")
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["init", str(storage_root), "--name", "alpha"],
        input="n\n",
    )

    assert result.exit_code == 1, result.output
    assert "Aborted." in result.output
    assert not kit.apprc_toml_path().exists()
    assert not (storage_root / ".env.apprc_example_app").exists()


def test_generated_config_app_inits_non_empty_storage_with_yes_option(
    monkeypatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    (storage_root / "payload.txt").write_text("demo", encoding="utf-8")
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["init", str(storage_root), "--name", "alpha", "--yes"],
    )

    assert result.exit_code == 0, result.output
    assert "Continue? [y/n/l]" not in result.output
    assert (storage_root / ".env.apprc_example_app").is_file()


def test_generated_config_app_lists_registered_storages_as_rich_tree(
    monkeypatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    alpha_root = tmp_path / "alpha"
    beta_root = tmp_path / "beta"
    kit.register_storage(name="alpha", root=alpha_root, make_default=True)
    kit.register_storage(name="beta", root=beta_root, make_default=False)
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()

    result = runner.invoke(app, ["list"])

    assert result.exit_code == 0, result.output
    assert "apprc_toml_path:" in result.output
    assert "default_storage:" in result.output
    assert "storages:" in result.output
    assert "alpha [default]" in result.output
    assert "beta" in result.output
    assert "root:" in result.output
    assert "root_exists:" in result.output
    assert "local_env:" in result.output
    assert "local_env_exists:" in result.output
    root_lines = [
        line
        for line in result.output.splitlines()
        if "root:" in line and "root_exists:" not in line
    ]
    assert root_lines
    assert all(not line.startswith("root:") for line in root_lines)


def test_generated_config_app_lists_registered_storages_as_json(
    monkeypatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    alpha_root = tmp_path / "alpha"
    beta_root = tmp_path / "beta"
    kit.register_storage(name="alpha", root=alpha_root, make_default=True)
    kit.register_storage(name="beta", root=beta_root, make_default=False)
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()

    result = runner.invoke(app, ["list", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == {
        "apprc_toml_path": str(
            tmp_path
            / "config"
            / "apprc_example_app"
            / "apprc_example_app.apprc.toml"
        ),
        "default_storage": "alpha",
        "storages": [
            {
                "default": True,
                "local_env": str(
                    alpha_root.resolve() / ".env.apprc_example_app"
                ),
                "local_env_exists": True,
                "name": "alpha",
                "root": str(alpha_root.resolve()),
                "root_exists": True,
            },
            {
                "default": False,
                "local_env": str(
                    beta_root.resolve() / ".env.apprc_example_app"
                ),
                "local_env_exists": True,
                "name": "beta",
                "root": str(beta_root.resolve()),
                "root_exists": True,
            },
        ],
    }


def test_config_doctor_guidance_uses_host_default_storage_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()

    message = config_setup_message(kit)
    payload = build_config_doctor_payload(kit, storage_name=None)

    assert "APPRC_EXAMPLE_APP_APPRC_TOML" in message
    assert "setup --yes --apprc-dir" in message
    assert payload["next_steps"][0].endswith(
        "setup --yes --apprc-dir /absolute/path/to/config-dir"
    )
