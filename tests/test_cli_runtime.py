from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, cast

import pytest
import typer
from typer.testing import CliRunner

from apprc.definition.paths import Layout
from apprc.interfaces.cli import (
    COMMON_CLI_FLAG_OPTIONS,
    COMMON_CLI_VALUE_OPTIONS,
    CliRuntime,
    CliRuntimeContext,
    CliRuntimeOptions,
    CliRuntimePolicy,
    CliRuntimeSession,
    ConfigRuntimePolicy,
    DefaultConfigCliState,
    RuntimeIndependentCommand,
    cli_options_from,
)
from apprc.runtime.resolution import ResolvedConfig
from tests.support_config import (
    ConfigOnlyExampleState,
    WorkspaceExampleEnv,
    WorkspaceExampleState,
    build_config_only_example_app,
    build_workspace_example_app,
    register_workspace_for_app,
)


@dataclass(slots=True)
class _FakeContext:
    """Tiny context stand-in for policy tests."""

    invoked_subcommand: str | None


@dataclass(frozen=True, slots=True)
class HostOptions:
    """AppRC options plus app-specific CLI fields."""

    env_files: Sequence[Path] | None = None
    env_file_overrides_os_environ: bool = False
    load_dotenv_layers: bool = True
    workspace: str | None = None
    layout: Layout | None = None
    log_level: str | None = None
    workdir_base: Path | None = None
    model: str | None = None


@dataclass(slots=True)
class HostState:
    """Host runtime state built from AppRC context and app options."""

    resolved: ResolvedConfig | None = None
    workspace: str | None = None
    workdir_base: Path | None = None
    model: str | None = None


def test_runtime_independent_command_matches_empty_and_declared_actions() -> (
    None
):
    command = RuntimeIndependentCommand(
        skip_empty=True,
        exact_actions={("benchmark",)},
        action_prefixes={("cache",)},
    )
    flag_options = {"--ignore-cache"}
    value_options = {"--workdir-base"}

    assert command.matches(
        [], flag_options=flag_options, value_options=value_options
    )
    assert command.matches(
        ["--workdir-base", "/tmp/project", "--ignore-cache", "cache"],
        flag_options=flag_options,
        value_options=value_options,
    )
    assert command.matches(
        ["cache", "--json"],
        flag_options=flag_options,
        value_options=value_options,
    )
    assert command.matches(
        ["cache", "--help"],
        flag_options=flag_options,
        value_options=value_options,
    )
    assert not command.matches(
        ["benchmark", "--json"],
        flag_options=flag_options,
        value_options=value_options,
    )
    assert not command.matches(
        ["query"], flag_options=flag_options, value_options=value_options
    )
    assert not RuntimeIndependentCommand().matches(
        [], flag_options=flag_options, value_options=value_options
    )


def test_runtime_independent_command_respects_help_and_separator() -> None:
    command = RuntimeIndependentCommand(
        exact_actions={("benchmark",)},
        action_prefixes={("cache",)},
        skip_help=False,
    )
    assert not command.matches(
        ["--help"], flag_options=set(), value_options=set()
    )
    assert not command.matches(
        ["benchmark", "--help"], flag_options=set(), value_options=set()
    )
    assert not command.matches(
        ["cache", "--", "--json"], flag_options=set(), value_options=set()
    )
    assert command.matches(["cache"], flag_options=set(), value_options=set())


def test_runtime_independent_command_rejects_empty_action_paths() -> None:
    with pytest.raises(ValueError, match="skip_empty=True"):
        RuntimeIndependentCommand(exact_actions={()})
    with pytest.raises(ValueError, match="skip_empty=True"):
        RuntimeIndependentCommand(action_prefixes={()})


def test_runtime_policy_merges_workspace_layout_and_host_options() -> None:
    policy = CliRuntimePolicy(
        extra_cli_flag_options={"--ignore-cache"},
        extra_cli_value_options={"--workdir-base"},
    )

    assert "--env-file-overrides-os-environ" in policy.cli_flag_options
    assert "--ignore-cache" in policy.cli_flag_options
    assert "--workspace" in policy.cli_value_options
    assert "--layout" in policy.cli_value_options
    assert "--app-root" in policy.cli_value_options
    assert "--workdir-base" in policy.cli_value_options
    assert COMMON_CLI_FLAG_OPTIONS <= set(policy.cli_flag_options)
    assert COMMON_CLI_VALUE_OPTIONS <= set(policy.cli_value_options)
    assert policy.request_skips_runtime(
        _ctx("config"),
        tokens=[
            "--workspace",
            "alpha",
            "--workdir-base",
            "/tmp/project",
            "config",
            "paths",
        ],
        config_group_name="config",
    )


