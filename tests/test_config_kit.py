from __future__ import annotations

from pathlib import Path

import pytest

from apprc.interfaces.cli.config_command.state import (
    active_storage_root_from_env,
    initial_storage_from_state,
)
from apprc.definition.app_config.capabilities import (
    CapabilityState,
    StorageLayerState,
)
from apprc.runtime.diagnostics.payload import build_config_doctor_payload
from apprc.runtime.diagnostics.status import ConfigDoctorStatus
from apprc.definition.app_config.kit import AppConfigKit
from apprc.user_files.storage_roots.registry import register_storage
from tests.support_config import (
    ApprcExampleAppConfigState,
    ApprcExampleAppEnv,
    StorageFreeExampleEnv,
    build_apprc_example_app_kit,
    build_storage_free_example_kit,
)


def test_kit_constructors_declare_expected_capabilities() -> None:
    env_only = AppConfigKit.env_only(
        app_name="env_app",
        display_name="Env App",
        config_package="apprc",
        envs=(StorageFreeExampleEnv,),
    )
    storage_only = build_apprc_example_app_kit()
    app_wide = build_storage_free_example_kit()
    app_wide_storage = AppConfigKit.app_wide_storage(
        app_name="wide_storage",
        display_name="Wide Storage",
        config_package="apprc",
        envs=(ApprcExampleAppEnv,),
    )

    assert env_only.spec.storage_layer == StorageLayerState.DISABLED
    assert env_only.spec.app_wide_layer == CapabilityState.OPTIONAL
    assert env_only.spec.named_storage_layer == CapabilityState.DISABLED
    assert storage_only.spec.storage_layer == StorageLayerState.REQUIRED
    assert storage_only.spec.app_wide_layer == CapabilityState.OPTIONAL
    assert storage_only.spec.named_storage_layer == CapabilityState.OPTIONAL
    assert app_wide.spec.app_wide_layer == CapabilityState.OPTIONAL
    assert app_wide_storage.spec.storage_layer == StorageLayerState.REQUIRED
    assert app_wide_storage.spec.app_wide_layer == CapabilityState.DEFAULT


def test_kit_rejects_removed_storage_mode_keyword() -> None:
    with pytest.raises(TypeError):
        AppConfigKit(
            app_name="demo",
            display_name="Demo",
            config_package="apprc",
            storage_mode="required",  # pyright: ignore[reportCallIssue]
        )


