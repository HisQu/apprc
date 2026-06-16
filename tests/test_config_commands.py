from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from typer.testing import CliRunner

from apprc.config.tui import ConfigEditorApp
from apprc.config.diagnostics import (
    build_config_doctor_payload,
    config_setup_message,
)
from tests.support_config import (
    ApprcExampleAppConfigState,
    apprc_example_app_state,
    build_apprc_example_app_kit,
    register_storage_for_kit,
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


@pytest.mark.allow_missing_apprc_env
def test_generated_config_app_sets_and_shows_with_storage_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("APPRC_EXAMPLE_APP_APPRC_TOML", raising=False)
    storage_root = tmp_path / "single-storage"
    storage_root.mkdir()
    (storage_root / ".env.apprc_example_app").write_text("", encoding="utf-8")
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", str(storage_root))
    kit = build_apprc_example_app_kit()
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    state = ApprcExampleAppConfigState(env_bootstrap=None)
    runner = CliRunner()

    set_result = runner.invoke(
        app,
        ["set", "app.profile", "single-profile"],
        obj=state,
    )
    show_result = runner.invoke(app, ["show", "--json"], obj=state)

    assert set_result.exit_code == 0, set_result.output
    assert show_result.exit_code == 0, show_result.output
    assert 'APPRC_EXAMPLE_APP_PROFILE="single-profile"\n' in (
        storage_root / ".env.apprc_example_app"
    ).read_text(encoding="utf-8")
    assert json.loads(show_result.output)["apprc_toml_path"] is None


@pytest.mark.allow_missing_apprc_env
def test_generated_config_multi_storage_commands_require_apprc_toml_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("APPRC_EXAMPLE_APP_APPRC_TOML", raising=False)
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", str(tmp_path / "storage"))
    kit = build_apprc_example_app_kit()
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()

    list_result = runner.invoke(app, ["list"])
    init_result = runner.invoke(
        app,
        ["init", str(tmp_path / "storage"), "--name", "alpha"],
    )

    assert list_result.exit_code == 2, list_result.output
    assert init_result.exit_code == 2, init_result.output
    assert "APPRC_EXAMPLE_APP_APPRC_TOML" in list_result.output
    assert "required for multi-storage" in list_result.output
    assert "APPRC_EXAMPLE_APP_APPRC_TOML" in init_result.output
    assert "required for multi-storage" in init_result.output


def test_generated_config_list_rejects_missing_apprc_toml_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing_apprc_toml = tmp_path / "missing.apprc.toml"
    monkeypatch.setenv("APPRC_EXAMPLE_APP_APPRC_TOML", str(missing_apprc_toml))
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", str(tmp_path / "storage"))
    kit = build_apprc_example_app_kit()
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()

    result = runner.invoke(app, ["list"])

    assert result.exit_code == 2, result.output
    assert "APPRC_EXAMPLE_APP_APPRC_TOML" in result.output
    assert "points to a missing AppRC TOML file" in result.output
    assert not missing_apprc_toml.exists()


def test_generated_config_init_creates_missing_apprc_toml_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing_apprc_toml = tmp_path / "missing.apprc.toml"
    storage_root = tmp_path / "storage"
    monkeypatch.setenv("APPRC_EXAMPLE_APP_APPRC_TOML", str(missing_apprc_toml))
    kit = build_apprc_example_app_kit()
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["init", str(storage_root), "--name", "alpha", "--yes"],
    )

    assert result.exit_code == 0, result.output
    assert missing_apprc_toml.is_file()
    assert "registered_storage: alpha" in result.output


