from __future__ import annotations

import ast
import json
import os
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apprc.runtime_config.doctor.payload import config_command_text
from apprc_example_app import APPRC_EXAMPLE_APP_KIT
from apprc_example_app.cli import app
from tests.support_config import (
    assert_config_home_cli_error,
    block_config_home_with_file,
    build_apprc_example_app_kit,
    set_apprc_example_app_bootstrap,
)


pytestmark = [pytest.mark.requires_apprc_env("APPRC_EXAMPLE_APP")]


@pytest.fixture(autouse=True)
def _isolate_apprc_example_app_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for key in tuple(os.environ):
        if key.startswith("APPRC_EXAMPLE_APP_"):
            monkeypatch.delenv(key, raising=False)
    set_apprc_example_app_bootstrap(monkeypatch, tmp_path)


def _clear_process_apprc_example_app_env() -> None:
    """Remove Example App env values mutated by in-process CLI invocations."""
    for key in tuple(os.environ):
        if (
            key.startswith("APPRC_EXAMPLE_APP_")
            and key != "APPRC_EXAMPLE_APP_APPRC_TOML"
            and key != "APPRC_EXAMPLE_APP_STORAGE"
        ):
            del os.environ[key]


def _set_demo_apprc_toml(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Path:
    """Point the demo CLI at a test AppRC TOML file."""
    apprc_toml_path, _ = set_apprc_example_app_bootstrap(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        apprc_toml=tmp_path
        / "config"
        / "apprc_example_app"
        / "apprc_example_app.apprc.toml",
    )
    return apprc_toml_path


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
        (root / "examples" / "apprc_example_app" / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )

    assert "scripts" not in root_pyproject["project"]
    assert (
        demo_pyproject["project"]["scripts"]["apprc"]
        == "apprc_example_app.cli:main"
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

    assert pyproject["dependency-groups"]["demo"] == ["apprc_example_app"]
    assert {"include-group": "demo"} in pyproject["dependency-groups"]["dev"]
    assert pyproject["tool"]["uv"]["sources"]["apprc_example_app"] == {
        "path": "examples/apprc_example_app",
        "editable": True,
    }


def test_core_package_does_not_import_demo_package() -> None:
    core_files = (Path(__file__).parents[1] / "src" / "apprc").rglob("*.py")

    offenders = [
        path
        for path in core_files
        if "apprc_example_app" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_storage_modules_do_not_import_bootstrap_layer() -> None:
    storage_files = (
        Path(__file__).parents[1]
        / "src"
        / "apprc"
        / "runtime_config"
        / "storage"
    ).rglob("*.py")

    offenders = [
        path
        for path in storage_files
        if _imports_runtime_config_bootstrap(path)
    ]
    assert offenders == []


def _imports_runtime_config_bootstrap(path: Path) -> bool:
    """Return whether one Python file imports the bootstrap package.

    :param path: Python source file to inspect.
    :return: Whether it imports ``apprc.runtime_config.bootstrap``.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            if node.module.startswith("apprc.runtime_config.bootstrap"):
                return True
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("apprc.runtime_config.bootstrap"):
                    return True
    return False


def test_demo_config_setup_accepts_quickstart_storage_export_and_command_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("APPRC_EXAMPLE_APP_APPRC_TOML", raising=False)
    storage_root = tmp_path / ".demo" / "storage"
    monkeypatch.setenv(
        "APPRC_EXAMPLE_APP_STORAGE",
        str(storage_root.resolve()),
    )
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "config",
            "setup",
            "--yes",
            "--storage-root",
            os.environ["APPRC_EXAMPLE_APP_STORAGE"],
        ],
    )

    assert result.exit_code == 0, result.output
    assert APPRC_EXAMPLE_APP_KIT.spec.optional_apprc_toml_path().is_file()
    assert (storage_root / ".env.apprc_example_app").is_file()
    assert "export APPRC_EXAMPLE_APP_APPRC_TOML" not in result.output
    assert (
        f'export APPRC_EXAMPLE_APP_STORAGE="{storage_root.resolve()}"'
        in result.output
    )
    assert "apprc config edit" in result.output
    assert "apprc config show" in result.output
    assert "apprc config doctor" in result.output
    assert "apprc_example_app config" not in result.output


def test_demo_root_bootstrap_reports_config_home_error() -> None:
    block_config_home_with_file(APPRC_EXAMPLE_APP_KIT)
    runner = CliRunner()

    result = runner.invoke(app, ["config", "show"])

    assert_config_home_cli_error(result)


def test_demo_root_bootstrap_reports_env_file_read_error(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / "unreadable.env"
    env_file.write_text(
        'APPRC_EXAMPLE_APP_PROFILE="explicit"\n',
        encoding="utf-8",
    )
    env_file.chmod(0)
    runner = CliRunner()

    try:
        result = runner.invoke(
            app,
            ["--env-file", str(env_file), "config", "show"],
        )
    finally:
        env_file.chmod(0o600)

    assert result.exit_code == 2, result.output
    assert "--env-file" in result.output
    assert "config-home" not in result.output
    assert "PermissionError" not in result.output


def test_demo_config_set_and_show_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("APPRC_EXAMPLE_APP_APPRC_TOML", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv(
        "APPRC_EXAMPLE_APP_STORAGE",
        str(
            (
                tmp_path
                / "data"
                / "apprc_example_app"
                / "apprc_example_app_stor-1"
            ).resolve()
        ),
    )
    runner = CliRunner()

    setup_result = runner.invoke(app, ["config", "setup", "--yes"])
    assert setup_result.exit_code == 0, setup_result.output

    _clear_process_apprc_example_app_env()
    model_result = runner.invoke(
        app,
        ["config", "set", "app.profile", "other-profile"],
    )
    assert model_result.exit_code == 0, model_result.output

    _clear_process_apprc_example_app_env()
    retry_result = runner.invoke(app, ["config", "set", "retry_count", "5"])
    assert retry_result.exit_code == 0, retry_result.output

    _clear_process_apprc_example_app_env()
    token_result = runner.invoke(
        app,
        ["config", "set", "access_token", "secret-token"],
    )
    assert token_result.exit_code == 0, token_result.output

    _clear_process_apprc_example_app_env()
    show_result = runner.invoke(app, ["config", "show", "--json"])

    payload = json.loads(show_result.output)
    storage_root = (
        tmp_path / "data" / "apprc_example_app" / "apprc_example_app_stor-1"
    )
    assert show_result.exit_code == 0, show_result.output
    assert payload["app_name"] == "apprc_example_app"
    assert payload["command_name"] == "apprc"
    assert payload["bootstrap"]["storage_root"] == str(storage_root.resolve())
    assert payload["config"]["profile"] == "other-profile"
    assert payload["config"]["retry_count"] == 5
    assert payload["config"]["access_token"] == "<redacted>"


def test_demo_root_env_file_option_before_config_show(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("APPRC_EXAMPLE_APP_APPRC_TOML", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv(
        "APPRC_EXAMPLE_APP_STORAGE",
        str(
            (
                tmp_path
                / "data"
                / "apprc_example_app"
                / "apprc_example_app_stor-1"
            ).resolve()
        ),
    )
    first_env = tmp_path / "first.env"
    first_env.write_text(
        'APPRC_EXAMPLE_APP_PROFILE="first-profile"\n',
        encoding="utf-8",
    )
    second_env = tmp_path / "second.env"
    second_env.write_text(
        'APPRC_EXAMPLE_APP_PROFILE="second-profile"\n',
        encoding="utf-8",
    )
    runner = CliRunner()
    setup_result = runner.invoke(app, ["config", "setup", "--yes"])
    assert setup_result.exit_code == 0, setup_result.output

    _clear_process_apprc_example_app_env()
    result = runner.invoke(
        app,
        [
            "--env-file",
            str(first_env),
            "--env-file",
            str(second_env),
            "config",
            "show",
            "--json",
        ],
    )

    payload = json.loads(result.output)
    assert result.exit_code == 0, result.output
    assert payload["config"]["profile"] == "second-profile"


def test_command_name_falls_back_to_app_name() -> None:
    assert config_command_text(build_apprc_example_app_kit(), "show") == (
        "apprc_example_app config show"
    )
    assert (
        config_command_text(APPRC_EXAMPLE_APP_KIT, "show")
        == "apprc config show"
    )
