from __future__ import annotations

from pathlib import Path

import pytest

from apprc.runtime_config.app_spec import CapabilityState, StorageLayerState
from apprc.runtime_config.doctor.payload import build_config_doctor_payload
from apprc.runtime_config.doctor.status import ConfigDoctorStatus
from apprc.runtime_config.kit import AppConfigKit
from apprc.runtime_config.storage.registry import register_storage
from tests.support_config import (
    ApprcExampleAppEnv,
    StorageFreeExampleEnv,
    build_apprc_example_app_kit,
    build_storage_free_example_kit,
)


def test_kit_constructors_declare_expected_capabilities() -> None:
    env_only = AppConfigKit.env_only(
        app_name="env_app",
        display_name="Env App",
        config_package="apprc.runtime_config",
        envs=(StorageFreeExampleEnv,),
    )
    storage_only = build_apprc_example_app_kit()
    app_wide = build_storage_free_example_kit()
    app_wide_storage = AppConfigKit.app_wide_storage(
        app_name="wide_storage",
        display_name="Wide Storage",
        config_package="apprc.runtime_config",
        envs=(ApprcExampleAppEnv,),
    )

    assert env_only.spec.storage_layer == StorageLayerState.DISABLED
    assert env_only.spec.app_wide_layer == CapabilityState.OPTIONAL
    assert env_only.spec.named_storage_layer == CapabilityState.DISABLED
    assert storage_only.spec.storage_layer == StorageLayerState.REQUIRED
    assert storage_only.spec.app_wide_layer == CapabilityState.OPTIONAL
    assert storage_only.spec.named_storage_layer == CapabilityState.OPTIONAL
    assert app_wide.spec.app_wide_layer == CapabilityState.DEFAULT
    assert app_wide_storage.spec.storage_layer == StorageLayerState.REQUIRED
    assert app_wide_storage.spec.app_wide_layer == CapabilityState.DEFAULT


def test_kit_rejects_removed_storage_mode_keyword() -> None:
    with pytest.raises(TypeError):
        AppConfigKit(
            app_name="demo",
            display_name="Demo",
            config_package="apprc.runtime_config",
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

    assert payload["status"] == ConfigDoctorStatus.ENV_NOT_SET.value
    assert payload["missing_env_keys"] == ["APPRC_EXAMPLE_APP_STORAGE"]
    assert not kit.spec.app_wide_env_path().exists()
    assert not kit.spec.index_path().exists()


def test_doctor_app_config_not_ready_for_default_app_wide_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    kit = build_storage_free_example_kit()

    payload = build_config_doctor_payload(kit, storage=None)

    assert payload["status"] == ConfigDoctorStatus.APP_CONFIG_NOT_READY.value
    assert payload["app_wide_env_exists"] is False


def test_doctor_named_storage_not_ready_for_bad_index(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", "alpha")
    kit = build_apprc_example_app_kit()
    index_path = kit.spec.index_path()
    index_path.parent.mkdir(parents=True)
    index_path.write_text("[invalid", encoding="utf-8")

    payload = build_config_doctor_payload(kit, storage=None)

    assert payload["status"] == ConfigDoctorStatus.NAMED_STORAGE_NOT_READY.value
    assert payload["index_parse_ok"] is False
    assert payload["index_error"] is not None


def test_doctor_warns_about_bad_optional_index_for_path_selector(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    (storage_root / ".env.apprc-storage").write_text("", encoding="utf-8")
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", str(storage_root))
    kit = build_apprc_example_app_kit()
    index_path = kit.spec.index_path()
    index_path.parent.mkdir(parents=True)
    index_path.write_text("[invalid", encoding="utf-8")

    payload = build_config_doctor_payload(kit, storage=None)

    assert payload["status"] == ConfigDoctorStatus.RUNNABLE.value
    assert payload["index_parse_ok"] is False
    assert any(
        "Named-storage index is invalid" in warning
        for warning in payload["warnings"]
    )


def test_doctor_ignores_bad_disabled_named_storage_index(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    (storage_root / ".env.apprc-storage").write_text("", encoding="utf-8")
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", str(storage_root))
    kit = AppConfigKit(
        app_name="apprc_example_app",
        display_name="Example App",
        config_package="apprc.runtime_config",
        envs=(ApprcExampleAppEnv,),
        storage_env_key="APPRC_EXAMPLE_APP_STORAGE",
        storage_layer=StorageLayerState.REQUIRED,
        named_storage_layer=CapabilityState.DISABLED,
        index_filename="apprc_example_app.apprc.toml",
    )
    index_path = kit.spec.index_path()
    index_path.parent.mkdir(parents=True)
    index_path.write_text("[invalid", encoding="utf-8")

    payload = build_config_doctor_payload(kit, storage=None)

    assert payload["status"] == ConfigDoctorStatus.RUNNABLE.value
    assert payload["index_parse_ok"] is True
    assert any(
        "layer is disabled" in warning for warning in payload["warnings"]
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

    assert payload["status"] == ConfigDoctorStatus.STORAGE_NOT_READY.value
    assert payload["selected_storage_env_exists"] is False


def test_doctor_runnable_for_storage_with_storage_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    (storage_root / ".env.apprc-storage").write_text("", encoding="utf-8")
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", str(storage_root))
    kit = build_apprc_example_app_kit()

    payload = build_config_doctor_payload(kit, storage=None)

    assert payload["status"] == ConfigDoctorStatus.RUNNABLE.value


def test_doctor_warns_about_legacy_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    (storage_root / ".env.apprc-storage").write_text("", encoding="utf-8")
    (storage_root / ".env.local").write_text("OLD=1\n", encoding="utf-8")
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", str(storage_root))
    kit = build_apprc_example_app_kit()
    legacy_app = kit.spec.app_wide_env_path().with_name(".env.global")
    legacy_app.parent.mkdir(parents=True)
    legacy_app.write_text("OLD=1\n", encoding="utf-8")

    payload = build_config_doctor_payload(kit, storage=None)

    assert any(".env.global" in warning for warning in payload["warnings"])
    assert any(".env.local" in warning for warning in payload["warnings"])


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

    assert payload["selected_storage"] == "alpha"
    assert payload["selected_storage_root"] == str(storage_root.resolve())
