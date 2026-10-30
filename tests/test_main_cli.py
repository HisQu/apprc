from __future__ import annotations

import ast
import json
import os
import re
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import pytest
import typer
from cache_only import cli as cache_only
from cli_runtime import cli as cli_runtime
from cli_runtime.config.app import MyRC as RUNTIME_KIT
from explicit_env_precedence import (
    cli as explicit_env_precedence,
)
from explicit_env_precedence.config.app import (
    MyRC as EXPLICIT_ENV_PRECEDENCE_KIT,
)
from packaging.requirements import Requirement
from process_env import cli as process_env
from process_env.config.app import MyRC as PROCESS_ENV_RC
from typer.testing import CliRunner, Result
from user_dotenv import cli as user_dotenv
from user_dotenv.config.app import MyRC as USER_DOTENV_RC
from user_dotenv_with_workspace import cli as user_dotenv_with_workspace
from user_dotenv_with_workspace.config.app import MyRC as BOTH_RC
from workspace import cli as workspace
from workspace.config.app import MyRC as WORKSPACE_RC

from apprc import AppRC
from apprc.interfaces.cli.diagnostics.messages import config_command_text
from apprc.interfaces.tui.editor import ConfigEditorApp
from tests.support_config import build_workspace_example_app

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

    scenario: str
    command_name: str
    kit: AppRC
    build_app: Callable[..., typer.Typer]
    app_key: str
    app_value: str
    workspace_key: str | None = None
    workspace_value: str | None = None
    runtime: bool = False

    @property
    def uses_workspaces(self) -> bool:
        """Return whether this example declares workspace selection."""
        return self.kit.schema.uses_workspaces()

    @property
    def uses_user_dotenv(self) -> bool:
        """Return whether this example mounts user-dotenv commands."""
        return self.kit.schema.uses_user_dotenv()