def test_runtime_policy_skips_maintenance_and_config_paths() -> None:
    policy = CliRuntimePolicy(
        runtime_independent_commands={
            "tool": RuntimeIndependentCommand(skip_empty=True),
        },
    )

    assert policy.request_skips_runtime(
        _ctx("tool"), tokens=["tool"], config_group_name="config"
    )
    assert not policy.request_skips_runtime(
        _ctx("run"),
        tokens=["run", "--text", "--help"],
        config_group_name="config",
    )


def test_runtime_builds_host_state_and_forwards_app_options(
    tmp_path: Path,
) -> None:
    kit = build_config_only_example_app()
    args = [
        "--workdir-base",
        str(tmp_path),
        "--model",
        "example-model",
        "run",
    ]
    app = typer.Typer()
    sessions: list[CliRuntimeSession[HostState]] = []
    factory_calls: list[tuple[CliRuntimeContext, HostOptions]] = []
    runtime = CliRuntime[HostOptions, HostState](
        kit,
        state_type=HostState,
        state_factory=lambda context, options: (
            factory_calls.append((context, options))
            or HostState(
                resolved=context.resolved,
                workspace=options.workspace,
                workdir_base=options.workdir_base,
                model=options.model,
            )
        ),
        args_provider=lambda: args,
    )

    @app.callback()
    def host_callback(
        ctx: typer.Context,
        workspace: Annotated[str | None, typer.Option("--workspace")] = None,
        workdir_base: Annotated[
            Path | None,
            typer.Option("--workdir-base"),
        ] = None,
        model: Annotated[str | None, typer.Option("--model")] = None,
    ) -> None:
        sessions.append(
            runtime.prepare(
                ctx,
                HostOptions(
                    workspace=workspace,
                    workdir_base=workdir_base,
                    model=model,
                ),
            )
        )

    @app.command()
    def run(ctx: typer.Context) -> None:
        state = ctx.obj
        assert isinstance(state, HostState)
        options = cli_options_from(ctx, HostOptions)
        typer.echo(
            json.dumps(
                {
                    "model": state.model,
                    "workdir_base": str(state.workdir_base),
                    "typed_model": options.model,
                },
                sort_keys=True,
            )
        )

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "model": "example-model",
        "typed_model": "example-model",
        "workdir_base": str(tmp_path),
    }
    assert len(factory_calls) == 1
    assert sessions[0].state is not None
    assert not sessions[0].runtime_setup_skipped


def test_runtime_skips_state_for_independent_command_and_preserves_ctx_obj() -> (
    None
):
    kit = build_config_only_example_app()
    args = ["tool"]
    app = typer.Typer()
    marker = {"preexisting": True}
    objects_after_prepare: list[object | None] = []
    factory_calls: list[CliRuntimeContext] = []
    runtime = CliRuntime[CliRuntimeOptions, ConfigOnlyExampleState](
        kit,
        state_type=ConfigOnlyExampleState,
        state_factory=lambda context, _options: (
            factory_calls.append(context)
            or ConfigOnlyExampleState(resolved=context.resolved)
        ),
        runtime_policy=CliRuntimePolicy(
            runtime_independent_commands={
                "tool": RuntimeIndependentCommand(skip_empty=True),
            },
        ),
        args_provider=lambda: args,
    )

    @app.callback()
    def host_callback(ctx: typer.Context) -> None:
        ctx.obj = marker
        session = runtime.prepare(ctx, CliRuntimeOptions())
        objects_after_prepare.append(ctx.obj)
        assert session.runtime_setup_skipped

    @app.command()
    def tool(ctx: typer.Context) -> None:
        typer.echo(str(ctx.obj is marker).lower())

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    assert result.output.strip() == "true"
    assert objects_after_prepare == [marker]
    assert factory_calls == []


