from __future__ import annotations

from pathlib import Path

import pytest

from apprc.runtime_config.doctor.payload import build_config_doctor_payload
from apprc.runtime_config.doctor.status import ConfigDoctorStatus
from tests.support_config import build_apprc_example_app_kit


@pytest.mark.allow_missing_apprc_env
def test_config_doctor_reports_config_package_convention_warnings(
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

    assert payload["status"] == ConfigDoctorStatus.RUNNABLE.value
    assert any("prefer '<app>.config'" in issue for issue in payload["issues"])
    assert any(
        "ApprcExampleAppEnv lives" in issue for issue in payload["issues"]
    )
