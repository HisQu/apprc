from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apprc.cli.config import config_request_skips_bootstrap
from apprc.config import (
    AppConfigKit,
    ApprcTomlEnvError,
    ConfigInstallState,
    ConfigOwner,
    config_field,
)
from apprc.config.diagnostics import build_config_doctor_payload
from tests.support_config import (
    APPRC_EXAMPLE_APP_OWNERS,
    ApprcExampleAppConfigState,
    build_apprc_example_app_kit,
    set_apprc_example_app_apprc_toml,
    set_apprc_example_app_bootstrap,
)

pytestmark = [pytest.mark.requires_apprc_env("APPRC_EXAMPLE_APP")]


def test_config_init_and_list_skip_runtime_bootstrap() -> None:
    assert config_request_skips_bootstrap(["init", "/tmp/storage"])
    assert config_request_skips_bootstrap(["list"])
    assert config_request_skips_bootstrap(["edit"])
    assert config_request_skips_bootstrap(["setup"])


def test_config_owner_runtime_cls_is_optional() -> None:
    owner = ConfigOwner(
        key="app",
        title="App",
        env_prefix="APPRC_EXAMPLE_APP_",
        rc_path=("app",),
        fields=(
            config_field(
                "profile",
                "PROFILE",
                str,
                default="default",
            ),
        ),
    )

    assert owner.runtime_cls is None
    assert owner.env_key("profile") == "APPRC_EXAMPLE_APP_PROFILE"

    legacy_owner = ConfigOwner(
        key="legacy",
        title="Legacy",
        env_prefix="LEGACY_",
        rc_path=("legacy",),
        runtime_cls=object,
        fields=owner.fields,
    )
    assert legacy_owner.runtime_cls is object


def test_kit_computes_default_apprc_toml_filename() -> None:
    kit = AppConfigKit(
        app_name="my-app.rc",
        display_name="My App",
        config_package="apprc.config",
        owners=APPRC_EXAMPLE_APP_OWNERS,
        storage_env_key="MY_APP_STORAGE",
    )

    assert kit.spec.apprc_toml_filename == "my-app_rc.apprc.toml"


