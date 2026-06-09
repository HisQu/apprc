from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apprc.cli.doctor import config_command_text
from apprc_demo import APPRC_DEMO_KIT
from apprc_demo.cli import app
from tests.support_config import build_demo_kit


@pytest.fixture(autouse=True)
def _isolate_apprc_demo_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in tuple(os.environ):
        if key.startswith("APPRC_DEMO_"):
            monkeypatch.delenv(key, raising=False)


def _clear_process_demo_env() -> None:
    """Remove demo env values mutated by in-process CLI invocations."""
    for key in tuple(os.environ):
        if key.startswith("APPRC_DEMO_"):
            del os.environ[key]


def test_standalone_cli_help_shows_config_command() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0, result.output
    assert "config" in result.output
    assert "generated config CLI" in result.output


def test_console_script_points_to_demo_cli() -> None:
    root = Path(__file__).parents[1]
    root_pyproject = tomllib.loads(
        (root / "pyproject.toml").read_text(encoding="utf-8")
    )
    demo_pyproject = tomllib.loads(
        (root / "examples" / "apprc_demo" / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )

    assert "scripts" not in root_pyproject["project"]
    assert (
        demo_pyproject["project"]["scripts"]["apprc"] == "apprc_demo.cli:main"
    )


def test_build_backend_packages_only_library_in_root_wheel() -> None:
    pyproject = tomllib.loads(
        (Path(__file__).parents[1] / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )

    assert pyproject["tool"]["uv"]["build-backend"]["module-name"] == "apprc"


def test_demo_package_is_dev_dependency_only() -> None:
    pyproject = tomllib.loads(
        (Path(__file__).parents[1] / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )

    assert pyproject["dependency-groups"]["demo"] == ["apprc-demo"]
    assert {"include-group": "demo"} in pyproject["dependency-groups"]["dev"]
    assert pyproject["tool"]["uv"]["sources"]["apprc-demo"] == {
        "path": "examples/apprc_demo",
        "editable": True,
    }


def test_core_package_does_not_import_demo_package() -> None:
    core_files = (Path(__file__).parents[1] / "src" / "apprc").rglob("*.py")

    offenders = [
        path
        for path in core_files
        if "apprc_demo" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_demo_config_setup_uses_demo_paths_and_apprc_command_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    runner = CliRunner()

    result = runner.invoke(app, ["config", "setup", "--yes"])

    storage_root = tmp_path / "data" / "apprc-demo" / "apprc-demo_stor-1"
    registry = APPRC_DEMO_KIT.load_registry()
    assert result.exit_code == 0, result.output
    assert registry.path == (
        tmp_path / "config" / "apprc-demo" / "apprc-demo.toml"
    )
    assert registry.default_storage == "apprc-demo_stor-1"
    assert registry.selected("apprc-demo_stor-1").root == (
        storage_root.resolve()
    )
    assert (storage_root / ".env.apprc-demo").is_file()
    assert "apprc config edit" in result.output
    assert "apprc config show" in result.output
    assert "apprc config doctor" in result.output
    assert "apprc-demo config" not in result.output


def test_demo_config_set_and_show_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    runner = CliRunner()

    setup_result = runner.invoke(app, ["config", "setup", "--yes"])
    assert setup_result.exit_code == 0, setup_result.output

    _clear_process_demo_env()
    model_result = runner.invoke(
        app,
        ["config", "set", "runtime.model", "other-model"],
    )
    assert model_result.exit_code == 0, model_result.output

    _clear_process_demo_env()
    retry_result = runner.invoke(app, ["config", "set", "retry_count", "5"])
    assert retry_result.exit_code == 0, retry_result.output

    _clear_process_demo_env()
    token_result = runner.invoke(
        app,
        ["config", "set", "api_token", "secret-token"],
    )
    assert token_result.exit_code == 0, token_result.output

    _clear_process_demo_env()
    show_result = runner.invoke(app, ["config", "show", "--json"])

    payload = json.loads(show_result.output)
    storage_root = tmp_path / "data" / "apprc-demo" / "apprc-demo_stor-1"
    assert show_result.exit_code == 0, show_result.output
    assert payload["app_name"] == "apprc-demo"
    assert payload["command_name"] == "apprc"
    assert payload["bootstrap"]["storage_root"] == str(storage_root.resolve())
    assert payload["runtime"]["model"] == "other-model"
    assert payload["runtime"]["retry_count"] == 5
    assert payload["runtime"]["api_token"] == "<redacted>"


def test_demo_root_env_file_option_before_config_show(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    explicit_env = tmp_path / "override.env"
    explicit_env.write_text(
        'APPRC_DEMO_MODEL="explicit-model"\n',
        encoding="utf-8",
    )
    runner = CliRunner()
    setup_result = runner.invoke(app, ["config", "setup", "--yes"])
    assert setup_result.exit_code == 0, setup_result.output

    _clear_process_demo_env()
    result = runner.invoke(
        app,
        ["--env-file", str(explicit_env), "config", "show", "--json"],
    )

    payload = json.loads(result.output)
    assert result.exit_code == 0, result.output
    assert payload["runtime"]["model"] == "explicit-model"


def test_command_name_falls_back_to_app_name() -> None:
    assert config_command_text(build_demo_kit(), "show") == "demo config show"
    assert config_command_text(APPRC_DEMO_KIT, "show") == "apprc config show"
