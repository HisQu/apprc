from __future__ import annotations

import ast
import json
import os
import re
import shlex
import subprocess
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import pytest
import typer
from packaging.requirements import Requirement
from typer.testing import CliRunner, Result

from app_wide_config import cli as app_wide_config
from app_wide_config.config import KIT as APP_WIDE_CONFIG_KIT
from app_wide_storage import cli as app_wide_storage
from app_wide_storage.config import KIT as APP_WIDE_STORAGE_KIT
from cli_runtime import cli as cli_runtime
from cli_runtime.config import KIT as RUNTIME_KIT
from env_only import cli as env_only
from env_only.config import KIT as ENV_ONLY_KIT
from explicit_env_precedence import (
    cli as explicit_env_precedence,
)
from explicit_env_precedence.config import (
    KIT as EXPLICIT_ENV_PRECEDENCE_KIT,
)
from apprc.definition.app_config.kit import AppConfigKit
from apprc.interfaces.tui.editor import ConfigEditorApp
from apprc.runtime.diagnostics.messages import config_command_text
from storage_only import cli as storage_only
from storage_only.config import KIT as STORAGE_ONLY_KIT
from apprc_dev.example_apps.bootstrap import (
    EXAMPLE_APP_DISK_FILES_ROOT,
    bootstrap_example_apps,
)
from tests.support_config import build_apprc_example_app_kit

ROOT = Path(__file__).parents[1]


class HeadlessConfigEditorApp(ConfigEditorApp):
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
    kit: AppConfigKit
    build_app: Callable[..., typer.Typer]
    app_key: str
    app_value: str
    storage_key: str | None = None
    storage_value: str | None = None
    runtime: bool = False

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
        mode="cli_runtime",
        command_name="apprc-cli-runtime",
        kit=RUNTIME_KIT,
        build_app=cli_runtime.build_app,
        app_key="profile",
        app_value="runtime-app-profile",
        storage_key="api_token",
        storage_value="runtime-secret",
        runtime=True,
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
    if definition.runtime:
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


def test_cli_runtime_status_bypasses_runtime_bootstrap(tmp_path: Path) -> None:
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
    assert result.output.strip() == "runtime_status: runtime-independent"


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
    output_root = tmp_path / "example_app_disk_files"
    env_files = bootstrap_example_apps(output_root=output_root, clean=True)

    assert {path.name for path in env_files} == {".env"}
    assert all(path.is_relative_to(output_root) for path in env_files)
    assert not list(tmp_path.glob(".apprc-example*"))

    for env_file in env_files:
        text = env_file.read_text(encoding="utf-8")
        assert "AppRC does not choose a location for this file" in text
        assert "set -a; source .env; set +a" in text

    shared_config_home = output_root / "xdg-config-home"
    assert {path.name for path in shared_config_home.iterdir()} == {
        definition.kit.spec.app_name for definition in EXAMPLE_CLIS
    }

    storage_roots = sorted(output_root.glob(".apprc-example*/storages/alpha"))
    assert len(storage_roots) == sum(
        definition.uses_storage for definition in EXAMPLE_CLIS
    )

    generated_files = sorted(output_root.glob("**/.env.apprc-*"))
    generated_files.extend(sorted(output_root.glob("**/*.toml")))
    assert generated_files
    for path in generated_files:
        text = path.read_text(encoding="utf-8")
        assert "Generated by python -m apprc_dev.example_apps.bootstrap" in text
        assert "Real app location:" in text


def test_example_bootstrap_default_output_root() -> None:
    assert EXAMPLE_APP_DISK_FILES_ROOT == (
        ROOT / "examples" / "example_app_disk_files"
    )


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="requires a POSIX Bash shell",
)
def test_example_root_env_makes_precedence_app_runnable(
    tmp_path: Path,
) -> None:
    env = _source_example_apps_env(project_root=tmp_path)
    output_root = Path(env["APPRC_EXAMPLE_APPS_ROOT"])
    bootstrap_example_apps(output_root=output_root, clean=True)

    definition = EXAMPLE_CLIS[4]
    harness = ExampleCliHarness(definition)
    payload = _assert_json_success(harness.invoke(["run"], env=env))
    bootstrap = payload["bootstrap"]
    config = payload["config"]

    assert payload["app_name"] == definition.kit.spec.app_name
    assert isinstance(bootstrap, dict)
    assert bootstrap["storage_root"] == str(
        output_root
        / ".apprc-example-explicit-env-precedence"
        / "storages"
        / "alpha"
    )
    assert isinstance(config, dict)
    assert config["label"] == "explicit-env-label"


