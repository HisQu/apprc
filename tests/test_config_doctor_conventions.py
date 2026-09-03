from __future__ import annotations

from pathlib import Path

import pytest

from apprc.definition.app_config.kit import AppConfigKit
from apprc.runtime.diagnostics._diagnosis import (
    config_package_convention_warnings,
)
from apprc.runtime.diagnostics.payload import build_config_doctor_payload
from apprc.runtime.diagnostics.status import ConfigDoctorStatus
from tests.support_config import (
    ApprcExampleAppEnv,
    build_apprc_example_app_kit,
)


@pytest.mark.allow_missing_apprc_env
def test_config_doctor_reports_config_package_convention_warnings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("APPRC_EXAMPLE_APP_APPRC_TOML", raising=False)
    storage_root = tmp_path / "alpha"
    storage_root.mkdir()
    (storage_root / ".env.apprc-storage").write_text("", encoding="utf-8")
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", str(storage_root))
    kit = build_apprc_example_app_kit()

    payload = build_config_doctor_payload(kit, storage=None)

    assert payload.status == ConfigDoctorStatus.RUNNABLE.value
    assert payload.issues == ()
    assert any(
        "ApprcExampleAppEnv lives" in warning for warning in payload.warnings
    )


def test_config_package_convention_warns_when_package_is_not_config() -> None:
    kit = AppConfigKit.storage_only(
        app_name="apprc_example_app",
        display_name="Example App",
        config_package="config_with_storage",
        envs=(),
        storage_env_key="APPRC_EXAMPLE_APP_STORAGE",
    )

    warnings = config_package_convention_warnings(kit)

    assert any("prefer '<app>.config'" in warning for warning in warnings)


@pytest.mark.allow_missing_apprc_env
def test_config_doctor_reports_unreadable_config_package_as_issue(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("APPRC_EXAMPLE_APP_APPRC_TOML", raising=False)
    storage_root = tmp_path / "alpha"
    storage_root.mkdir()
    (storage_root / ".env.apprc-storage").write_text("", encoding="utf-8")
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", str(storage_root))
    kit = AppConfigKit.storage_only(
        app_name="apprc_example_app",
        display_name="Example App",
        config_package="missing_app.config",
        envs=(ApprcExampleAppEnv,),
        storage_env_key="APPRC_EXAMPLE_APP_STORAGE",
    )

    payload = build_config_doctor_payload(kit, storage=None)

    assert payload.status == ConfigDoctorStatus.STORAGE_NOT_READY.value
    assert any(
        "Packaged defaults env could not be read" in issue
        for issue in payload.issues
    )
