from __future__ import annotations

from pathlib import Path

import pytest

from apprc.definition.app_config.kit import AppConfigKit
from apprc.definition.app_config.storage import Storage
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
    monkeypatch.setenv("APPRC_EXAMPLE_APP_APPRC_DIR", str(tmp_path / "apprc"))
    storage_root = tmp_path / "alpha"
    storage_root.mkdir()
    kit = build_apprc_example_app_kit()
    kit.spec.ensure_user_dotenv()
    from apprc.user_files.storage_roots.registry import register_storage

    register_storage(
        name="alpha",
        root=storage_root,
        path=kit.spec.preferred_apprc_toml_path(),
    )
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", "alpha")

    payload = build_config_doctor_payload(kit, storage=None)

    assert payload.status == ConfigDoctorStatus.RUNNABLE.value
    assert payload.issues == ()
    assert any(
        "ApprcExampleAppEnv lives" in warning for warning in payload.warnings
    )


def test_config_package_convention_warns_when_package_is_not_config() -> None:
    kit = AppConfigKit(
        app_id="apprc_example_app",
        display_name="Example App",
        config_package="config_with_storage",
        envs=(),
        storage=Storage(selector_env_key="APPRC_EXAMPLE_APP_STORAGE"),
    )

    warnings = config_package_convention_warnings(kit)

    assert any("prefer '<app>.config'" in warning for warning in warnings)


@pytest.mark.allow_missing_apprc_env
def test_config_doctor_reports_missing_user_dotenv_as_issue(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("APPRC_EXAMPLE_APP_APPRC_DIR", str(tmp_path / "apprc"))
    kit = AppConfigKit(
        app_id="apprc_example_app",
        display_name="Example App",
        config_package="missing_app.config",
        envs=(ApprcExampleAppEnv,),
    )

    payload = build_config_doctor_payload(kit, storage=None)

    assert payload.status == ConfigDoctorStatus.USER_DOTENV_NOT_READY.value
    assert any(
        "User dotenv file does not exist" in issue for issue in payload.issues
    )


@pytest.mark.allow_missing_apprc_env
def test_config_doctor_reports_a_missing_registry_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Avoid repeating one missing registry through two diagnostic layers.

    :param monkeypatch: Process environment mutation fixture.
    :param tmp_path: Isolated absent AppRC directory.
    """
    monkeypatch.setenv("APPRC_EXAMPLE_APP_APPRC_DIR", str(tmp_path / "apprc"))
    kit = build_apprc_example_app_kit()

    payload = build_config_doctor_payload(kit, storage=None)

    matching_issues = [
        issue
        for issue in payload.issues
        if issue.startswith("Storage registry does not exist:")
    ]
    assert len(matching_issues) == 1
