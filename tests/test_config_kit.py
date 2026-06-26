from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apprc.cli.config import config_request_skips_runtime_bootstrap
from apprc.runtime_config import (
    AppConfigKit,
    ConfigDoctorStatus,
)
from apprc.runtime_config.doctor.payload import build_config_doctor_payload
from apprc.runtime_config.contract.schema import ConfigField, ConfigOwner
from tests.support_config import (
    APPRC_EXAMPLE_APP_OWNERS,
    ApprcExampleAppConfigState,
    ApprcExampleAppEnv,
    StorageFreeExampleConfigState,
    build_apprc_example_app_kit,
    build_storage_free_example_kit,
    register_storage_for_kit,
    set_apprc_example_app_apprc_toml,
    set_apprc_example_app_bootstrap,
)

pytestmark = [pytest.mark.requires_apprc_env("APPRC_EXAMPLE_APP")]


def test_config_init_and_list_skip_runtime_bootstrap() -> None:
    skips = config_request_skips_runtime_bootstrap

    assert skips(tokens=["config", "init", "/tmp/storage"])
    assert skips(tokens=["config", "list"])
    assert skips(tokens=["config", "edit"])
    assert skips(tokens=["config", "setup"])


def test_config_owner_builds_env_keys_and_config_paths() -> None:
    owner = ConfigOwner(
        key="app",
        title="App",
        env_prefix="APPRC_EXAMPLE_APP_",
        rc_path=("app",),
        fields=(
            ConfigField(
                "profile",
                "PROFILE",
                str,
                default="default",
            ),
        ),
    )

    assert owner.env_key("profile") == "APPRC_EXAMPLE_APP_PROFILE"
    assert owner.config_path("profile") == ("app", "profile")
    assert owner.config_path_text("profile") == "app.profile"


def test_kit_derives_apprc_toml_filename() -> None:
    kit = AppConfigKit(
        app_name="my-app.rc",
        display_name="My App",
        config_package="apprc.runtime_config",
        envs=(ApprcExampleAppEnv,),
        storage_env_key="MY_APP_STORAGE",
    )

    assert kit.spec.apprc_toml_filename == "my-app_rc.apprc.toml"


def test_kit_rejects_manual_owner_argument() -> None:
    with pytest.raises(TypeError, match="owners"):
        AppConfigKit(  # pyright: ignore[reportCallIssue]
            app_name="my-app.rc",
            display_name="My App",
            config_package="apprc.runtime_config",
            owners=APPRC_EXAMPLE_APP_OWNERS,
            storage_env_key="MY_APP_STORAGE",
        )


@pytest.mark.allow_missing_apprc_env
def test_kit_apprc_toml_path_defaults_to_config_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("APPRC_EXAMPLE_APP_APPRC_TOML", raising=False)
    monkeypatch.delenv("APPRC_EXAMPLE_APP_STORAGE", raising=False)
    kit = build_apprc_example_app_kit()

    assert (
        kit.spec.required_apprc_toml_path()
        == tmp_path
        / "config-home"
        / "apprc_example_app"
        / "apprc_example_app.apprc.toml"
    )


@pytest.mark.allow_missing_apprc_env
def test_config_doctor_reports_env_not_set_without_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("APPRC_EXAMPLE_APP_APPRC_TOML", raising=False)
    monkeypatch.delenv("APPRC_EXAMPLE_APP_STORAGE", raising=False)
    kit = build_apprc_example_app_kit()
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()

    payload = build_config_doctor_payload(kit, storage=None)
    result = runner.invoke(app, ["doctor", "--json"])

    assert payload["status"] == ConfigDoctorStatus.ENV_NOT_SET.value
    assert payload["apprc_toml_exists"] is True
    assert payload["missing_env_keys"] == ["APPRC_EXAMPLE_APP_STORAGE"]
    assert result.exit_code == 1, result.output
    result_payload = json.loads(result.output)
    assert result_payload["status"] == "env_not_set"
    assert "runnable" not in result_payload


@pytest.mark.allow_missing_apprc_env
def test_config_doctor_prints_env_not_set_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("APPRC_EXAMPLE_APP_APPRC_TOML", raising=False)
    monkeypatch.delenv("APPRC_EXAMPLE_APP_STORAGE", raising=False)
    kit = build_apprc_example_app_kit()
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 1, result.output
    assert "Example App config doctor: env not set" in result.output
    assert "missing_env_keys: APPRC_EXAMPLE_APP_STORAGE" in result.output


