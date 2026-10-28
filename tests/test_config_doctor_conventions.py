from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

import apprc as rc
from apprc.definition.paths import Layout, Paths
from apprc.interfaces.cli.mount import mount_app_cli


def _doctor_app(
    tmp_path: Path,
    *,
    required_secret: bool = True,
) -> tuple[rc.AppRC, typer.Typer]:
    app_rc = rc.AppRC(
        app_id="doctor_configuration",
        paths=Paths(config=True),
        layout=Layout.single_root(tmp_path / "home"),
        user_dotenv=rc.UserDotenv(),
    )

    @app_rc.config("secrets", prefix="DOCTOR_CONFIGURATION_")
    class Settings(rc.Config):
        token: str = (
            rc.field("DOCTOR_CONFIGURATION_TOKEN", required=True, secret=True)
            if required_secret
            else rc.field("DOCTOR_CONFIGURATION_TOKEN", default="", secret=True)
        )

    app = typer.Typer()
    mount_app_cli(app, app_rc)
    return app_rc, app


def test_config_doctor_reports_missing_required_secret_without_writes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("DOCTOR_CONFIGURATION_TOKEN", raising=False)
    app_rc, app = _doctor_app(tmp_path)

    result = CliRunner().invoke(app, ["config", "doctor", "--json"])

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "error"
    assert any(
        check["status"] == "error"
        and "DOCTOR_CONFIGURATION_TOKEN" in check["message"]
        for check in payload["checks"]
    )
    assert "secret-value" not in result.output
    assert not app_rc.paths(environment={}).require("config").exists()


def test_config_doctor_reports_uninitialized_user_preferences_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app_rc, app = _doctor_app(tmp_path, required_secret=False)
    monkeypatch.setenv("DOCTOR_CONFIGURATION_TOKEN", "private-test-secret")

    result = CliRunner().invoke(app, ["config", "doctor", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "warning"
    assert "private-test-secret" not in result.output
    assert any(
        check["name"] == "user_dotenv" and check["status"] == "warning"
        for check in payload["checks"]
    )
    assert not app_rc.paths(environment={}).require("config").exists()
