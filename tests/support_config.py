"""Shared AppRC example declarations for maintained interface tests."""

from __future__ import annotations

# == Standard Library ========================
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# == 3rd Party ===============================
from pytest import MonkeyPatch
from rich.text import Text
from typer.testing import Result

# == Internal ================================
import apprc as rc
from apprc import AppRC
from apprc.definition.paths import AppPaths, Layout
from apprc.definition.installation import InstallationSnapshot
from apprc.definition.provenance import ConfigOriginState, ShellProvenanceOrigin
from apprc.definition.resolution import ConfigSource
from apprc.runtime.resolution import ResolvedConfig, ResolvedLayer, merge_layers
from apprc.user_files.app_home.application import AppFiles
from apprc.user_files.env_files.secrets import repair_secret_file_permissions
from apprc.user_files.workspace_roots.registry import (
    WorkspaceRegistry,
    record_archived_workspace,
)


def native_environment() -> dict[str, str]:
    """Keep native test roots while excluding unrelated business variables."""
    keys = (
        "HOME",
        "USERPROFILE",
        "LOCALAPPDATA",
        "APPDATA",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
        "XDG_STATE_HOME",
    )
    return {key: os.environ[key] for key in keys if key in os.environ}


def compact_cli_output(result: Result) -> str:
    """Return rendered CLI text without terminal presentation details."""
    plain = Text.from_ansi(result.output).plain
    return "".join(
        character
        for character in plain
        if not character.isspace() and not "\u2500" <= character <= "\u257f"
    )


_WORKSPACE_EXAMPLE_RC = rc.AppRC(
    app_id="apprc_example_app",
    display_name="Example App",
    config_package="user_dotenv_with_workspace.config",
    paths=rc.Paths(config=True),
    user_dotenv=rc.UserDotenv(),
    workspaces=rc.Workspaces(selector_env_key="APPRC_EXAMPLE_APP_WORKSPACE"),
)


@_WORKSPACE_EXAMPLE_RC.config(
    "app", title="App", prefix="APPRC_EXAMPLE_APP_", rc_path=("app",)
)
class WorkspaceExampleEnv(rc.Config):
    """Example configuration owner used by workspace interface tests."""

    workspace_root: Path = rc.field(
        "APPRC_EXAMPLE_APP_WORKSPACE", editable=False, required=True
    )
    profile: str = rc.field(
        "APPRC_EXAMPLE_APP_PROFILE",
        default="default",
        title="Profile",
        explanation_short="Named profile used by the example app.",
        explanation_long="Named profile used by the example app. Longer context appears in the modal editor.",
    )
    mode: str = rc.field(
        "APPRC_EXAMPLE_APP_MODE",
        default="AUTO",
        title="Mode",
        explanation_short="Operating mode used by Example App commands.",
        choices=("AUTO", "MANUAL"),
    )
    enabled: bool = rc.field(
        "APPRC_EXAMPLE_APP_ENABLED",
        default=True,
        title="Enabled",
        explanation_short="Turns the example app on or off.",
    )
    retry_count: int = rc.field(
        "APPRC_EXAMPLE_APP_RETRY_COUNT",
        default=3,
        title="Retry count",
        explanation_short="Maximum number of retry attempts.",
    )
    cache_dir: Path = rc.field(
        "APPRC_EXAMPLE_APP_CACHE_DIR",
        default=Path("cache"),
        title="Cache directory",
        explanation_short="Workspace-local cache path.",
    )
    access_token: str = rc.field(
        "APPRC_EXAMPLE_APP_ACCESS_TOKEN",
        title="Access token",
        explanation_short="Required secret token.",
        explanation_long="Secret token required by the example app when no shell environment or local override provides one.",
        required=True,
        secret=True,
    )


WORKSPACE_EXAMPLE_OWNER = rc.schema.owner_for(WorkspaceExampleEnv)
WORKSPACE_EXAMPLE_OWNERS = (WORKSPACE_EXAMPLE_OWNER,)


_CONFIG_ONLY_RC = rc.AppRC(
    app_id="config_only_app",
    display_name="Config-only App",
    config_package="user_dotenv.config",
    paths=rc.Paths(config=True),
    user_dotenv=rc.UserDotenv(),
)


@_CONFIG_ONLY_RC.config(
    "global", title="Global", prefix="CONFIG_ONLY_APP_", rc_path=("global",)
)
class ConfigOnlyExampleEnv(rc.Config):
    """Config-only env section used by AppRC CLI tests."""

    profile: str = rc.field(
        "CONFIG_ONLY_APP_PROFILE",
        default="default",
        title="Profile",
        explanation_short="Named profile used by the config-only app.",
    )
    enabled: bool = rc.field(
        "CONFIG_ONLY_APP_ENABLED",
        default=True,
        title="Enabled",
        explanation_short="Turns the config-only app on or off.",
    )


CONFIG_ONLY_EXAMPLE_OWNER = rc.schema.owner_for(ConfigOnlyExampleEnv)


def example_resolution(
    *,
    user_dotenv_values: Mapping[str, str],
    workspace_values: Mapping[str, str],
    shell_env: Mapping[str, str],
    defaults_values: Mapping[str, str] | None,
) -> ResolvedConfig:
    """Build presentation-only sources with workspace dotenv provenance."""
    inputs: tuple[tuple[ShellProvenanceOrigin, Mapping[str, str]], ...] = (
        ("shell_dotenv_defaults", defaults_values or {}),
        ("shell_dotenv_user", user_dotenv_values),
        ("shell_dotenv_workspace", workspace_values),
        ("shell_export_variable", shell_env),
    )
    layers = tuple(
        ResolvedLayer(
            origin,
            ConfigSource(
                values,
                {key: ConfigOriginState(origin, env_key=key) for key in values},
            ),
        )
        for origin, values in inputs
    )
    return ResolvedConfig(
        schema=_WORKSPACE_EXAMPLE_RC.schema,
        options=rc.ResolveOptions(),
        source=merge_layers(layers),
        layers=layers,
        paths=AppPaths(
            Layout.native(),
            "default",
            None,
            None,
            None,
            None,
            None,
            InstallationSnapshot(Path("/unused/installation"), None, None),
        ),
        workspace=None,
        workspace_count=0,
        registered_types=(WorkspaceExampleEnv,),
        bundles={},
    )