def test_cli_runtime_run_forwarded_uses_child_args_for_runtime_policy() -> None:
    kit = build_config_only_example_app()
    parent_app = typer.Typer()
    child_app = typer.Typer()
    child_runtime = CliRuntime[CliRuntimeOptions, DefaultConfigCliState](
        kit,
        runtime_policy=CliRuntimePolicy(
            runtime_independent_commands={
                "status": RuntimeIndependentCommand(skip_empty=True),
            },
        ),
    )
    sessions: list[CliRuntimeSession[DefaultConfigCliState]] = []

    @child_app.callback()
    def child_callback(ctx: typer.Context) -> None:
        sessions.append(child_runtime.prepare(ctx, CliRuntimeOptions()))

    @child_app.command()
    def status() -> None:
        typer.echo("child-status")

    @parent_app.command()
    def forward() -> None:
        child_runtime.run_forwarded(
            child_app,
            args=["status"],
            prog_name="child",
        )

    result = CliRunner().invoke(parent_app, [])

    assert result.exit_code == 0, result.output
    assert result.output.strip() == "child-status"
    assert sessions[0].runtime_setup_skipped


def test_runtime_resolves_workspace_and_environment_precedence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    kit = build_workspace_example_app()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    register_workspace_for_app(kit, name="alpha", root=tmp_path / "workspace")
    env_file = tmp_path / "explicit.env"
    env_file.write_text(
        "APPRC_EXAMPLE_APP_PROFILE=from-file\n"
        "APPRC_EXAMPLE_APP_ACCESS_TOKEN=secret\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("APPRC_EXAMPLE_APP_PROFILE", "from-shell")
    args = ["--workspace", "alpha", "--env-file", str(env_file), "run"]
    app = typer.Typer()
    runtime = CliRuntime[CliRuntimeOptions, WorkspaceExampleState](
        kit,
        state_type=WorkspaceExampleState,
        state_factory=lambda context, options: WorkspaceExampleState(
            resolved=context.resolved,
            workspace=options.workspace,
        ),
        args_provider=lambda: args,
    )

    @app.callback()
    def host_callback(
        ctx: typer.Context,
        workspace: Annotated[str | None, typer.Option("--workspace")] = None,
        env_files: Annotated[
            list[Path] | None, typer.Option("--env-file")
        ] = None,
    ) -> None:
        runtime.prepare(
            ctx,
            CliRuntimeOptions.from_typer(
                workspace=workspace, env_files=env_files
            ),
        )

    @app.command()
    def run(ctx: typer.Context) -> None:
        state = ctx.obj
        assert isinstance(state, WorkspaceExampleState)
        assert state.resolved is not None
        typer.echo(state.resolved.build(WorkspaceExampleEnv).profile)

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    assert result.output.strip() == "from-shell"


def test_config_policy_can_override_runtime_independent_actions() -> None:
    policy = ConfigRuntimePolicy(
        runtime_independent_actions={"doctor", "paths"}
    )
    assert policy.request_skips_runtime(tokens=["config", "paths"])
    assert not policy.request_skips_runtime(
        tokens=["config", "set", "profile", "demo"]
    )


def _ctx(command_name: str | None) -> typer.Context:
    return cast(typer.Context, _FakeContext(command_name))


def test_installation_recovery_preserves_app_owned_ctx_obj() -> None:
    kit = build_config_only_example_app()
    app = typer.Typer()
    marker = {"application": "owned"}
    args = ["installation", "show"]
    runtime = CliRuntime[CliRuntimeOptions, ConfigOnlyExampleState](
        kit,
        args_provider=lambda: args,
    )
    sessions: list[CliRuntimeSession[ConfigOnlyExampleState]] = []
    objects_after_prepare: list[object | None] = []

    @app.callback()
    def host_callback(ctx: typer.Context) -> None:
        ctx.obj = marker
        sessions.append(runtime.prepare(ctx, CliRuntimeOptions()))
        objects_after_prepare.append(ctx.obj)

    installation = typer.Typer()
    app.add_typer(installation, name="installation")

    @installation.command("show")
    def show() -> None:
        typer.echo("installation diagnostics available")

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    assert objects_after_prepare == [marker]
    assert sessions[0].runtime_setup_skipped