@pytest.mark.allow_missing_apprc_env
def test_generated_config_edit_opens_single_storage_without_apprc_toml(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class RecordingEditor:
        instances: list["RecordingEditor"] = []

        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            self.ran = False
            self.instances.append(self)

        def run(self) -> None:
            self.ran = True

    monkeypatch.delenv("APPRC_EXAMPLE_APP_APPRC_TOML", raising=False)
    storage_root = tmp_path / "single-storage"
    storage_root.mkdir()
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", str(storage_root))
    kit = build_apprc_example_app_kit()
    app = kit.typer_app(
        state_type=ApprcExampleAppConfigState,
        editor_app_cls=cast(type[ConfigEditorApp], RecordingEditor),
    )
    runner = CliRunner()

    result = runner.invoke(app, ["edit"])

    assert result.exit_code == 0, result.output
    assert len(RecordingEditor.instances) == 1
    editor = RecordingEditor.instances[0]
    assert editor.ran
    assert editor.kwargs["active_storage_root"] == storage_root.resolve()


def test_generated_config_edit_rejects_missing_apprc_toml_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing_apprc_toml = tmp_path / "missing.apprc.toml"
    monkeypatch.setenv("APPRC_EXAMPLE_APP_APPRC_TOML", str(missing_apprc_toml))
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", str(tmp_path / "storage"))
    kit = build_apprc_example_app_kit()
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()

    result = runner.invoke(app, ["edit"])

    assert result.exit_code == 2, result.output
    assert "APPRC_EXAMPLE_APP_APPRC_TOML" in result.output
    assert "points to a missing AppRC TOML file" in result.output


def test_generated_config_app_rejects_bare_unknown_storage_selector(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    register_storage_for_kit(
        kit,
        name="alpha",
        root=tmp_path / "alpha-storage",
    )
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", "beta")
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    state = ApprcExampleAppConfigState(env_bootstrap=None)
    runner = CliRunner()

    payload = build_config_doctor_payload(kit, storage=None)
    result = runner.invoke(app, ["show"], obj=state)

    assert result.exit_code == 2, result.output
    assert "not a registered storage" in result.output
    assert any("Use './beta'" in issue for issue in payload["issues"])


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
        ["init", str(storage_root), "--name", "alpha"],
        input="l\ny\n",
    )

    assert result.exit_code == 0, result.output
    assert "Storage Root Not Empty" in result.output
    assert "Storage root exists and is not empty." in result.output
    assert str(storage_root) in result.output
    assert (
        "Example App will reuse this directory for Example App storage "
        "'alpha'." in result.output
    )
    assert "AppRC-managed files to create or update:" in result.output
    assert "storage-local env" in result.output
    assert "AppRC TOML file" in result.output
    assert "Existing files inside the storage root" in result.output
    assert "will not be deleted" in result.output
    assert (
        "Choices: y continue  n abort  l list first-level contents"
        in result.output
    )
    assert "payload.txt" in result.output
    local_env = (storage_root / ".env.apprc_example_app").read_text(
        encoding="utf-8"
    )
    assert "APPRC_EXAMPLE_APP_STORAGE" not in local_env


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
        ["init", malformed, "--name", "alpha"],
    )

    assert result.exit_code == 2, result.output
    assert "STORAGE_ROOT" in result.output
    assert "Storage root looks like a Windows drive" in result.output
    assert "path, but it is missing a slash" in result.output
    assert "backslashes are consumed" in result.output
    assert "C:/Projects/demo-storage" in result.output
    assert not Path(malformed).exists()
    assert not kit.spec.required_apprc_toml_path().exists()


def test_generated_config_app_rejects_removed_default_commands(
    monkeypatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()

    init_result = runner.invoke(
        app,
        [
            "init",
            str(tmp_path / "storage"),
            "--name",
            "alpha",
            "--default",
        ],
    )
    set_default_result = runner.invoke(app, ["set-default", "alpha"])

    assert init_result.exit_code == 2, init_result.output
    assert "--default" in init_result.output
    assert set_default_result.exit_code == 2, set_default_result.output
    assert "set-default" in set_default_result.output


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
    assert not kit.spec.required_apprc_toml_path().exists()
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
    register_storage_for_kit(kit, name="alpha", root=alpha_root)
    register_storage_for_kit(kit, name="beta", root=beta_root)
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", str(alpha_root.resolve()))
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()

    result = runner.invoke(app, ["list"])

    assert result.exit_code == 0, result.output
    assert "apprc_toml_path:" in result.output
    assert "storages:" in result.output
    assert "alpha [active]" in result.output
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
    register_storage_for_kit(kit, name="alpha", root=alpha_root)
    register_storage_for_kit(kit, name="beta", root=beta_root)
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", str(alpha_root.resolve()))
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
        "storages": [
            {
                "active": True,
                "local_env": str(
                    alpha_root.resolve() / ".env.apprc_example_app"
                ),
                "local_env_exists": True,
                "name": "alpha",
                "root": str(alpha_root.resolve()),
                "root_exists": True,
            },
            {
                "active": False,
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


@pytest.mark.allow_missing_apprc_env
def test_config_doctor_guidance_describes_active_storage_selector(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("APPRC_EXAMPLE_APP_APPRC_TOML", raising=False)
    monkeypatch.delenv("APPRC_EXAMPLE_APP_STORAGE", raising=False)
    kit = build_apprc_example_app_kit()

    message = config_setup_message(kit)
    payload = build_config_doctor_payload(kit, storage=None)

    assert "APPRC_EXAMPLE_APP_APPRC_TOML" in message
    assert "optional" in message
    assert "active storage root" in message
    assert "setup --yes --storage-root" in message
    assert payload["next_steps"][0].endswith(
        "setup --yes --storage-root /absolute/path/to/storage-root"
    )