@dataclass(slots=True)
class WorkspaceExampleState:
    """Host CLI state used by generated config/workspace tests."""

    resolved: ResolvedConfig | None
    workspace: str | None = None


@dataclass(slots=True)
class ConfigOnlyExampleState:
    """Host CLI state used by config-only generated tests."""

    resolved: ResolvedConfig | None = None
    workspace: str | None = None


@dataclass(slots=True)
class ConfigOnlyExampleStateWithoutWorkspace:
    """Config-only host state with no workspace selector field."""

    resolved: ResolvedConfig | None = None


def build_workspace_example_app(*, setup_next_step: str | None = None) -> AppRC:
    """Return an isolated workspace-capable AppRC declaration."""
    app_rc = rc.AppRC(
        app_id="apprc_example_app",
        display_name="Example App",
        config_package="user_dotenv_with_workspace.config",
        paths=rc.Paths(config=True),
        user_dotenv=rc.UserDotenv(),
        workspaces=rc.Workspaces(
            selector_env_key="APPRC_EXAMPLE_APP_WORKSPACE"
        ),
        setup_next_step=setup_next_step,
    )
    app_rc.config(
        "app", title="App", prefix="APPRC_EXAMPLE_APP_", rc_path=("app",)
    )(WorkspaceExampleEnv)
    return app_rc


def build_config_only_example_app(
    *, setup_next_step: str | None = None
) -> AppRC:
    """Return an AppRC declaration with user config but no workspaces."""
    app_rc = rc.AppRC(
        app_id="config_only_app",
        display_name="Config-only App",
        config_package="user_dotenv.config",
        paths=rc.Paths(config=True),
        user_dotenv=rc.UserDotenv(),
        setup_next_step=setup_next_step,
    )
    app_rc.config(
        "global", title="Global", prefix="CONFIG_ONLY_APP_", rc_path=("global",)
    )(ConfigOnlyExampleEnv)
    return app_rc


def set_workspace_example_app_apprc_toml(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> Path:
    """Point the workspace example at an isolated config root."""
    path, _ = set_workspace_example_bootstrap(monkeypatch, tmp_path)
    return path


def create_empty_workspace_example_app_apprc_toml(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> Path:
    """Point the workspace example at an empty registry file."""
    path = set_workspace_example_app_apprc_toml(monkeypatch, tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


def set_workspace_example_bootstrap(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    *,
    apprc_toml: Path | None = None,
    workspace_root: Path | None = None,
) -> tuple[Path, Path]:
    """Capture isolated config/workspace bootstrap values for CLI tests."""
    config_home = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    kit = build_workspace_example_app()
    paths = kit.paths(environment=dict(__import__("os").environ))
    if apprc_toml is not None:
        config_root = apprc_toml.parent
        monkeypatch.setenv("XDG_CONFIG_HOME", str(config_root.parent.parent))
        path = apprc_toml
    else:
        path = AppFiles(kit.schema, paths).config_file()
    root = workspace_root or tmp_path / "default-workspace"
    kit.ensure_path("config", environment=dict(os.environ))
    kit.workspaces(environment=dict(os.environ)).register_workspace(
        name="default", root=root
    )
    monkeypatch.setenv("APPRC_EXAMPLE_APP_WORKSPACE", "default")
    return path, root


def workspace_example_app_state(
    kit: AppRC, workspace_root: Path
) -> WorkspaceExampleState:
    """Return host CLI state resolved from an explicit workspace path."""
    return WorkspaceExampleState(
        resolved=kit.resolve(
            rc.ResolveOptions(workspace=str(workspace_root)),
            environment=native_environment(),
        ),
        workspace="alpha",
    )


def register_workspace_for_app(
    kit: AppRC, *, name: str, root: Path
) -> WorkspaceRegistry:
    """Register a test workspace through the application's manager."""
    environment = native_environment()
    kit.ensure_path("config", environment=environment)
    registry = kit.workspaces(environment=environment).register_workspace(
        name, root
    )
    files = AppFiles(kit.schema, kit.paths(environment=environment))
    repair_secret_file_permissions(
        files.workspace_secret_dotenv_path(root.resolve())
    )
    return registry


def record_archived_workspace_for_kit(
    kit: AppRC,
    *,
    name: str,
    archive: Path,
    source_root: Path,
) -> WorkspaceRegistry:
    """Record an archived workspace through its application registry."""
    manager = kit.workspaces(environment=native_environment())
    return record_archived_workspace(
        name=name,
        archive=archive,
        source_root=source_root,
        path=manager.registry_path(),
    )


def assert_app_path_cli_error(result: Result) -> None:
    """Assert that a CLI failure reports an AppRC path readiness error."""
    assert result.exit_code != 0, result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "AppRC" in result.output
    assert "Traceback" not in result.output
    assert "Invalid value for 'KEY'" not in result.output


def block_config_path_with_file(kit: AppRC) -> Path:
    """Replace the declared config directory with a blocking file."""
    config_dir = kit.paths().require("config")
    config_dir.parent.mkdir(parents=True, exist_ok=True)
    config_dir.write_text("not a directory", encoding="utf-8")
    return config_dir
