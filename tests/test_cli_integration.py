from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from apprc.cli import prepare_cli_runtime_context
from apprc.definition.paths import Layout
from apprc.interfaces.cli import (
    AppRootOption,
    CliArgvProvider,
    CliRuntime,
    CliRuntimeContext,
    CliRuntimeOptions,
    EnvFileOverridesOption,
    EnvFilesOption,
    LayoutOption,
    LogLevelOption,
    SkipDotenvLayersOption,
    cli_runtime_context_from,
    cli_runtime_options_to_args,
    mount_app_cli,
)
from tests.support_config import (
    ConfigOnlyExampleEnv,
    ConfigOnlyExampleState,
    WorkspaceExampleEnv,
    build_config_only_example_app,
    build_workspace_example_app,
    register_workspace_for_app,
)


def test_cli_bootstrap_options_normalize_and_forward_workspace_layout(
    tmp_path: Path,
) -> None:
    first_env = tmp_path / "first.env"
    second_env = tmp_path / "second.env"
    app_root = tmp_path / "app-root"
    options = CliRuntimeOptions.from_typer(
        env_files=[first_env, second_env],
        env_file_overrides_os_environ=True,
        load_dotenv_layers=False,
        workspace="alpha",
        layout="single-root",
        app_root=app_root,
        log_level="DEBUG",
    )

    assert options.env_files == (first_env, second_env)
    assert cli_runtime_options_to_args(options) == [
        "--log-level",
        "DEBUG",
        "--env-file",
        str(first_env),
        "--env-file",
        str(second_env),
        "--env-file-overrides-os-environ",
        "--skip-dotenv-layers",
        "--workspace",
        "alpha",
        "--layout",
        "single-root",
        "--app-root",
        str(app_root),
    ]


def test_cli_bootstrap_options_accept_option_like_none_env_files() -> None:
    @dataclass(frozen=True, slots=True)
    class OptionLike:
        """Option object mirroring a Typer callback with no env files."""

        env_files: list[Path] | None = None
        env_file_overrides_os_environ: bool = False
        load_dotenv_layers: bool = True
        workspace: str | None = None
        layout: Layout | None = None
        log_level: str | None = None

    options = CliRuntimeOptions.from_options(OptionLike())

    assert options.env_files == ()