def test_console_scripts_point_to_example_clis() -> None:
    root_pyproject = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    demo_pyproject = tomllib.loads(
        (ROOT / "examples" / "example_apps" / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )

    assert root_pyproject["project"]["scripts"] == {
        "apprc": "apprc.__main__:main",
    }
    assert demo_pyproject["project"]["scripts"] == {
        "apprc-env-only": "env_only.cli:main",
        "apprc-storage-only": "storage_only.cli:main",
        "apprc-app-wide-config": "app_wide_config.cli:main",
        "apprc-app-wide-storage": "app_wide_storage.cli:main",
        "apprc-explicit-env-precedence": ("explicit_env_precedence.cli:main"),
        "apprc-cli-runtime": "cli_runtime.cli:main",
        "apprc-examples-run-all": "_example_apps_utils.run_all:main",
    }
    assert demo_pyproject["tool"]["setuptools"]["packages"]["find"][
        "include"
    ] == [
        "app_wide_config*",
        "app_wide_storage*",
        "cli_runtime*",
        "env_only*",
        "_example_apps_utils",
        "explicit_env_precedence*",
        "storage_only*",
    ]


def test_build_backend_packages_only_library_in_root_wheel() -> None:
    pyproject = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert pyproject["tool"]["uv"]["build-backend"]["module-name"] == "apprc"


def test_sdist_includes_tests_and_example_app_sources() -> None:
    pyproject = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    source_include = pyproject["tool"]["uv"]["build-backend"]["source-include"]

    assert "tests/**" in source_include
    assert "examples/example_apps/**" in source_include


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


def test_textual_is_tui_extra_not_core_runtime_dependency() -> None:
    """The Textual editor is opt-in while dev installs keep test coverage."""
    pyproject = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert "textual" not in _dependency_names(
        pyproject["project"]["dependencies"]
    )
    assert pyproject["project"]["optional-dependencies"]["tui"] == ["textual"]
    assert "textual" in _dependency_names(pyproject["dependency-groups"]["dev"])


def test_verify_pypi_recipe_checks_current_base_install_surface() -> None:
    """The package smoke helper must track the clean public root facade."""
    recipe = _just_recipe("verify-pypi")

    assert "AppConfigKit" not in recipe
    assert "apprc.AppRC" in recipe
    assert "apprc.Config" in recipe
    assert "apprc.ConfigBase" in recipe
    assert "apprc.field" in recipe
    assert "Provides-Extra" in recipe
    assert 'find_spec("textual") is None' in recipe
    assert 'startswith("textual")' in recipe


def test_clean_recipe_removes_nested_egg_info_without_touching_envs() -> None:
    """Cleaning should remove nested package metadata but skip environments."""
    recipe = _just_recipe("clean")

    assert '-name "*.egg-info"' in recipe
    assert "./.git" in recipe
    assert "./.venv" in recipe
    assert "./.direnv" in recipe
    assert "find ." in recipe
    assert "uv cache prune -y" not in recipe


def test_ci_compile_command_uses_current_source_roots() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert "examples/apprc_example_app/src" not in workflow
    assert (
        "python -m compileall -q src tests examples/example_apps/src"
        in workflow
    )


def test_release_docs_do_not_contain_stale_template_names() -> None:
    texts = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in (
            "CHANGELOG.md",
            "docs/Development.md",
            "justfile",
        )
    )

    assert "{my_project}" not in texts
    assert "src/apprc/logging" not in texts
    assert "such as rag" not in texts


def _dependency_names(requirements: list[object]) -> set[str]:
    """Return requirement names from dependency strings in one pyproject list."""
    names: set[str] = set()
    for requirement in requirements:
        if isinstance(requirement, str):
            names.add(Requirement(requirement).name)
    return names


def _just_recipe(name: str) -> str:
    """Return one recipe body from the project justfile."""
    justfile = (ROOT / "justfile").read_text(encoding="utf-8")
    match = re.search(
        rf"(?ms)^{re.escape(name)}(?:[^\n]*):\n(?P<body>.*?)(?=^\S|\Z)",
        justfile,
    )
    assert match is not None
    return match.group("body")


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


def _source_example_apps_env(*, project_root: Path) -> dict[str, str]:
    """Return env values produced by sourcing the root example env file."""
    command = (
        f"PROJECT_ROOT={shlex.quote(project_root.as_posix())}; "
        f"source {shlex.quote((ROOT / '.env.example_apps').as_posix())}; "
        "env -0"
    )
    result = subprocess.run(
        ["bash", "-c", command],
        check=True,
        capture_output=True,
    )
    env: dict[str, str] = {}
    for item in result.stdout.split(b"\0"):
        if not item:
            continue
        key, _, value = item.partition(b"=")
        decoded_key = key.decode()
        if decoded_key.startswith("APPRC_EXAMPLE_") or decoded_key in {
            "PROJECT_ROOT",
            "XDG_CONFIG_HOME",
        }:
            env[decoded_key] = value.decode()
    return env


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