def test_doctor_env_not_set_for_missing_storage_selector(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    monkeypatch.delenv("APPRC_EXAMPLE_APP_STORAGE", raising=False)
    kit = build_apprc_example_app_kit()

    payload = build_config_doctor_payload(kit, storage=None)

    assert payload.status == ConfigDoctorStatus.ENV_NOT_SET.value
    assert payload.missing_env_keys == ("APPRC_EXAMPLE_APP_STORAGE",)
    assert not kit.spec.app_env_path().exists()
    assert not kit.spec.apprc_toml_path().exists()


def test_doctor_app_config_is_runnable_before_first_app_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    kit = build_storage_free_example_kit()

    payload = build_config_doctor_payload(kit, storage=None)

    assert payload.status == ConfigDoctorStatus.RUNNABLE.value
    assert payload.app_env_exists is False


def test_doctor_named_storage_not_ready_for_bad_apprc_toml(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", "alpha")
    kit = build_apprc_example_app_kit()
    apprc_toml = kit.spec.apprc_toml_path()
    apprc_toml.parent.mkdir(parents=True)
    apprc_toml.write_text("[invalid", encoding="utf-8")

    payload = build_config_doctor_payload(kit, storage=None)

    assert payload.status == ConfigDoctorStatus.NAMED_STORAGE_NOT_READY.value
    assert payload.apprc_toml_parse_ok is False
    assert payload.apprc_toml_error is not None


def test_doctor_warns_about_bad_optional_apprc_toml_without_selector(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    monkeypatch.delenv("APPRC_EXAMPLE_APP_STORAGE", raising=False)
    kit = build_apprc_example_app_kit()
    apprc_toml = kit.spec.apprc_toml_path()
    apprc_toml.parent.mkdir(parents=True)
    apprc_toml.write_text("[invalid", encoding="utf-8")

    payload = build_config_doctor_payload(kit, storage=None)

    assert payload.status == ConfigDoctorStatus.ENV_NOT_SET.value
    assert payload.apprc_toml_parse_ok is False
    assert any(
        "AppRC TOML is invalid" in warning for warning in payload.warnings
    )
    assert not any("AppRC TOML is invalid" in issue for issue in payload.issues)


def test_doctor_warns_about_bad_optional_apprc_toml_for_path_selector(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    (storage_root / "apprc.storage.env").write_text("", encoding="utf-8")
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", str(storage_root))
    kit = build_apprc_example_app_kit()
    apprc_toml = kit.spec.apprc_toml_path()
    apprc_toml.parent.mkdir(parents=True)
    apprc_toml.write_text("[invalid", encoding="utf-8")

    payload = build_config_doctor_payload(kit, storage=None)

    assert payload.status == ConfigDoctorStatus.RUNNABLE.value
    assert payload.apprc_toml_parse_ok is False
    assert any(
        "AppRC TOML is invalid" in warning for warning in payload.warnings
    )


def test_doctor_ignores_bad_apprc_toml_when_named_storage_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    (storage_root / "apprc.storage.env").write_text("", encoding="utf-8")
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", str(storage_root))
    kit = AppConfigKit(
        app_name="apprc_example_app",
        display_name="Example App",
        config_package="apprc",
        envs=(ApprcExampleAppEnv,),
        storage_env_key="APPRC_EXAMPLE_APP_STORAGE",
        storage_layer=StorageLayerState.REQUIRED,
        named_storage_layer=CapabilityState.DISABLED,
        index_filename="apprc_example_app.apprc.toml",
    )
    apprc_toml = kit.spec.apprc_toml_path()
    apprc_toml.parent.mkdir(parents=True)
    apprc_toml.write_text("[invalid", encoding="utf-8")

    payload = build_config_doctor_payload(kit, storage=None)

    assert payload.status == ConfigDoctorStatus.RUNNABLE.value
    assert payload.apprc_toml_parse_ok is True
    assert any(
        "named storage is disabled" in warning for warning in payload.warnings
    )


def test_doctor_storage_not_ready_for_missing_storage_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", str(storage_root))
    kit = build_apprc_example_app_kit()

    payload = build_config_doctor_payload(kit, storage=None)

    assert payload.status == ConfigDoctorStatus.STORAGE_NOT_READY.value
    assert payload.selected_storage_env_exists is False


def test_doctor_runnable_for_storage_with_storage_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    (storage_root / "apprc.storage.env").write_text("", encoding="utf-8")
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", str(storage_root))
    kit = build_apprc_example_app_kit()

    payload = build_config_doctor_payload(kit, storage=None)

    assert payload.status == ConfigDoctorStatus.RUNNABLE.value


def test_doctor_warns_about_legacy_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    (storage_root / "apprc.storage.env").write_text("", encoding="utf-8")
    (storage_root / ".env.local").write_text("OLD=1\n", encoding="utf-8")
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", str(storage_root))
    kit = build_apprc_example_app_kit()
    legacy_app = kit.spec.app_wide_env_path().with_name(".env.global")
    legacy_app.parent.mkdir(parents=True)
    legacy_app.write_text("OLD=1\n", encoding="utf-8")

    payload = build_config_doctor_payload(kit, storage=None)

    assert any(".env.global" in warning for warning in payload.warnings)
    assert any(".env.local" in warning for warning in payload.warnings)


def test_doctor_named_storage_selector_uses_index(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    kit = build_apprc_example_app_kit()
    index_path = tmp_path / "index.toml"
    storage_root = tmp_path / "alpha"
    register_storage(
        name="alpha",
        root=storage_root,
        path=index_path,
        storage_env_filename=kit.spec.storage_env_filename,
    )
    monkeypatch.setenv("APPRC_EXAMPLE_APP_APPRC_TOML", str(index_path))
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", "alpha")

    payload = build_config_doctor_payload(kit, storage=None)

    assert payload.selected_storage == "alpha"
    assert payload.selected_storage_root == str(storage_root.resolve())


def test_doctor_payload_honors_explicit_selector_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    monkeypatch.delenv("APPRC_EXAMPLE_APP_APPRC_TOML", raising=False)
    monkeypatch.delenv("APPRC_EXAMPLE_APP_STORAGE", raising=False)
    kit = build_apprc_example_app_kit()
    index_path = tmp_path / "explicit-index.toml"
    storage_root = tmp_path / "alpha"
    register_storage(
        name="alpha",
        root=storage_root,
        path=index_path,
        storage_env_filename=kit.spec.storage_env_filename,
    )

    payload = build_config_doctor_payload(
        kit,
        storage=None,
        explicit_values={
            "APPRC_EXAMPLE_APP_APPRC_TOML": str(index_path),
            "APPRC_EXAMPLE_APP_STORAGE": "alpha",
        },
    )

    assert payload.status == ConfigDoctorStatus.RUNNABLE.value
    assert payload.index_path == str(index_path)
    assert payload.selected_storage == "alpha"
    assert payload.selected_storage_root == str(storage_root.resolve())


def test_selector_helpers_honor_explicit_storage_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    monkeypatch.delenv("APPRC_EXAMPLE_APP_APPRC_TOML", raising=False)
    monkeypatch.delenv("APPRC_EXAMPLE_APP_STORAGE", raising=False)
    kit = build_apprc_example_app_kit()
    index_path = tmp_path / "explicit-index.toml"
    storage_root = tmp_path / "alpha"
    registry = register_storage(
        name="alpha",
        root=storage_root,
        path=index_path,
        storage_env_filename=kit.spec.storage_env_filename,
    )
    explicit_values = {
        "APPRC_EXAMPLE_APP_APPRC_TOML": str(index_path),
        "APPRC_EXAMPLE_APP_STORAGE": "alpha",
    }

    assert (
        active_storage_root_from_env(
            kit,
            explicit_values=explicit_values,
        )
        == storage_root.resolve()
    )
    assert (
        initial_storage_from_state(
            kit,
            ApprcExampleAppConfigState(env_bootstrap=None, storage=None),
            registry,
            explicit_values=explicit_values,
        )
        == "alpha"
    )
