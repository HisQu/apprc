"""Doctor reports readiness, independent of application module layout."""

from pathlib import Path

import pytest

import apprc as rc
from apprc.interfaces.cli.diagnostics.payload import build_config_doctor_payload


def test_doctor_accepts_arbitrary_section_module_layout() -> None:
    app = rc.AppRC(app_id="doctor_test", display_name="Doctor test")

    @app.config("settings", prefix="DOCTOR_")
    class Settings(rc.Config):
        count: int = rc.field("DOCTOR_COUNT", default=1)

    payload = build_config_doctor_payload(app, storage=None)
    assert payload.status == "runnable"
    assert not payload.warnings


def test_doctor_reports_missing_resource_package_without_writes(
    tmp_path: Path,
) -> None:
    app = rc.AppRC(
        app_id="doctor_test",
        display_name="Doctor test",
        config_package="nonexistent_apprc_test_package",
        user_dotenv=rc.UserDotenv(),
        apprc_dir=tmp_path / "absent",
    )
    payload = build_config_doctor_payload(app, storage=None)
    assert any("packaged defaults" in issue for issue in payload.issues)
    assert payload.status == "config_invalid"
    assert not (tmp_path / "absent").exists()
    with pytest.raises(ModuleNotFoundError):
        app.resolve(environment={})


def test_doctor_reports_missing_required_values_without_echoing_secrets() -> (
    None
):
    app = rc.AppRC(app_id="doctor_fields", display_name="Doctor fields")

    @app.config("settings", prefix="DOCTOR_")
    class Settings(rc.Config):
        token: str = rc.field("DOCTOR_TOKEN", required=True, secret=True)

    payload = build_config_doctor_payload(
        app, storage=None, manager=app.manage(environment={})
    )
    assert payload.status == "config_invalid"
    assert payload.issues
