from __future__ import annotations

import ast
import json
import os
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import pytest
import typer
from typer.testing import CliRunner, Result

import apprc
from apprc_app_wide_config_example import cli as app_wide_config
from apprc_app_wide_config_example.config import KIT as APP_WIDE_CONFIG_KIT
from apprc_app_wide_storage_example import cli as app_wide_storage
from apprc_app_wide_storage_example.config import KIT as APP_WIDE_STORAGE_KIT
from apprc_cli_bridge_example import cli as cli_bridge
from apprc_cli_bridge_example.config import KIT as BRIDGE_KIT
from apprc_env_only_example import cli as env_only
from apprc_env_only_example.config import KIT as ENV_ONLY_KIT
from apprc_explicit_env_precedence_example import (
    cli as explicit_env_precedence,
)
from apprc_explicit_env_precedence_example.config import (
    KIT as EXPLICIT_ENV_PRECEDENCE_KIT,
)
from apprc.runtime.diagnostics.messages import config_command_text
from apprc_storage_only_example import cli as storage_only
from apprc_storage_only_example.config import KIT as STORAGE_ONLY_KIT
from apprc_dev.example_apps.bootstrap import bootstrap_example_apps
from tests.support_config import build_apprc_example_app_kit

ROOT = Path(__file__).parents[1]


class HeadlessConfigEditorApp(apprc.ConfigEditorApp):
    """Test editor that records launch state without starting Textual."""

    run_count: ClassVar[int] = 0

    @classmethod
    def reset(cls) -> None:
        """Clear recorded launch state."""
        cls.run_count = 0

    def run(self, *args: object, **kwargs: object) -> None:
        """Record that the editor would have launched."""
        type(self).run_count += 1


@dataclass(frozen=True, slots=True)
class ExampleCliDefinition:
    """One example CLI and the command data needed to exercise it."""

    mode: str
    command_name: str
    kit: apprc.AppConfigKit
    build_app: Callable[..., typer.Typer]
    app_key: str
    app_value: str
    storage_key: str | None = None
    storage_value: str | None = None
    bridge: bool = False

    @property
    def uses_storage(self) -> bool:
        """Return whether this example mounts storage commands."""
        return self.kit.spec.storage_required()


EXAMPLE_CLIS = (
    ExampleCliDefinition(
        mode="env_only",
        command_name="apprc-env-only",
        kit=ENV_ONLY_KIT,
        build_app=env_only.build_app,
        app_key="profile",
        app_value="env-only-app-profile",
    ),
    ExampleCliDefinition(
        mode="storage_only",
        command_name="apprc-storage-only",
        kit=STORAGE_ONLY_KIT,
        build_app=storage_only.build_app,
        app_key="profile",
        app_value="storage-only-app-profile",
        storage_key="api_token",
        storage_value="storage-only-secret",
    ),
    ExampleCliDefinition(
        mode="app_wide_config",
        command_name="apprc-app-wide-config",
        kit=APP_WIDE_CONFIG_KIT,
        build_app=app_wide_config.build_app,
        app_key="region",
        app_value="app-wide-region",
    ),
    ExampleCliDefinition(
        mode="app_wide_storage",
        command_name="apprc-app-wide-storage",
        kit=APP_WIDE_STORAGE_KIT,
        build_app=app_wide_storage.build_app,
        app_key="region",
        app_value="app-wide-storage-region",
        storage_key="access_token",
        storage_value="app-wide-storage-secret",
    ),
    ExampleCliDefinition(
        mode="explicit_env_precedence",
        command_name="apprc-explicit-env-precedence",
        kit=EXPLICIT_ENV_PRECEDENCE_KIT,
        build_app=explicit_env_precedence.build_app,
        app_key="label",
        app_value="precedence-app-label",
        storage_key="label",
        storage_value="precedence-storage-label",
    ),
    ExampleCliDefinition(
        mode="cli_bridge",
        command_name="apprc-cli-bridge",
        kit=BRIDGE_KIT,
        build_app=cli_bridge.build_app,
        app_key="profile",
        app_value="bridge-app-profile",
        storage_key="api_token",
        storage_value="bridge-secret",
        bridge=True,
    ),
)


@pytest.fixture(autouse=True)
def _isolate_example_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Remove example env values and isolate platform config paths."""
    for key in tuple(os.environ):
        if key.startswith("APPRC_EXAMPLE_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))


class ExampleCliHarness:
    """Small invoker that keeps AppRC's args provider aligned with Typer."""

    def __init__(self, definition: ExampleCliDefinition) -> None:
        """Build one test CLI app for a definition."""
        self.definition = definition
        self.current_args: list[str] = []
        self.runner = CliRunner()
        self.app = definition.build_app(
            args_provider=lambda: self.current_args,
            editor_app_cls=HeadlessConfigEditorApp,
        )

    def invoke(
        self,
        args: list[str],
        *,
        env: dict[str, str] | None = None,
    ) -> Result:
        """Invoke the example CLI with matching skip-policy tokens."""
        self.current_args = args
        return self.runner.invoke(
            self.app,
            args,
            env=env,
            prog_name=self.definition.command_name,
        )