@pytest.mark.allow_missing_apprc_env
def test_storage_free_config_cli_uses_global_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("STORAGE_FREE_APP_PROFILE", raising=False)
    kit = build_storage_free_example_kit()
    app = kit.typer_app(state_type=StorageFreeExampleConfigState)
    runner = CliRunner()

    doctor = runner.invoke(app, ["doctor", "--json"])
    show = runner.invoke(app, ["show", "--json"])
    update = runner.invoke(app, ["set", "profile", "global-profile"])
    storage_list = runner.invoke(app, ["list"])

    assert doctor.exit_code == 0, doctor.output
    doctor_payload = json.loads(doctor.output)
    assert doctor_payload["status"] == "runnable"
    assert doctor_payload["storage_count"] == 0
    assert doctor_payload["selected_storage_root"] is None
    assert Path(doctor_payload["global_env"]).is_file()
    assert Path(doctor_payload["apprc_toml_path"]).is_file()
    assert show.exit_code == 0, show.output
    show_payload = json.loads(show.output)
    assert show_payload["storage_root"] is None
    assert show_payload["global_env"] == doctor_payload["global_env"]
    assert update.exit_code == 0, update.output
    assert "global_env:" in update.output
    assert 'STORAGE_FREE_APP_PROFILE="global-profile"' in Path(
        doctor_payload["global_env"]
    ).read_text(encoding="utf-8")
    assert storage_list.exit_code != 0
    assert "does not use AppRC storage" in storage_list.output