EXAMPLE_CLIS = (
    ExampleCliDefinition(
        scenario="process_env",
        command_name="apprc-process-env",
        kit=PROCESS_ENV_RC,
        build_app=process_env.build_app,
        app_key="profile",
        app_value="process-env-profile",
    ),
    ExampleCliDefinition(
        scenario="user_dotenv",
        command_name="apprc-user-dotenv",
        kit=USER_DOTENV_RC,
        build_app=user_dotenv.build_app,
        app_key="profile",
        app_value="user-dotenv-profile",
    ),
    ExampleCliDefinition(
        scenario="workspace",
        command_name="apprc-workspace",
        kit=WORKSPACE_RC,
        build_app=workspace.build_app,
        app_key="profile",
        app_value="workspace-profile",
        workspace_key="api_token",
        workspace_value="workspace-secret",
    ),
    ExampleCliDefinition(
        scenario="user_dotenv_with_workspace",
        command_name="apprc-user-dotenv-with-workspace",
        kit=BOTH_RC,
        build_app=user_dotenv_with_workspace.build_app,
        app_key="profile",
        app_value="combined-profile",
        workspace_key="api_token",
        workspace_value="combined-secret",
    ),
    ExampleCliDefinition(
        scenario="explicit_env_precedence",
        command_name="apprc-explicit-env-precedence",
        kit=EXPLICIT_ENV_PRECEDENCE_KIT,
        build_app=explicit_env_precedence.build_app,
        app_key="label",
        app_value="precedence-app-label",
        workspace_key="label",
        workspace_value="precedence-workspace-label",
    ),
    ExampleCliDefinition(
        scenario="cli_runtime",
        command_name="apprc-cli-runtime",
        kit=RUNTIME_KIT,
        build_app=cli_runtime.build_app,
        app_key="profile",
        app_value="runtime-app-profile",
        workspace_key="api_token",
        workspace_value="runtime-secret",
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


@pytest.mark.parametrize(
    "definition",
    EXAMPLE_CLIS,
    ids=lambda item: item.scenario,
)
def test_example_cli_runs_every_supported_config_command(
    definition: ExampleCliDefinition,
    tmp_path: Path,
) -> None:
    harness = ExampleCliHarness(definition)
    workspace_root = tmp_path / definition.scenario / "workspace"

    _assert_success(harness.invoke(["--help"]))
    _assert_success(harness.invoke(["config", "--help"]))
    _assert_success(harness.invoke(["config", "paths"]))
    _assert_json_success(
        harness.invoke(["--log-level", "INFO", "config", "paths", "--json"])
    )

    if definition.uses_user_dotenv:
        _assert_success(harness.invoke(["config", "setup", "--yes"]))
    elif not definition.uses_workspaces:
        assert harness.invoke(["config", "setup", "--yes"]).exit_code != 0

    runtime_prefix: list[str] = []
    if definition.uses_workspaces:
        _assert_success(
            harness.invoke(["workspace", "add", "default", str(workspace_root)])
        )
        runtime_prefix = ["--workspace", "default"]
        assert definition.workspace_key is not None
        assert definition.workspace_value is not None
        _assert_success(
            harness.invoke(
                [
                    *runtime_prefix,
                    "config",
                    "set",
                    definition.workspace_key,
                    definition.workspace_value,
                    "--scope",
                    "workspace",
                ]
            )
        )
        if definition.uses_user_dotenv:
            _assert_success(
                harness.invoke(
                    [
                        "config",
                        "set",
                        definition.app_key,
                        definition.app_value,
                        "--scope",
                        "user",
                    ]
                )
            )
    elif definition.uses_user_dotenv:
        unavailable = harness.invoke(["workspace", "list"])
        assert unavailable.exit_code != 0
        _assert_success(
            harness.invoke(
                [
                    "config",
                    "set",
                    definition.app_key,
                    definition.app_value,
                    "--scope",
                    "user",
                ]
            )
        )
    else:
        assert harness.invoke(["config", "set", "x", "y"]).exit_code != 0

    _assert_success(harness.invoke([*runtime_prefix, "config", "doctor"]))
    doctor_json = _assert_json_success(
        harness.invoke([*runtime_prefix, "config", "doctor", "--json"])
    )
    assert doctor_json["status"] == "ok"

    _assert_success(harness.invoke([*runtime_prefix, "config", "show"]))
    show_json = _assert_json_success(
        harness.invoke([*runtime_prefix, "config", "show", "--json"])
    )
    assert show_json["app_id"] == definition.kit.schema.app_id

    HeadlessConfigEditorApp.reset()
    _assert_success(harness.invoke([*runtime_prefix, "config", "edit"]))
    assert HeadlessConfigEditorApp.run_count == 1

    run_args = [*runtime_prefix]
    if definition.runtime:
        run_args.extend(["--model", "test-model", "--dry-run"])
    run_payload = _assert_json_success(harness.invoke([*run_args, "run"]))
    assert run_payload["app_id"] == definition.kit.schema.app_id


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


def test_workspace_example_exercises_registry_lifecycle_and_path_selection(
    tmp_path: Path,
) -> None:
    definition = EXAMPLE_CLIS[2]
    harness = ExampleCliHarness(definition)
    default_root = tmp_path / "default"
    alpha_root = tmp_path / "alpha"
    repointed_root = tmp_path / "repointed"
    moved_root = tmp_path / "moved"

    _assert_success(
        harness.invoke(["workspace", "add", "default", str(default_root)])
    )
    _assert_success(
        harness.invoke(
            [
                "--workspace",
                "default",
                "config",
                "set",
                "api_token",
                "example-secret",
                "--scope",
                "workspace",
            ]
        )
    )
    selected_by_name = _assert_json_success(
        harness.invoke(["--workspace", "default", "run"])
    )
    assert selected_by_name["workspace"] == str(default_root.resolve())

    _assert_success(
        harness.invoke(["workspace", "add", "alpha", str(alpha_root)])
    )

    _assert_success(
        harness.invoke(
            [
                "--workspace",
                "alpha",
                "config",
                "set",
                "api_token",
                "alpha-secret",
                "--scope",
                "workspace",
            ]
        )
    )
    after_add = _assert_json_success(
        harness.invoke(["workspace", "list", "--json"])
    )
    assert after_add["workspace_count"] == 2
    registry = after_add["registry"]
    assert isinstance(registry, dict)
    assert registry["selected_workspace"] == "default"

    _assert_success(
        harness.invoke(["workspace", "rename", "default", "primary"])
    )
    _assert_success(harness.invoke(["workspace", "select", "alpha"]))

    after_select = _assert_json_success(
        harness.invoke(["workspace", "list", "--json"])
    )
    registry = after_select["registry"]
    assert isinstance(registry, dict)
    assert registry["selected_workspace"] == "alpha"
    repointed_root.mkdir(mode=0o700)
    _assert_success(
        harness.invoke(["workspace", "repoint", "alpha", str(repointed_root)])
    )
    _assert_success(
        harness.invoke(
            [
                "--workspace",
                "alpha",
                "config",
                "set",
                "api_token",
                "alpha-secret",
                "--scope",
                "workspace",
            ]
        )
    )
    _assert_success(
        harness.invoke(["workspace", "move", "alpha", str(moved_root)])
    )
    selected_after_move = _assert_json_success(
        harness.invoke(["--workspace", "alpha", "run"])
    )
    assert selected_after_move["workspace"] == str(moved_root.resolve())
    _assert_success(harness.invoke(["workspace", "remove", "alpha"]))
    after_remove = _assert_json_success(
        harness.invoke(["workspace", "list", "--json"])
    )
    assert after_remove["workspace_count"] == 1
    registry = after_remove["registry"]
    assert isinstance(registry, dict)
    assert registry["selected_workspace"] is None


def test_cache_only_entrypoint_exercises_help_initialization_and_paths(
    tmp_path: Path,
) -> None:
    app = cache_only.build_app()
    runner = CliRunner()
    env = {"XDG_CACHE_HOME": str(tmp_path / "cache")}

    help_result = _assert_success(
        runner.invoke(app, ["--help"], prog_name="apprc-cache-only")
    )
    assert "paths" in help_result.output
    assert "cache" in help_result.output

    before_init = _assert_json_success(
        runner.invoke(app, ["paths", "cache", "--json"], env=env)
    )
    assert before_init["exists"] is False
    cache_path = before_init["path"]

    init_result = _assert_success(
        runner.invoke(app, ["cache", "init"], env=env)
    )
    assert init_result.output.strip() == cache_path
    after_init = _assert_json_success(
        runner.invoke(app, ["paths", "cache", "--json"], env=env)
    )
    assert after_init == {
        "category": "cache",
        "path": cache_path,
        "exists": True,
    }


def test_example_cli_env_file_options_control_layout(
    tmp_path: Path,
) -> None:
    definition = EXAMPLE_CLIS[2]
    harness = ExampleCliHarness(definition)
    explicit_root = tmp_path / "explicit"
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"{definition.kit.schema.root_env_key}={explicit_root}\n",
        encoding="utf-8",
    )

    result = _assert_json_success(
        harness.invoke(
            [
                "--env-file",
                str(env_file),
                "--env-file-overrides-os-environ",
                "paths",
                "--json",
            ],
            env={definition.kit.schema.layout_env_key: "native"},
        )
    )

    assert result["layout"] == "single-root"
    assert result["root"] == str(explicit_root.resolve())
    assert result["source"] == "environment"
    paths = result["paths"]
    assert isinstance(paths, dict)
    assert paths["config"] == str(explicit_root.resolve() / "config")


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
        "apprc-process-env": "process_env.cli:main",
        "apprc-user-dotenv": "user_dotenv.cli:main",
        "apprc-workspace": "workspace.cli:main",
        "apprc-user-dotenv-with-workspace": (
            "user_dotenv_with_workspace.cli:main"
        ),
        "apprc-cache-only": "cache_only.cli:main",
        "apprc-explicit-env-precedence": "explicit_env_precedence.cli:main",
        "apprc-cli-runtime": "cli_runtime.cli:main",
        "apprc-library-client": "library_client.cli:main",
        "apprc-examples-lab": "_example_apps_utils.lab:main",
        "apprc-examples-run-all": "_example_apps_utils.run_all:main",
    }
    assert demo_pyproject["tool"]["setuptools"]["packages"]["find"][
        "include"
    ] == [
        "cli_runtime*",
        "process_env*",
        "user_dotenv*",
        "workspace*",
        "cache_only*",
        "_example_apps_utils",
        "explicit_env_precedence*",
        "library_client*",
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
    assert "examples/**" in source_include
    assert "docs/**" in source_include
    assert "README.md" in source_include


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


def test_terminal_dependencies_belong_to_wrapper() -> None:
    """The Textual editor is opt-in while dev installs keep test coverage."""
    pyproject = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert "textual" not in _dependency_names(
        pyproject["project"]["dependencies"]
    )
    wrapper = tomllib.loads(
        (ROOT / "src/apprc_dev/packaging/terminal/pyproject.toml").read_text()
    )
    assert "textual" in wrapper["project"]["dependencies"]
    assert "textual" in _dependency_names(pyproject["dependency-groups"]["dev"])


def test_verify_pypi_recipe_checks_current_base_install_surface() -> None:
    """The package smoke helper must track the clean public root facade."""
    recipe = _just_recipe("verify-pypi")
    helper = (ROOT / "src/apprc_dev/packaging/install_smoke.py").read_text(
        encoding="utf-8"
    )

    assert "install_smoke.py" in recipe
    assert "AppConfigKit" not in helper
    assert "apprc.AppRC" in helper
    assert "apprc.Config" in helper
    assert "apprc.ConfigBase" in helper
    assert "apprc.field" in helper
    assert "core-only" in helper
    assert "apprc-core" in helper


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


def test_ci_is_reusable_without_running_twice_for_release_tags() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert "workflow_call:" in workflow
    assert '      - "**"' in workflow
    assert "tags:" not in workflow
    assert "uses: extractions/setup-just@v4" in workflow
    assert 'just-version: "1.56.0"' in workflow
    assert (
        workflow.count(
            "matrix.os == 'ubuntu-latest' && matrix.python-version == '3.12'"
        )
        == 2
    )
    assert workflow.index("name: Install just") < workflow.index(
        "name: Validate justfile"
    )
    assert "run: just --summary" in workflow


def test_release_workflow_creates_github_release_before_optional_pypi() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    checks, remainder = workflow.split("  build:", maxsplit=1)
    build, remainder = remainder.split("  github-release:", maxsplit=1)
    github_release, remainder = remainder.split("  pypi-publish:", maxsplit=1)
    pypi_publish, publish_existing = remainder.split(
        "  publish-existing-release:", maxsplit=1
    )

    assert '      - "v*"' in workflow
    assert "workflow_dispatch:" in workflow
    assert "release_tag:" in workflow
    assert "uses: ./.github/workflows/ci.yml" in workflow
    assert "needs: checks" in workflow
    assert "needs: build" in workflow
    assert "environment: pypi" in pypi_publish
    assert "id-token: write" in workflow
    assert "contents: write" in workflow
    assert "--trusted-publishing always" in workflow
    assert "needs.build.outputs.release_pypi == 'true'" in pypi_publish
    assert "      - github-release" in pypi_publish
    assert "just --evaluate RELEASE_PYPI" in build
    assert 'gh release create "$GITHUB_REF_NAME"' in workflow
    assert "just _release-artifact-check release/release-notes.md" in workflow
    assert "just publish-check" not in build
    assert "uses: extractions/setup-just@v4" in build
    assert 'just-version: "1.56.0"' in build
    assert build.index("name: Install just") < build.index(
        "just _release-artifact-check release/release-notes.md"
    )
    assert "cancel-in-progress: false" in workflow
    assert "contents: read" in checks
    assert "contents: read" in build
    assert "id-token:" not in checks
    assert "id-token:" not in build
    assert "actions/upload-artifact@v7" in build
    assert "actions/download-artifact@v8" in github_release
    assert "actions/download-artifact@v8" in pypi_publish
    assert "artifact@v4" not in workflow
    assert "dist/*.whl" in workflow
    assert "dist/*.tar.gz" in workflow
    assert "--notes-file release/release-notes.md" in github_release
    assert "--trusted-publishing always" in pypi_publish
    assert "if: github.event_name == 'workflow_dispatch'" in publish_existing
    assert "gh release download" in publish_existing
    assert "exactly three wheels and three source archives" in publish_existing
    assert "${project}-${version}-py3-none-any.whl" in publish_existing
    assert "${project}-${version}.tar.gz" in publish_existing
    assert "twine check" in publish_existing
    assert "uv build" not in publish_existing
    assert "actions/checkout" not in publish_existing
    assert "--check-url https://pypi.org/simple/apprc/" in workflow
    assert "PUBLISH_PYPI" not in workflow


def test_publish_check_rehearses_ci_and_release_artifacts() -> None:
    justfile = (ROOT / "justfile").read_text(encoding="utf-8")
    publish_check = _just_recipe("publish-check")
    ci_check = _just_recipe("_ci-check-python")
    artifact_check = _just_recipe("_release-artifact-check")

    assert "pypi-readme:" not in justfile
    assert "build:" not in justfile
    assert "for python_version in 3.12 3.13 3.14" in publish_check
    assert "mktemp -d" in publish_check
    assert "_ci-check-python" in publish_check
    assert "_release-artifact-check" in publish_check
    for command in (
        "uv sync",
        "uv lock --check",
        "ruff format . --check",
        "ruff check .",
        "pyright",
        "pytest",
        "python -m compileall",
    ):
        assert command in ci_check
    assert "UV_PROJECT_ENVIRONMENT" in ci_check
    assert "UV_LINK_MODE=copy" in ci_check
    assert "unset VIRTUAL_ENV" in ci_check
    assert "--quiet" in ci_check
    assert "--no-progress" in ci_check
    assert "preparing isolated release environment" in ci_check
    assert "environment ready; running CI checks" in ci_check
    assert "CI checks passed" in ci_check
    assert '$(dirname "$UV_PROJECT_ENVIRONMENT")' in ci_check
    assert "release_notes.py" in artifact_check
    assert "GITHUB_REF_NAME:-v${version}" in artifact_check
    assert "pypi_readme.py" in artifact_check
    assert "gui_metadata.py --check" in artifact_check
    assert "rm -rf dist" in artifact_check
    assert "uv build --python 3.12 --no-sources" in artifact_check
    assert "twine check" in artifact_check
    assert "for python_version in 3.12 3.13 3.14" in artifact_check
    assert "--python 3.12" in artifact_check
    assert "artifact_check.py dist" in artifact_check
    assert "--dry-run" in artifact_check
    assert "--trusted-publishing never" in artifact_check
    assert "--token unused-local-dry-run-token" in artifact_check
    assert "https://pypi.org/simple/${project}/" in artifact_check
    assert "no files will be uploaded" in artifact_check
    assert "nothing was uploaded" in artifact_check
    assert "run just release <patch|minor|major>" in publish_check
    assert (
        "Local release rehearsal passed; nothing was published" in publish_check
    )


def test_release_recipe_surface_is_minimal() -> None:
    justfile = (ROOT / "justfile").read_text(encoding="utf-8")

    for recipe in (
        "release",
        "release-prepare",
        "release-push",
        "publish-check",
        "publish-pypi",
        "verify-pypi",
    ):
        assert _just_recipe(recipe)
    for removed_recipe in ("bump", "bump-version", "build", "pypi-readme"):
        assert (
            re.search(
                rf"(?m)^{re.escape(removed_recipe)}(?:[^\n]*):",
                justfile,
            )
            is None
        )
    for private_recipe in ("_release-artifact-check", "_ci-check-python"):
        assert re.search(
            rf"(?m)^\[private\]\n{re.escape(private_recipe)}(?:[^\n]*):",
            justfile,
        )
    assert (
        re.search(r"(?m)^alias\s+(?:bump|bump-version)\s*:=", justfile) is None
    )


def test_release_recipe_pushes_prepared_tag_atomically() -> None:
    """Release orchestration should preserve a retryable local result."""
    justfile = (ROOT / "justfile").read_text(encoding="utf-8")
    release = _just_recipe("release")
    release_push = _just_recipe("release-push")
    publish_pypi = _just_recipe("publish-pypi")

    assert 'RELEASE_PYPI := "true"' in justfile
    assert 'just release-prepare "{{level}}"' in release
    assert 'just release-push "$tag"' in release
    assert 'git push --atomic origin main "$tag"' in release_push
    assert "git branch --show-current" in release_push
    assert 'git cat-file -e "${tag}^{tag}"' in release_push
    assert "just --evaluate RELEASE_PYPI" in release_push
    assert "gh workflow run release.yml" in publish_pypi
    assert "isDraft" in publish_pypi
    assert "exactly three wheels and three source archives" in publish_pypi


def test_release_prepare_keeps_existing_result_banner() -> None:
    """The new split command should retain the established visual structure."""
    recipe = _just_recipe("release-prepare")

    assert (
        'echo "================================================================="'
        in recipe
    )
    assert 'echo "✅  RELEASE ${tag} PREPARED LOCALLY"' in recipe
    assert 'echo "Nothing has been uploaded."' in recipe
    assert 'echo "NEXT COMMAND, THIS STARTS THE RELEASE:"' in recipe


def test_release_metadata_links_to_github_and_pypi_surfaces() -> None:
    pyproject = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    urls = pyproject["project"]["urls"]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert urls == {
        "Homepage": "https://github.com/HisQu/apprc",
        "Repository": "https://github.com/HisQu/apprc",
        "Documentation": "https://github.com/HisQu/apprc/tree/main/docs",
        "Changelog": "https://github.com/HisQu/apprc/blob/main/CHANGELOG.md",
        "Issues": "https://github.com/HisQu/apprc/issues",
    }
    assert "actions/workflows/ci.yml/badge.svg" in readme
    assert "img.shields.io/pypi/v/apprc" in readme
    assert "img.shields.io/pypi/pyversions/apprc" in readme
    assert "img.shields.io/pypi/l/apprc" in readme


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
        rf"(?ms)^{re.escape(name)}(?:[ \t][^\n]*)?:\n(?P<body>.*?)(?=^\S|\Z)",
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


def test_workspace_root_modules_do_not_import_bootstrap_layer() -> None:
    workspace_root_files = (
        ROOT / "src" / "apprc" / "user_files" / "workspace_roots"
    ).rglob("*.py")

    offenders = [
        path
        for path in workspace_root_files
        if _imports_runtime_bootstrap(path)
    ]
    assert offenders == []


def test_command_name_falls_back_or_uses_declared_command() -> None:
    assert config_command_text(build_workspace_example_app(), "show") == (
        "apprc_example_app config show"
    )
    assert (
        config_command_text(WORKSPACE_RC, "show")
        == "apprc-workspace config show"
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