def test_prepare_cli_runtime_context_captures_paths_and_environment_when_skipped(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    kit = build_config_only_example_app()
    app_root = tmp_path / "selected-root"
    monkeypatch.setenv("CAPTURED_BY_APPRC", "before")
    app = typer.Typer()

    @app.callback()
    def root_cmd(
        ctx: typer.Context,
        layout: LayoutOption = None,
        app_root_option: AppRootOption = None,
        env_files: EnvFilesOption = None,
        env_file_overrides_os_environ: EnvFileOverridesOption = False,
        skip_dotenv_layers: SkipDotenvLayersOption = False,
        log_level: LogLevelOption = None,
    ) -> None:
        options = CliRuntimeOptions.from_typer(
            layout=layout,
            app_root=app_root_option,
            env_files=env_files,
            env_file_overrides_os_environ=env_file_overrides_os_environ,
            load_dotenv_layers=not skip_dotenv_layers,
            log_level=log_level,
        )
        prepare_cli_runtime_context(ctx, kit, options, skip_runtime_setup=True)
        os.environ["CAPTURED_BY_APPRC"] = "after"

    @app.command()
    def inspect(ctx: typer.Context) -> None:
        context = cli_runtime_context_from(ctx)
        assert context is not None
        typer.echo(
            json.dumps(
                {
                    "app_root": str(context.paths.layout.root),
                    "environment": context.environment["CAPTURED_BY_APPRC"],
                    "skipped": context.runtime_setup_skipped,
                },
                sort_keys=True,
            )
        )

    result = CliRunner().invoke(
        app,
        ["--layout", "single-root", "--app-root", str(app_root), "inspect"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "app_root": str(app_root),
        "environment": "before",
        "skipped": True,
    }


def test_mount_app_cli_resolves_config_from_workspace_and_env_precedence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    kit = build_workspace_example_app()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    register_workspace_for_app(
        kit,
        name="alpha",
        root=tmp_path / "workspace",
    )
    env_file = tmp_path / "explicit.env"
    env_file.write_text(
        "APPRC_EXAMPLE_APP_PROFILE=from-file\n"
        "APPRC_EXAMPLE_APP_ACCESS_TOKEN=from-file-secret\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("APPRC_EXAMPLE_APP_PROFILE", "from-shell")
    app = typer.Typer()
    mount_app_cli(app, kit)

    @app.command()
    def run(ctx: typer.Context) -> None:
        context = cli_runtime_context_from(ctx)
        assert context is not None and context.resolved is not None
        typer.echo(context.resolved.build(WorkspaceExampleEnv).profile)

    result = CliRunner().invoke(
        app,
        ["--workspace", "alpha", "--env-file", str(env_file), "run"],
    )

    assert result.exit_code == 0, result.output
    assert result.output.strip() == "from-shell"


def test_mount_app_cli_args_provider_controls_runtime_skip(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    kit = build_config_only_example_app()
    args = ["config", "paths", "--json"]
    state_calls: list[CliRuntimeContext] = []

    def state_factory(context: CliRuntimeContext) -> ConfigOnlyExampleState:
        state_calls.append(context)
        return ConfigOnlyExampleState(resolved=context.resolved)

    app = typer.Typer()
    mount_app_cli(
        app,
        kit,
        state_type=ConfigOnlyExampleState,
        state_factory=state_factory,
        args_provider=lambda: args,
    )
    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    assert state_calls == []


def test_cli_argv_provider_alias_accepts_token_provider() -> None:
    def provide_args() -> list[str]:
        """Return command tokens without the program name."""
        return ["config", "paths"]

    provider: CliArgvProvider = provide_args

    assert provider() == ["config", "paths"]


def test_mount_app_cli_rejects_existing_root_callback() -> None:
    app = typer.Typer()

    @app.callback()
    def root_cmd() -> None:
        """Existing callback owned by the host app."""

    with pytest.raises(RuntimeError, match="already has a callback"):
        mount_app_cli(app, build_config_only_example_app())


def test_mount_app_cli_rejects_existing_app_group_name() -> None:
    app = typer.Typer()

    @app.command()
    def config() -> None:
        """Host command that collides with the generated config group."""

    with pytest.raises(RuntimeError, match="command names are already in use"):
        mount_app_cli(app, build_config_only_example_app())


def test_runtime_mount_app_groups_preserves_host_callback_and_mounts_groups() -> (
    None
):
    kit = build_config_only_example_app()
    args = ["config", "paths", "--json"]
    runtime = CliRuntime[CliRuntimeOptions, ConfigOnlyExampleState](
        kit,
        state_type=ConfigOnlyExampleState,
        state_factory=lambda context, _options: ConfigOnlyExampleState(
            resolved=context.resolved
        ),
        args_provider=lambda: args,
    )
    app = typer.Typer()
    callback_calls: list[str | None] = []

    @app.callback()
    def host_callback(ctx: typer.Context) -> None:
        callback_calls.append(ctx.invoked_subcommand)
        runtime.prepare(ctx, CliRuntimeOptions())

    mounted = runtime.mount_app_groups(app)

    assert "config" in mounted
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert callback_calls == ["config"]


def test_runtime_mount_app_groups_rejects_existing_config_group() -> None:
    kit = build_config_only_example_app()
    app = typer.Typer()
    app.add_typer(typer.Typer(), name="config")
    runtime = CliRuntime[CliRuntimeOptions, ConfigOnlyExampleState](kit)

    with pytest.raises(RuntimeError, match="already has a command or group"):
        runtime.mount_app_groups(app)


def test_config_only_app_cli_resolves_explicit_environment_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("CONFIG_ONLY_APP_PROFILE", "from-shell")
    env_file = tmp_path / "explicit.env"
    env_file.write_text(
        "CONFIG_ONLY_APP_PROFILE=from-file\n",
        encoding="utf-8",
    )
    app = typer.Typer()
    mount_app_cli(app, build_config_only_example_app())

    @app.command()
    def run(ctx: typer.Context) -> None:
        context = cli_runtime_context_from(ctx)
        assert context is not None and context.resolved is not None
        typer.echo(context.resolved.build(ConfigOnlyExampleEnv).profile)

    result = CliRunner().invoke(app, ["--env-file", str(env_file), "run"])

    assert result.exit_code == 0, result.output
    assert result.output.strip() == "from-shell"
