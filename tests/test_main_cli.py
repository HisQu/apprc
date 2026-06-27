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
from tests.support_config import build_apprc_example_app_kit


@pytest.fixture(autouse=True)
def _isolate_apprc_example_app_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for key in tuple(os.environ):
        if key.startswith("APPRC_EXAMPLE_APP_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))


def _clear_process_apprc_example_app_env() -> None:
    """Remove Example App env values mutated by in-process CLI invocations."""
    for key in tuple(os.environ):
        if (
            key.startswith("APPRC_EXAMPLE_APP_")
            and key != "APPRC_EXAMPLE_APP_APPRC_TOML"
            and key != "APPRC_EXAMPLE_APP_STORAGE"
        ):
            del os.environ[key]


def test_standalone_cli_help_shows_config_command() -> None:
    result = CliRunner().invoke(app, ["--help"])

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


def test_demo_config_setup_uses_storage_only_route(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"

    result = CliRunner().invoke(
        app,
        [
            "--storage",
            str(storage_root),
            "config",
            "setup",
            "--yes",
            "--storage-root",
            str(storage_root),
        ],
    )

    assert result.exit_code == 0, result.output
    assert (storage_root / ".env.apprc-storage").is_file()
    assert "export APPRC_EXAMPLE_APP_STORAGE" in result.output
    assert "APPRC_EXAMPLE_APP_APPRC_TOML" not in result.output


def test_demo_config_set_and_show_payload(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    runner = CliRunner()
    setup_result = runner.invoke(
        app,
        [
            "--storage",
            str(storage_root),
            "config",
            "setup",
            "--yes",
            "--storage-root",
            str(storage_root),
        ],
    )
    assert setup_result.exit_code == 0, setup_result.output
    os.environ["APPRC_EXAMPLE_APP_STORAGE"] = str(storage_root)

    _clear_process_apprc_example_app_env()
    profile_result = runner.invoke(
        app,
        ["config", "set", "app.profile", "other-profile"],
    )
    _clear_process_apprc_example_app_env()
    token_result = runner.invoke(
        app,
        ["config", "set", "access_token", "secret-token"],
    )
    _clear_process_apprc_example_app_env()
    show_result = runner.invoke(app, ["config", "show", "--json"])

    assert profile_result.exit_code == 0, profile_result.output
    assert token_result.exit_code == 0, token_result.output
    assert show_result.exit_code == 0, show_result.output
    payload = json.loads(show_result.output)
    assert payload["bootstrap"]["storage_env"] == str(
        storage_root.resolve() / ".env.apprc-storage"
    )
    assert payload["config"]["profile"] == "other-profile"
    assert payload["config"]["access_token"] == "<redacted>"


def test_demo_root_env_file_option_before_config_show(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    (storage_root / ".env.apprc-storage").write_text(
        'APPRC_EXAMPLE_APP_ACCESS_TOKEN="secret-token"\n',
        encoding="utf-8",
    )
    os.environ["APPRC_EXAMPLE_APP_STORAGE"] = str(storage_root)
    env_file = tmp_path / "profile.env"
    env_file.write_text(
        'APPRC_EXAMPLE_APP_PROFILE="from-explicit"\n',
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        ["--env-file", str(env_file), "config", "show", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["config"]["profile"] == "from-explicit"


def test_command_name_falls_back_to_app_name() -> None:
    assert config_command_text(build_apprc_example_app_kit(), "show") == (
        "apprc_example_app config show"
    )
    assert (
        config_command_text(APPRC_EXAMPLE_APP_KIT, "show")
        == "apprc config show"
    )