@pytest.mark.parametrize("definition", EXAMPLE_CLIS, ids=lambda item: item.mode)
def test_example_cli_runs_every_supported_config_command(
    definition: ExampleCliDefinition,
    tmp_path: Path,
) -> None:
    harness = ExampleCliHarness(definition)
    storage_root = tmp_path / definition.mode / "active-storage"
    named_storage = tmp_path / definition.mode / "named-storage"

    _assert_success(harness.invoke(["--help"]))
    _assert_success(harness.invoke(["config", "--help"]))
    _assert_success(harness.invoke(["config", "paths"]))
    paths_json = _assert_json_success(
        harness.invoke(["--log-level", "INFO", "config", "paths", "--json"])
    )
    assert str(paths_json["config_home"]).endswith(definition.kit.spec.app_name)

    setup_args = ["config", "setup", "--yes"]
    if definition.uses_storage:
        setup_args.extend(["--storage-root", str(storage_root)])
    _assert_success(harness.invoke(setup_args))
    _assert_success(harness.invoke(["config", "app", "init"]))

    if definition.uses_storage:
        _assert_success(
            harness.invoke(
                [
                    "config",
                    "storage",
                    "add",
                    "alpha",
                    str(named_storage),
                    "--yes",
                ]
            )
        )
        _assert_success(harness.invoke(["config", "storage", "list"]))
        storage_list = _assert_json_success(
            harness.invoke(["config", "storage", "list", "--json"])
        )
        storages = storage_list["storages"]
        assert isinstance(storages, list)
        first_storage = storages[0]
        assert isinstance(first_storage, dict)
        assert first_storage["name"] == "alpha"
        _assert_success(
            harness.invoke(["config", "storage", "remove", "alpha"])
        )

        assert definition.storage_key is not None
        assert definition.storage_value is not None
        storage_prefix = ["--storage", str(storage_root)]
        _assert_success(
            harness.invoke(
                [
                    *storage_prefix,
                    "config",
                    "set",
                    definition.storage_key,
                    definition.storage_value,
                    "--scope",
                    "storage",
                ]
            )
        )
        _assert_success(
            harness.invoke(
                [
                    *storage_prefix,
                    "config",
                    "set",
                    definition.app_key,
                    definition.app_value,
                    "--scope",
                    "app",
                ]
            )
        )
        runtime_prefix = storage_prefix
    else:
        unavailable = harness.invoke(["config", "storage", "list"])
        assert unavailable.exit_code != 0
        _assert_success(
            harness.invoke(
                [
                    "config",
                    "set",
                    definition.app_key,
                    definition.app_value,
                    "--scope",
                    "app",
                ]
            )
        )
        runtime_prefix = []

    _assert_success(harness.invoke([*runtime_prefix, "config", "doctor"]))
    doctor_json = _assert_json_success(
        harness.invoke([*runtime_prefix, "config", "doctor", "--json"])
    )
    assert doctor_json["status"] == "runnable"

    _assert_success(harness.invoke([*runtime_prefix, "config", "show"]))
    show_json = _assert_json_success(
        harness.invoke([*runtime_prefix, "config", "show", "--json"])
    )
    assert show_json["app_name"] == definition.kit.spec.app_name

    HeadlessConfigEditorApp.reset()
    _assert_success(harness.invoke([*runtime_prefix, "config", "edit"]))
    assert HeadlessConfigEditorApp.run_count == 1

    run_args = [*runtime_prefix]
    if definition.bridge:
        run_args.extend(
            [
                "--workspace",
                str(tmp_path / definition.mode / "workspace"),
                "--model",
                "test-model",
                "--dry-run",
            ]
        )
    run_payload = _assert_json_success(harness.invoke([*run_args, "run"]))
    assert run_payload["app_name"] == definition.kit.spec.app_name


def test_cli_bridge_status_bypasses_runtime_bootstrap(tmp_path: Path) -> None:
    definition = EXAMPLE_CLIS[-1]
    harness = ExampleCliHarness(definition)

    result = harness.invoke(
        [
            "--workspace",
            str(tmp_path / "workspace"),
            "--model",
            "no-bootstrap",
            "--dry-run",
            "status",
        ]
    )

    _assert_success(result)
    assert result.output.strip() == "bridge_status: bootstrapless"