@pytest.mark.allow_missing_apprc_env
def test_kit_registry_path_requires_apprc_toml_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("APPRC_EXAMPLE_APP_APPRC_TOML", raising=False)
    monkeypatch.delenv("APPRC_EXAMPLE_APP_STORAGE", raising=False)
    kit = build_apprc_example_app_kit()

    with pytest.raises(ApprcTomlEnvError) as exc_info:
        kit.apprc_toml_path()

    message = str(exc_info.value)
    assert (
        "APPRC_EXAMPLE_APP_APPRC_TOML is required for multi-storage" in message
    )
    assert "config setup --yes --apprc-dir" in message


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

    assert payload["install_state"] == ConfigInstallState.ENV_NOT_SET.value
    assert payload["ok"] is False
    assert payload["apprc_toml_exists"] is False
    assert payload["missing_env_keys"] == ["APPRC_EXAMPLE_APP_STORAGE"]
    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["install_state"] == "env_not_set"


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
def test_config_doctor_reports_healthy_single_storage_without_apprc_toml(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("APPRC_EXAMPLE_APP_APPRC_TOML", raising=False)
    storage_root = tmp_path / "alpha"
    storage_root.mkdir()
    (storage_root / ".env.apprc_example_app").write_text("", encoding="utf-8")
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", str(storage_root))
    kit = build_apprc_example_app_kit()

    payload = build_config_doctor_payload(kit, storage=None)

    assert (
        payload["install_state"] == ConfigInstallState.INSTALLED_HEALTHY.value
    )
    assert payload["apprc_toml_path"] is None
    assert payload["missing_env_keys"] == []
    assert payload["selected_storage_root"] == str(storage_root.resolve())


def test_config_doctor_reports_env_not_set_for_missing_storage_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_bootstrap(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    kit.register_storage(
        name="alpha",
        root=tmp_path / "storage",
    )
    monkeypatch.delenv("APPRC_EXAMPLE_APP_STORAGE", raising=False)

    payload = build_config_doctor_payload(kit, storage=None)

    assert payload["install_state"] == ConfigInstallState.ENV_NOT_SET.value
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


def test_install_state_reports_not_installed_for_missing_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing_registry = tmp_path / "missing.toml"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    (storage_root / ".env.apprc_example_app").write_text("", encoding="utf-8")
    monkeypatch.setenv("APPRC_EXAMPLE_APP_APPRC_TOML", str(missing_registry))
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", str(storage_root))
    kit = build_apprc_example_app_kit()

    assert kit.install_state() == ConfigInstallState.NOT_INSTALLED


def test_install_state_reports_healthy_for_empty_registry_with_active_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry_path = set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text("\n", encoding="utf-8")
    storage_root = tmp_path / "active-storage"
    storage_root.mkdir()
    (storage_root / ".env.apprc_example_app").write_text("", encoding="utf-8")
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", str(storage_root))
    kit = build_apprc_example_app_kit()

    payload = kit.doctor_payload()

    assert kit.install_state() == ConfigInstallState.INSTALLED_HEALTHY
    assert payload["ok"] is True
    assert payload["apprc_toml_exists"] is True
    assert payload["storage_count"] == 0
    assert payload["selected_storage"] is None


def test_install_state_reports_unhealthy_for_invalid_registry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry_path = set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text("[invalid", encoding="utf-8")
    kit = build_apprc_example_app_kit()

    payload = kit.doctor_payload()

    assert kit.install_state() == ConfigInstallState.INSTALLED_UNHEALTHY
    assert payload["apprc_toml_parse_ok"] is False
    assert payload["apprc_toml_error"] is not None


def test_install_state_reports_unhealthy_for_missing_local_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    storage_root = tmp_path / "storage"
    kit.register_storage(name="alpha", root=storage_root)
    (storage_root / ".env.apprc_example_app").unlink()
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", "alpha")

    payload = kit.doctor_payload()

    assert kit.install_state() == ConfigInstallState.INSTALLED_UNHEALTHY
    assert payload["selected_local_env_exists"] is False


def test_install_state_reports_healthy_for_active_storage_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_bootstrap(
        monkeypatch,
        tmp_path,
        storage_root=tmp_path / "storage",
    )
    kit = build_apprc_example_app_kit()
    kit.register_storage(
        name="alpha",
        root=tmp_path / "storage",
    )

    payload = kit.doctor_payload()

    assert kit.install_state() == ConfigInstallState.INSTALLED_HEALTHY
    assert payload["ok"] is True
    assert payload["apprc_toml_exists"] is True


def test_install_state_tracks_selected_storage_source_from_env(
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

    kit.register_storage(
        name="alpha",
        root=registry_root,
    )
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", str(active_root))
    payload = kit.doctor_payload()

    assert payload["selected_storage_source"] == "APPRC_EXAMPLE_APP_STORAGE"
    assert payload["selected_storage_root"] == str(active_root.resolve())
    assert payload["selected_storage"] is None
    assert payload["ok"] is True


def test_install_state_resolves_storage_env_registered_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_bootstrap(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    storage_root = tmp_path / "alpha"

    kit.register_storage(
        name="alpha",
        root=storage_root,
    )
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", "alpha")

    payload = kit.doctor_payload()

    assert payload["selected_storage_source"] == "APPRC_EXAMPLE_APP_STORAGE"
    assert payload["selected_storage"] == "alpha"
    assert payload["selected_storage_root"] == str(storage_root.resolve())
    assert payload["ok"] is True


def test_kit_registers_storage_and_reports_doctor_payload(
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

    registry = kit.register_storage(
        name="alpha",
        root=storage_root,
    )
    payload = kit.doctor_payload()

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
    assert payload["ok"] is True
    assert payload["selected_storage_root"] == str(storage_root.resolve())
    assert payload["selected_local_env_exists"] is True


def test_config_field_splits_short_and_long_explanations() -> None:
    spec = config_field(
        "demo",
        "DEMO",
        str,
        explanation=(
            "Short sentence. Extra detail that should remain available in "
            "the modal."
        ),
    )

    assert spec.explanation_short == "Short sentence."
    assert spec.explanation_long.startswith("Short sentence. Extra detail")
    assert spec.explanation == spec.explanation_long
