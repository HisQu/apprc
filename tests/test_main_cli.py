from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from apprc.runtime_config.doctor.payload import config_command_text
from apprc_example_app import APPRC_EXAMPLE_APP_KIT
from apprc_example_app.cli import app
from tests.support_config import build_apprc_example_app_kit

ROOT = Path(__file__).parents[1]


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


def _invoke_root_config(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    args: list[str],
) -> Result:
    """Invoke the example CLI with argv matching the Typer command tokens."""
    monkeypatch.setattr(sys, "argv", ["apprc", *args])
    return runner.invoke(app, args)


def _run_example_cli(
    args: list[str],
    tmp_path: Path,
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the example CLI in a fresh process with controlled env values."""
    process_env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("APPRC_EXAMPLE_APP_")
    }
    pythonpath = [
        str(ROOT / "examples" / "apprc_example_app" / "src"),
        str(ROOT / "src"),
    ]
    if process_env.get("PYTHONPATH"):
        pythonpath.append(process_env["PYTHONPATH"])
    process_env.update(
        {
            "PYTHONPATH": os.pathsep.join(pythonpath),
            "XDG_CONFIG_HOME": str(tmp_path / "config-home"),
        }
    )
    process_env.update(env or {})
    return subprocess.run(
        [sys.executable, "-m", "apprc_example_app.cli", *args],
        cwd=ROOT,
        env=process_env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_standalone_cli_help_shows_config_command() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0, result.output
    assert "config" in result.output
    assert "generated config CLI" in result.output


def test_real_cli_config_help_skips_runtime_bootstrap(tmp_path: Path) -> None:
    config_help = _run_example_cli(["config", "--help"], tmp_path)
    show_help = _run_example_cli(["config", "show", "--help"], tmp_path)

    assert config_help.returncode == 0, config_help.stderr
    assert show_help.returncode == 0, show_help.stderr
    assert "Usage:" in config_help.stdout
    assert "Usage:" in show_help.stdout


def test_real_cli_env_file_storage_selector_for_skipped_doctor_and_set(
    tmp_path: Path,
) -> None:
    storage_root = tmp_path / "selected-storage"
    storage_root.mkdir()
    (storage_root / ".env.apprc-storage").write_text("", encoding="utf-8")
    selector_env = tmp_path / "selector.env"
    selector_env.write_text(
        f"APPRC_EXAMPLE_APP_STORAGE={storage_root}\n",
        encoding="utf-8",
    )

    doctor = _run_example_cli(
        ["--env-file", str(selector_env), "config", "doctor", "--json"],
        tmp_path,
    )
    update = _run_example_cli(
        [
            "--env-file",
            str(selector_env),
            "config",
            "set",
            "access_token",
            "secret-token",
            "--scope",
            "storage",
        ],
        tmp_path,
    )

    assert doctor.returncode == 0, doctor.stderr
    payload = json.loads(doctor.stdout)
    assert payload["selected_storage_root"] == str(storage_root.resolve())
    assert update.returncode == 0, update.stderr
    assert 'APPRC_EXAMPLE_APP_ACCESS_TOKEN="secret-token"\n' in (
        storage_root / ".env.apprc-storage"
    ).read_text(encoding="utf-8")


def test_real_cli_env_file_override_policy_for_storage_selector(
    tmp_path: Path,
) -> None:
    shell_storage = tmp_path / "shell-storage"
    explicit_storage = tmp_path / "explicit-storage"
    shell_storage.mkdir()
    explicit_storage.mkdir()
    (shell_storage / ".env.apprc-storage").write_text("", encoding="utf-8")
    (explicit_storage / ".env.apprc-storage").write_text("", encoding="utf-8")
    selector_env = tmp_path / "selector.env"
    selector_env.write_text(
        f"APPRC_EXAMPLE_APP_STORAGE={explicit_storage}\n",
        encoding="utf-8",
    )
    exported_env = {"APPRC_EXAMPLE_APP_STORAGE": str(shell_storage)}

    exported_wins = _run_example_cli(
        ["--env-file", str(selector_env), "config", "doctor", "--json"],
        tmp_path,
        env=exported_env,
    )
    explicit_wins = _run_example_cli(
        [
            "--env-file",
            str(selector_env),
            "--env-file-overrides-os-environ",
            "config",
            "doctor",
            "--json",
        ],
        tmp_path,
        env=exported_env,
    )

    assert exported_wins.returncode == 0, exported_wins.stderr
    assert explicit_wins.returncode == 0, explicit_wins.stderr
    assert json.loads(exported_wins.stdout)["selected_storage_root"] == str(
        shell_storage.resolve()
    )
    assert json.loads(explicit_wins.stdout)["selected_storage_root"] == str(
        explicit_storage.resolve()
    )


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
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert pyproject["tool"]["uv"]["build-backend"]["module-name"] == "apprc"


def test_demo_package_is_dev_dependency_only() -> None:
    pyproject = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert pyproject["dependency-groups"]["demo"] == ["apprc_example_app"]
    assert {"include-group": "demo"} in pyproject["dependency-groups"]["dev"]
    assert pyproject["tool"]["uv"]["sources"]["apprc_example_app"] == {
        "path": "examples/apprc_example_app",
        "editable": True,
    }


def test_core_package_does_not_import_demo_package() -> None:
    core_files = (ROOT / "src" / "apprc").rglob("*.py")

    offenders = [
        path
        for path in core_files
        if "apprc_example_app" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_storage_modules_do_not_import_bootstrap_layer() -> None:
    storage_files = (
        ROOT / "src" / "apprc" / "runtime_config" / "storage"
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


def test_demo_root_config_app_init_and_set_skip_storage_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()

    init_result = _invoke_root_config(
        monkeypatch,
        runner,
        ["config", "app", "init"],
    )
    inferred_set = _invoke_root_config(
        monkeypatch,
        runner,
        ["config", "set", "app.profile", "implicit-app"],
    )
    scoped_set = _invoke_root_config(
        monkeypatch,
        runner,
        ["config", "set", "app.profile", "scoped-app", "--scope", "app"],
    )

    assert init_result.exit_code == 0, init_result.output
    assert inferred_set.exit_code == 0, inferred_set.output
    assert scoped_set.exit_code == 0, scoped_set.output
    app_wide_env = APPRC_EXAMPLE_APP_KIT.spec.app_wide_env_path()
    assert 'APPRC_EXAMPLE_APP_PROFILE="scoped-app"\n' in (
        app_wide_env.read_text(encoding="utf-8")
    )


def test_demo_root_config_storage_set_uses_root_storage_selector(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    runner = CliRunner()

    result = _invoke_root_config(
        monkeypatch,
        runner,
        [
            "--storage",
            str(storage_root),
            "config",
            "set",
            "access_token",
            "secret-token",
            "--scope",
            "storage",
        ],
    )

    assert result.exit_code == 0, result.output
    assert 'APPRC_EXAMPLE_APP_ACCESS_TOKEN="secret-token"\n' in (
        storage_root / ".env.apprc-storage"
    ).read_text(encoding="utf-8")


def test_demo_root_config_set_requires_scope_when_app_and_storage_active(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    runner = CliRunner()

    init_result = _invoke_root_config(
        monkeypatch,
        runner,
        ["config", "app", "init"],
    )
    ambiguous = _invoke_root_config(
        monkeypatch,
        runner,
        [
            "--storage",
            str(storage_root),
            "config",
            "set",
            "app.profile",
            "ambiguous",
        ],
    )

    assert init_result.exit_code == 0, init_result.output
    assert ambiguous.exit_code != 0
    assert "--scope app or --scope storage" in ambiguous.output


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