def test_example_cli_env_file_options_control_index_paths(
    tmp_path: Path,
) -> None:
    definition = EXAMPLE_CLIS[1]
    harness = ExampleCliHarness(definition)
    explicit_index = tmp_path / "explicit" / "storage.apprc.toml"
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"{definition.kit.spec.index_env_key}={explicit_index}\n",
        encoding="utf-8",
    )

    result = _assert_json_success(
        harness.invoke(
            [
                "--env-file",
                str(env_file),
                "--env-file-overrides-os-environ",
                "config",
                "paths",
                "--json",
            ]
        )
    )

    assert result["index_path"] == str(explicit_index.resolve())


def test_example_bootstrap_writes_teaching_comments(tmp_path: Path) -> None:
    env_files = bootstrap_example_apps(repo_root=tmp_path, clean=True)

    assert {path.name for path in env_files} == {".env"}
    for env_file in env_files:
        text = env_file.read_text(encoding="utf-8")
        assert "AppRC does not choose a location for this file" in text
        assert "set -a; source .env; set +a" in text

    generated_files = sorted(tmp_path.glob(".apprc-example*/**/.env.apprc-*"))
    generated_files.extend(sorted(tmp_path.glob(".apprc-example*/**/*.toml")))
    assert generated_files
    for path in generated_files:
        text = path.read_text(encoding="utf-8")
        assert "Generated by python -m apprc_dev.example_apps.bootstrap" in text
        assert "Real app location:" in text


def test_console_scripts_point_to_example_clis() -> None:
    root_pyproject = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    demo_pyproject = tomllib.loads(
        (ROOT / "examples" / "example_apps" / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )

    assert "scripts" not in root_pyproject["project"]
    assert demo_pyproject["project"]["scripts"] == {
        "apprc-env-only": "apprc_env_only_example.cli:main",
        "apprc-storage-only": "apprc_storage_only_example.cli:main",
        "apprc-app-wide-config": "apprc_app_wide_config_example.cli:main",
        "apprc-app-wide-storage": "apprc_app_wide_storage_example.cli:main",
        "apprc-explicit-env-precedence": (
            "apprc_explicit_env_precedence_example.cli:main"
        ),
        "apprc-cli-bridge": "apprc_cli_bridge_example.cli:main",
        "apprc-examples-run-all": "apprc_example_apps.run_all:main",
    }
    assert demo_pyproject["tool"]["setuptools"]["packages"]["find"][
        "include"
    ] == [
        "apprc_app_wide_config_example",
        "apprc_app_wide_storage_example",
        "apprc_cli_bridge_example",
        "apprc_env_only_example",
        "apprc_example_apps",
        "apprc_explicit_env_precedence_example",
        "apprc_storage_only_example",
    ]


def test_build_backend_packages_only_library_in_root_wheel() -> None:
    pyproject = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert pyproject["tool"]["uv"]["build-backend"]["module-name"] == "apprc"


def test_demo_package_is_dev_dependency_only() -> None:
    pyproject = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert pyproject["dependency-groups"]["demo"] == ["apprc-example-apps"]
    assert {"include-group": "demo"} in pyproject["dependency-groups"]["dev"]
    assert pyproject["tool"]["uv"]["sources"]["apprc-example-apps"] == {
        "path": "examples/example_apps",
        "editable": True,
    }


def test_core_package_does_not_import_demo_package() -> None:
    core_files = (ROOT / "src" / "apprc").rglob("*.py")

    offenders = [
        path
        for path in core_files
        if "example_apps" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_storage_modules_do_not_import_bootstrap_layer() -> None:
    storage_files = (
        ROOT / "src" / "apprc" / "user_files" / "storage_roots"
    ).rglob("*.py")

    offenders = [
        path for path in storage_files if _imports_runtime_bootstrap(path)
    ]
    assert offenders == []


def test_command_name_falls_back_or_uses_declared_command() -> None:
    assert config_command_text(build_apprc_example_app_kit(), "show") == (
        "apprc_example_app config show"
    )
    assert (
        config_command_text(STORAGE_ONLY_KIT, "show")
        == "apprc-storage-only config show"
    )


def _assert_success(result: Result) -> Result:
    """Return a successful CLI result or fail with output."""
    assert result.exit_code == 0, result.output
    return result


def _assert_json_success(result: Result) -> dict[str, object]:
    """Return parsed JSON from a successful CLI result."""
    _assert_success(result)
    payload = json.loads(result.output)
    assert isinstance(payload, dict)
    return payload


def _imports_runtime_bootstrap(path: Path) -> bool:
    """Return whether one Python file imports the bootstrap package.

    :param path: Python source file to inspect.
    :return: Whether it imports ``apprc.runtime``.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            if node.module.startswith("apprc.runtime"):
                return True
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("apprc.runtime"):
                    return True
    return False