@pytest.mark.allow_missing_apprc_env
def test_config_doctor_reports_runnable_single_storage_without_apprc_toml(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("APPRC_EXAMPLE_APP_APPRC_TOML", raising=False)
    storage_root = tmp_path / "alpha"
    storage_root.mkdir()
    (storage_root / ".env.apprc_example_app").write_text("", encoding="utf-8")
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", str(storage_root))
    kit = build_apprc_example_app_kit()
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()

    payload = build_config_doctor_payload(kit, storage=None)
    result = runner.invoke(app, ["doctor"])

    assert payload["status"] == ConfigDoctorStatus.RUNNABLE.value
    assert payload["apprc_toml_path"] is not None
    assert payload["missing_env_keys"] == []
    assert payload["selected_storage_root"] == str(storage_root.resolve())
    assert payload["issues"] == []
    assert payload["warnings"]
    assert result.exit_code == 0, result.output
    assert "Warnings:" in result.output
    assert "Issues:" not in result.output
    assert "Next steps:" not in result.output


def test_config_doctor_reports_env_not_set_for_missing_storage_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_bootstrap(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    register_storage_for_kit(
        kit,
        name="alpha",
        root=tmp_path / "storage",
    )
    monkeypatch.delenv("APPRC_EXAMPLE_APP_STORAGE", raising=False)

    payload = build_config_doctor_payload(kit, storage=None)

    assert payload["status"] == ConfigDoctorStatus.ENV_NOT_SET.value
    assert payload["apprc_toml_exists"] is True
    assert payload["missing_env_keys"] == ["APPRC_EXAMPLE_APP_STORAGE"]


@pytest.mark.allow_missing_apprc_env
def test_generated_config_setup_yes_requires_storage_without_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("APPRC_EXAMPLE_APP_APPRC_TOML", raising=False)
    monkeypatch.delenv("APPRC_EXAMPLE_APP_STORAGE", raising=False)
    kit = build_apprc_example_app_kit()
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()

    result = runner.invoke(app, ["setup", "--yes"])

    assert result.exit_code == 2, result.output
    assert "--storage-root" in result.output
    assert "APPRC_EXAMPLE_APP_STORAGE" in result.output


def test_doctor_payload_creates_missing_override_apprc_toml(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing_apprc_toml = tmp_path / "missing.toml"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    (storage_root / ".env.apprc_example_app").write_text("", encoding="utf-8")
    monkeypatch.setenv("APPRC_EXAMPLE_APP_APPRC_TOML", str(missing_apprc_toml))
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", str(storage_root))
    kit = build_apprc_example_app_kit()

    payload = build_config_doctor_payload(kit, storage=None)

    assert payload["status"] == ConfigDoctorStatus.RUNNABLE.value
    assert payload["apprc_toml_path"] == str(missing_apprc_toml)
    assert missing_apprc_toml.is_file()


def test_doctor_payload_reports_runnable_for_empty_apprc_toml_with_active_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    apprc_toml_path = set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    apprc_toml_path.parent.mkdir(parents=True)
    apprc_toml_path.write_text("\n", encoding="utf-8")
    storage_root = tmp_path / "active-storage"
    storage_root.mkdir()
    (storage_root / ".env.apprc_example_app").write_text("", encoding="utf-8")
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", str(storage_root))
    kit = build_apprc_example_app_kit()

    payload = build_config_doctor_payload(kit, storage=None)

    assert payload["status"] == ConfigDoctorStatus.RUNNABLE.value
    assert payload["apprc_toml_exists"] is True
    assert payload["storage_count"] == 0
    assert payload["selected_storage"] is None


def test_doctor_payload_reports_multi_storage_not_ready_for_invalid_registry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    apprc_toml_path = set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    apprc_toml_path.parent.mkdir(parents=True)
    apprc_toml_path.write_text("[invalid", encoding="utf-8")
    kit = build_apprc_example_app_kit()

    payload = build_config_doctor_payload(kit, storage=None)

    assert payload["status"] == ConfigDoctorStatus.MULTI_STORAGE_NOT_READY.value
    assert payload["apprc_toml_parse_ok"] is False
    assert payload["apprc_toml_error"] is not None


def test_doctor_payload_reports_storage_not_ready_for_missing_local_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    storage_root = tmp_path / "storage"
    register_storage_for_kit(kit, name="alpha", root=storage_root)
    (storage_root / ".env.apprc_example_app").unlink()
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", "alpha")

    payload = build_config_doctor_payload(kit, storage=None)

    assert payload["status"] == ConfigDoctorStatus.STORAGE_NOT_READY.value
    assert payload["selected_local_env_exists"] is False
    assert payload["next_steps"][0] == (
        "Ensure the selected storage root exists and contains "
        ".env.apprc_example_app."
    )


def test_doctor_payload_reports_runnable_for_active_storage_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_bootstrap(
        monkeypatch,
        tmp_path,
        storage_root=tmp_path / "storage",
    )
    kit = build_apprc_example_app_kit()
    register_storage_for_kit(
        kit,
        name="alpha",
        root=tmp_path / "storage",
    )

    payload = build_config_doctor_payload(kit, storage=None)

    assert payload["status"] == ConfigDoctorStatus.RUNNABLE.value
    assert payload["apprc_toml_exists"] is True


def test_doctor_payload_tracks_selected_storage_source_from_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_bootstrap(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    registry_root = tmp_path / "registry"
    active_root = tmp_path / "active"
    active_root.mkdir()
    (active_root / ".env.apprc_example_app").write_text(
        'APPRC_EXAMPLE_APP_PROFILE="override"\n',
        encoding="utf-8",
    )

    register_storage_for_kit(
        kit,
        name="alpha",
        root=registry_root,
    )
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", str(active_root))
    payload = build_config_doctor_payload(kit, storage=None)

    assert payload["selected_storage_source"] == "APPRC_EXAMPLE_APP_STORAGE"
    assert payload["selected_storage_root"] == str(active_root.resolve())
    assert payload["selected_storage"] is None
    assert payload["status"] == ConfigDoctorStatus.RUNNABLE.value


def test_doctor_payload_resolves_storage_env_registered_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_bootstrap(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    storage_root = tmp_path / "alpha"

    register_storage_for_kit(
        kit,
        name="alpha",
        root=storage_root,
    )
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", "alpha")

    payload = build_config_doctor_payload(kit, storage=None)

    assert payload["selected_storage_source"] == "APPRC_EXAMPLE_APP_STORAGE"
    assert payload["selected_storage"] == "alpha"
    assert payload["selected_storage_root"] == str(storage_root.resolve())
    assert payload["status"] == ConfigDoctorStatus.RUNNABLE.value


def test_registry_storage_setup_reports_doctor_payload(
    monkeypatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_bootstrap(
        monkeypatch,
        tmp_path,
        storage_root=tmp_path / "storage",
    )
    kit = build_apprc_example_app_kit()
    storage_root = tmp_path / "storage"

    registry = register_storage_for_kit(
        kit,
        name="alpha",
        root=storage_root,
    )
    payload = build_config_doctor_payload(kit, storage=None)

    assert (
        registry.path
        == tmp_path
        / "config"
        / "apprc_example_app"
        / "apprc_example_app.apprc.toml"
    )
    assert (storage_root / ".env.apprc_example_app").is_file()
    assert "APPRC_EXAMPLE_APP_STORAGE" not in (
        storage_root / ".env.apprc_example_app"
    ).read_text(encoding="utf-8")
    assert payload["status"] == ConfigDoctorStatus.RUNNABLE.value
    assert payload["selected_storage_root"] == str(storage_root.resolve())
    assert payload["selected_local_env_exists"] is True


def test_config_field_stores_explicit_short_and_long_explanations() -> None:
    spec = ConfigField(
        "demo",
        "DEMO",
        str,
        explanation_short="Short sentence.",
        explanation_long=(
            "Short sentence. Extra detail that should remain available in "
            "the modal."
        ),
    )

    assert spec.explanation_short == "Short sentence."
    assert spec.explanation_long.startswith("Short sentence. Extra detail")
