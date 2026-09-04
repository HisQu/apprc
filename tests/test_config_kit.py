from __future__ import annotations

from pathlib import Path

import pytest

from apprc.definition.app_config.kit import AppConfigKit
from apprc.definition.app_config.storage import Storage
from apprc.runtime.diagnostics.payload import build_config_doctor_payload
from apprc.runtime.diagnostics.status import ConfigDoctorStatus
from apprc.user_files.storage_roots.registry import (
    StorageRecord,
    StorageRegistry,
    register_storage,
    write_storage_registry,
)
from tests.support_config import (
    ApprcExampleAppEnv,
    build_apprc_example_app_kit,
    build_storage_free_example_kit,
)


def test_direct_kit_declarations_control_storage_capability() -> None:
    assert build_storage_free_example_kit().spec.uses_storage() is False
    assert build_apprc_example_app_kit().spec.uses_storage() is True


def test_direct_kit_storage_values_are_preserved() -> None:
    storage = Storage(selector_env_key="DEMO_STORAGE")
    kit = AppConfigKit(
        app_id="demo",
        display_name="Demo",
        config_package="apprc",
        storage=storage,
    )

    assert kit.spec.require_storage() == storage


def test_kit_rejects_removed_capability_keywords() -> None:
    with pytest.raises(TypeError):
        AppConfigKit(
            app_id="demo",
            display_name="Demo",
            config_package="apprc",
            storage_mode="required",  # pyright: ignore[reportCallIssue]
        )


def test_doctor_reports_missing_user_dotenv_without_writing() -> None:
    kit = build_storage_free_example_kit()

    payload = build_config_doctor_payload(kit, storage=None)

    assert payload.status == ConfigDoctorStatus.USER_DOTENV_NOT_READY.value
    assert payload.user_dotenv_exists is False
    assert not Path(payload.user_dotenv).exists()
    assert payload.writes == "none"


def test_doctor_reports_selected_registered_storage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("APPRC_EXAMPLE_APP_APPRC_DIR", str(tmp_path / "apprc"))
    monkeypatch.delenv("APPRC_EXAMPLE_APP_STORAGE", raising=False)
    kit = build_apprc_example_app_kit()
    kit.spec.ensure_user_dotenv()
    storage_root = tmp_path / "alpha"
    register_storage(
        name="alpha",
        root=storage_root,
        path=kit.spec.preferred_apprc_toml_path(),
    )

    payload = build_config_doctor_payload(kit, storage=None)

    assert payload.status == ConfigDoctorStatus.RUNNABLE.value
    assert payload.configured_selected_storage == "alpha"
    assert payload.selected_storage == "alpha"
    assert payload.selected_storage_source == "apprc.toml selected_storage"
    assert payload.selected_storage_root == str(storage_root.resolve())


def test_doctor_reports_malformed_registry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("APPRC_EXAMPLE_APP_APPRC_DIR", str(tmp_path / "apprc"))
    monkeypatch.delenv("APPRC_EXAMPLE_APP_STORAGE", raising=False)
    kit = build_apprc_example_app_kit()
    kit.spec.ensure_user_dotenv()
    registry = kit.spec.preferred_apprc_toml_path()
    registry.write_text("[invalid", encoding="utf-8")

    payload = build_config_doctor_payload(kit, storage=None)

    assert payload.status == ConfigDoctorStatus.STORAGE_REGISTRY_NOT_READY.value
    assert payload.apprc_toml_parse_ok is False
    assert payload.apprc_toml_error is not None


def test_doctor_reports_storage_not_selected_without_missing_env_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("APPRC_EXAMPLE_APP_APPRC_DIR", str(tmp_path / "apprc"))
    monkeypatch.delenv("APPRC_EXAMPLE_APP_STORAGE", raising=False)
    kit = build_apprc_example_app_kit()
    kit.spec.ensure_user_dotenv()
    kit.spec.preferred_apprc_toml_path().write_text("", encoding="utf-8")

    payload = build_config_doctor_payload(kit, storage=None)

    assert payload.status == ConfigDoctorStatus.STORAGE_NOT_SELECTED.value
    assert "missing_env_keys" not in payload.to_payload()
    assert any("--storage NAME_OR_PATH" in issue for issue in payload.issues)
    assert any(
        "setup --yes --storage-root" in step for step in payload.next_steps
    )


def test_doctor_distinguishes_invalid_selector_from_missing_selection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("APPRC_EXAMPLE_APP_APPRC_DIR", str(tmp_path / "apprc"))
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", "missing")
    kit = build_apprc_example_app_kit()
    kit.spec.ensure_user_dotenv()
    storage_root = tmp_path / "alpha"
    register_storage(
        name="alpha",
        root=storage_root,
        path=kit.spec.preferred_apprc_toml_path(),
    )

    payload = build_config_doctor_payload(kit, storage=None)

    assert payload.status == ConfigDoctorStatus.STORAGE_NOT_READY.value
    assert any("missing" in issue for issue in payload.issues)
    assert all(
        "No storage is selected" not in issue for issue in payload.issues
    )
    assert payload.next_steps[0].startswith("Fix or unset")


def test_doctor_recommends_selecting_an_existing_storage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("APPRC_EXAMPLE_APP_APPRC_DIR", str(tmp_path / "apprc"))
    monkeypatch.delenv("APPRC_EXAMPLE_APP_STORAGE", raising=False)
    kit = build_apprc_example_app_kit()
    kit.spec.ensure_user_dotenv()
    storage_root = tmp_path / "alpha"
    storage_root.mkdir()
    (storage_root / "apprc.storage.env").write_text("", encoding="utf-8")
    registry_path = kit.spec.preferred_apprc_toml_path()
    write_storage_registry(
        StorageRegistry(
            path=registry_path,
            storages={"alpha": StorageRecord(name="alpha", root=storage_root)},
            selected_storage=None,
            archived_storages={},
        )
    )

    payload = build_config_doctor_payload(kit, storage=None)

    assert payload.status == ConfigDoctorStatus.STORAGE_NOT_SELECTED.value
    assert payload.storage_count == 1
    assert "storage select NAME" in payload.next_steps[0]


def test_disk_registry_never_enables_storage_for_storage_free_app(
    tmp_path: Path,
) -> None:
    kit = AppConfigKit(
        app_id="config_only",
        display_name="Config Only",
        config_package="apprc",
        envs=(ApprcExampleAppEnv,),
        apprc_dir=tmp_path / "apprc",
    )
    kit.spec.ensure_user_dotenv()
    registry = kit.spec.preferred_apprc_toml_path()
    registry.write_text(
        'selected_storage = "alpha"\n\n[storages.alpha]\nroot = "storage"\n',
        encoding="utf-8",
    )

    payload = build_config_doctor_payload(kit, storage=None)

    assert payload.storage_enabled is False
    assert payload.selected_storage is None
    assert any(
        "stale storage" in warning.lower() for warning in payload.warnings
    )
