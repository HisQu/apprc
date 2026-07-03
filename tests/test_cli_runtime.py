from __future__ import annotations

import json
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import FrozenInstanceError, dataclass
from pathlib import Path
from typing import Annotated, Any, cast

import pytest
import typer
from typer.testing import CliRunner

from apprc.definition.app_config.kit import AppConfigKit
from apprc.interfaces.cli import (
    RuntimeIndependentCommand,
    CliArgvProvider,
    CliRuntimeContext,
    COMMON_CLI_FLAG_OPTIONS,
    COMMON_CLI_VALUE_OPTIONS,
    ConfigRuntimePolicy,
    CliRuntime,
    CliRuntimeSession,
    DEFAULT_CONFIG_RUNTIME_INDEPENDENT_ACTIONS,
    DefaultConfigCliState,
    EnvFileOverridesOption,
    EnvFilesOption,
    CliRuntimePolicy,
    LogLevelOption,
    SkipDotenvLayersOption,
    StorageOption,
    cli_options_from,
)
from tests.support_config import (
    StorageFreeExampleEnv,
    build_apprc_example_app_kit,
    build_storage_free_example_kit,
)


@dataclass(slots=True)
class _FakeContext:
    """Tiny context stand-in for policy tests."""

    invoked_subcommand: str | None


@dataclass(frozen=True, slots=True)
class HaiuLikeOptions:
    """Host options with AppRC fields plus app-specific CLI fields."""

    env_files: Sequence[Path] | None = None
    env_file_overrides_os_environ: bool = False
    load_dotenv_layers: bool = True
    storage: str | None = None
    log_level: str | None = None
    workdir_base: Path | None = None
    model_llm: str | None = None
    model_embed: str | None = None
    base_url: str | None = None
    ignore_haiu_cache: bool = False


@dataclass(slots=True)
class HaiuLikeState(DefaultConfigCliState):
    """Host runtime state built from AppRC context and app options."""

    workdir_base: Path | None = None
    model_llm: str | None = None
    model_embed: str | None = None
    base_url: str | None = None
    ignore_haiu_cache: bool = False


def test_runtime_independent_command_matches_empty_and_declared_actions() -> (
    None
):
    command = RuntimeIndependentCommand(
        skip_empty=True,
        exact_actions={("benchmark",)},
        action_prefixes={("cache",)},
    )
    flag_options = {"--ignore-haiu-cache"}
    value_options = {"--workdir-base"}

    assert command.matches(
        [],
        flag_options=flag_options,
        value_options=value_options,
    )
    assert command.matches(
        ["--workdir-base", "/tmp/project", "--ignore-haiu-cache", "cache"],
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
        ["query"],
        flag_options=flag_options,
        value_options=value_options,
    )
    assert not RuntimeIndependentCommand().matches(
        [],
        flag_options=flag_options,
        value_options=value_options,
    )


def test_runtime_independent_command_can_require_runtime_for_help() -> None:
    command = RuntimeIndependentCommand(
        action_prefixes={("cache",)},
        skip_help=False,
    )

    assert not command.matches(
        ["--help"],
        flag_options=set(),
        value_options=set(),
    )
    assert not command.matches(
        ["cache", "--help"],
        flag_options=set(),
        value_options=set(),
    )
    assert command.matches(
        ["cache"],
        flag_options=set(),
        value_options=set(),
    )
    assert command.matches(
        ["cache", "--json"],
        flag_options=set(),
        value_options=set(),
    )


def test_runtime_independent_command_rejects_empty_action_paths() -> None:
    with pytest.raises(ValueError, match="skip_empty=True"):
        RuntimeIndependentCommand(exact_actions={()})
    with pytest.raises(ValueError, match="skip_empty=True"):
        RuntimeIndependentCommand(action_prefixes={()})


def test_runtime_independent_command_exact_action_help_respects_skip_help() -> (
    None
):
    help_skips = RuntimeIndependentCommand(exact_actions={("benchmark",)})
    help_bootstraps = RuntimeIndependentCommand(
        exact_actions={("benchmark",)},
        skip_help=False,
    )

    assert help_skips.matches(
        ["benchmark", "--help"],
        flag_options=set(),
        value_options=set(),
    )
    assert not help_bootstraps.matches(
        ["benchmark", "--help"],
        flag_options=set(),
        value_options=set(),
    )
    assert help_bootstraps.matches(
        ["benchmark"],
        flag_options=set(),
        value_options=set(),
    )


def test_host_cli_runtime_policy_handles_haiu_shaped_commands() -> None:
    policy = _haiu_policy()

    assert policy.request_skips_runtime(
        _ctx("tool"),
        tokens=["tool"],
        config_group_name="config",
    )
    assert policy.request_skips_runtime(
        _ctx("llm"),
        tokens=["llm", "benchmark"],
        config_group_name="config",
    )
    assert policy.request_skips_runtime(
        _ctx("rag"),
        tokens=[
            "--workdir-base",
            "/tmp/project",
            "rag",
            "--ignore-haiu-cache",
            "cache",
        ],
        config_group_name="config",
    )
    assert policy.request_skips_runtime(
        _ctx("rag"),
        tokens=["rag", "cache", "--json"],
        config_group_name="config",
    )
    assert policy.request_skips_runtime(
        _ctx("rag"),
        tokens=["rag", "benchmark", "minimum"],
        config_group_name="config",
    )
    assert policy.request_skips_runtime(
        _ctx("run"),
        tokens=["run", "--help"],
        config_group_name="config",
    )
    assert policy.request_skips_runtime(
        _ctx("tool"),
        tokens=["tool", "--help"],
        config_group_name="config",
    )
    assert policy.request_skips_runtime(
        _ctx("rag"),
        tokens=["rag", "cache", "--help"],
        config_group_name="config",
    )
    assert not policy.request_skips_runtime(
        _ctx("rag"),
        tokens=["rag", "query"],
        config_group_name="config",
    )
    assert not policy.request_skips_runtime(
        _ctx("run"),
        tokens=["run", "--text", "--help"],
        config_group_name="config",
    )
    assert policy.request_skips_runtime(
        _ctx("run"),
        tokens=["run", "-h"],
        config_group_name="config",
    )
    assert not policy.request_skips_runtime(
        _ctx("run"),
        tokens=["run", "--", "--help"],
        config_group_name="config",
    )
    assert not policy.request_skips_runtime(
        _ctx("run"),
        tokens=["run", "--", "--text"],
        config_group_name="config",
    )


def test_host_cli_runtime_policy_custom_config_actions() -> None:
    policy = _haiu_policy(
        config_runtime_independent_actions=(
            DEFAULT_CONFIG_RUNTIME_INDEPENDENT_ACTIONS - {"set"}
        ),
    )

    assert policy.request_skips_runtime(
        _ctx("config"),
        tokens=["config", "paths"],
        config_group_name="config",
    )
    assert not policy.request_skips_runtime(
        _ctx("config"),
        tokens=["config", "set", "profile", "demo"],
        config_group_name="config",
    )


def test_host_cli_runtime_policy_merges_standard_options() -> None:
    policy = CliRuntimePolicy(
        extra_cli_flag_options={"--ignore-haiu-cache"},
        extra_cli_value_options={"--workdir-base"},
    )

    assert "--env-file-overrides-os-environ" in policy.cli_flag_options
    assert "--ignore-haiu-cache" in policy.cli_flag_options
    assert "--storage" in policy.cli_value_options
    assert "--workdir-base" in policy.cli_value_options
    assert COMMON_CLI_FLAG_OPTIONS <= set(policy.cli_flag_options)
    assert COMMON_CLI_VALUE_OPTIONS <= set(policy.cli_value_options)
    assert policy.request_skips_runtime(
        _ctx("config"),
        tokens=[
            "--storage",
            "demo",
            "--workdir-base",
            "/tmp/project",
            "config",
            "paths",
        ],
        config_group_name="config",
    )


def test_host_cli_runtime_policy_config_uses_extra_host_options() -> None:
    policy = CliRuntimePolicy(
        extra_cli_value_options={"--workdir"},
    )

    assert policy.request_skips_runtime(
        _ctx("config"),
        tokens=[
            "--workdir",
            "/tmp/project",
            "config",
            "paths",
        ],
        config_group_name="config",
    )


def test_host_cli_runtime_policy_command_map_is_read_only() -> None:
    policy = CliRuntimePolicy(
        runtime_independent_commands={
            "tool": RuntimeIndependentCommand(skip_empty=True),
        },
    )

    with pytest.raises(TypeError):
        cast(Any, policy.runtime_independent_commands)["run"] = (
            RuntimeIndependentCommand(skip_empty=True)
        )


def test_config_cli_runtime_builds_state_for_host_command(
    tmp_path: Path,
) -> None:
    kit = _build_storage_free_kit_with_shared_env()
    args = [
        "--workdir-base",
        str(tmp_path),
        "--model-llm",
        "gpt-test",
        "--model-embed",
        "embed-test",
        "--base-url",
        "https://example.invalid",
        "--ignore-haiu-cache",
        "run",
    ]
    app = typer.Typer()
    factory_calls: list[tuple[CliRuntimeContext, HaiuLikeOptions]] = []
    sessions: list[CliRuntimeSession[HaiuLikeState]] = []
    _install_haiu_like_runtime(
        app,
        kit,
        args_provider=lambda: args,
        factory_calls=factory_calls,
        sessions=sessions,
    )

    @app.command()
    def run(ctx: typer.Context) -> None:
        state = ctx.obj
        if not isinstance(state, HaiuLikeState):
            raise RuntimeError("Haiu-like state missing.")
        typer.echo(
            json.dumps(
                {
                    "base_url": state.base_url,
                    "bootstrapped": state.env_bootstrap is not None,
                    "ignore_cache": state.ignore_haiu_cache,
                    "model_embed": state.model_embed,
                    "model_llm": state.model_llm,
                    "workdir_base": str(state.workdir_base),
                },
                sort_keys=True,
            )
        )

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "base_url": "https://example.invalid",
        "bootstrapped": True,
        "ignore_cache": True,
        "model_embed": "embed-test",
        "model_llm": "gpt-test",
        "workdir_base": str(tmp_path),
    }
    assert len(factory_calls) == 1
    assert factory_calls[0][1].model_llm == "gpt-test"
    assert isinstance(sessions[0], CliRuntimeSession)
    assert sessions[0].state is not None
    assert sessions[0].state.model_llm == "gpt-test"
    assert not sessions[0].runtime_setup_skipped


def test_config_cli_runtime_default_state_for_host_command() -> None:
    kit = _build_storage_free_kit_with_shared_env()
    args = ["--storage", "demo", "run"]
    app = typer.Typer()
    sessions: list[CliRuntimeSession[DefaultConfigCliState]] = []
    runtime = CliRuntime[HaiuLikeOptions, DefaultConfigCliState](
        kit,
        args_provider=lambda: args,
    )

    @app.callback()
    def host_callback(
        ctx: typer.Context,
        storage: StorageOption = None,
    ) -> None:
        session = runtime.prepare(ctx, HaiuLikeOptions(storage=storage))
        sessions.append(session)

    @app.command()
    def run(ctx: typer.Context) -> None:
        state = ctx.obj
        if not isinstance(state, DefaultConfigCliState):
            raise RuntimeError("default state missing")
        typer.echo(
            json.dumps(
                {
                    "bootstrapped": state.env_bootstrap is not None,
                    "storage": state.storage,
                },
                sort_keys=True,
            )
        )

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "bootstrapped": True,
        "storage": "demo",
    }
    assert isinstance(sessions[0].state, DefaultConfigCliState)


def test_config_cli_runtime_custom_state_requires_factory() -> None:
    kit = _build_storage_free_kit_with_shared_env()

    with pytest.raises(TypeError, match="state_factory"):
        CliRuntime[HaiuLikeOptions, HaiuLikeState](
            kit,
            state_type=HaiuLikeState,
        )


def test_config_cli_runtime_runtime_command_accepts_help_like_value() -> None:
    kit = _build_storage_free_kit_with_shared_env()
    args = ["run", "--text", "--help"]
    app = typer.Typer()
    factory_calls: list[tuple[CliRuntimeContext, HaiuLikeOptions]] = []
    _install_haiu_like_runtime(
        app,
        kit,
        args_provider=lambda: args,
        factory_calls=factory_calls,
    )

    @app.command()
    def run(
        ctx: typer.Context,
        text: Annotated[str, typer.Option("--text")],
    ) -> None:
        typer.echo(
            json.dumps(
                {
                    "state": isinstance(ctx.obj, HaiuLikeState),
                    "text": text,
                },
                sort_keys=True,
            )
        )

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "state": True,
        "text": "--help",
    }
    assert len(factory_calls) == 1


def test_config_cli_runtime_runtime_independent_command_preserves_existing_ctx_obj() -> (
    None
):
    kit = _build_storage_free_kit_with_shared_env()
    args = ["tool"]
    app = typer.Typer()
    marker = {"preexisting": True}
    objects_after_prepare: list[object | None] = []
    factory_calls: list[tuple[CliRuntimeContext, HaiuLikeOptions]] = []
    runtime = CliRuntime[HaiuLikeOptions, HaiuLikeState](
        kit,
        state_type=HaiuLikeState,
        state_factory=_empty_state_factory,
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
        session = runtime.prepare(ctx, HaiuLikeOptions())
        objects_after_prepare.append(ctx.obj)
        if not session.runtime_setup_skipped:
            factory_calls.append((session.apprc_context, HaiuLikeOptions()))

    @app.command()
    def tool(ctx: typer.Context) -> None:
        typer.echo(str(ctx.obj is marker).lower())

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    assert result.output.strip() == "true"
    assert objects_after_prepare == [marker]
    assert factory_calls == []


def test_config_cli_runtime_runtime_independent_command_preserves_cli_options(
    tmp_path: Path,
) -> None:
    kit = _build_storage_free_kit_with_shared_env()
    args = ["--workdir-base", str(tmp_path), "tool"]
    app = typer.Typer()
    runtime = CliRuntime[HaiuLikeOptions, HaiuLikeState](
        kit,
        state_type=HaiuLikeState,
        state_factory=_empty_state_factory,
        runtime_policy=CliRuntimePolicy(
            runtime_independent_commands={
                "tool": RuntimeIndependentCommand(skip_empty=True),
            },
            extra_cli_value_options={"--workdir-base"},
        ),
        args_provider=lambda: args,
    )

    @app.callback()
    def host_callback(
        ctx: typer.Context,
        workdir_base: Annotated[
            Path | None,
            typer.Option("--workdir-base"),
        ] = None,
    ) -> None:
        runtime.prepare(
            ctx,
            HaiuLikeOptions(workdir_base=workdir_base),
        )

    @app.command()
    def tool(ctx: typer.Context) -> None:
        options = cli_options_from(ctx, HaiuLikeOptions)
        typer.echo(str(options.workdir_base))

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    assert result.output.strip() == str(tmp_path)


def test_cli_runtime_run_forwarded_uses_child_args_for_runtime_policy() -> None:
    kit = _build_storage_free_kit_with_shared_env()
    parent_app = typer.Typer()
    child_app = typer.Typer()
    child_runtime = CliRuntime[HaiuLikeOptions, DefaultConfigCliState](
        kit,
        runtime_policy=CliRuntimePolicy(
            runtime_independent_commands={
                "status": RuntimeIndependentCommand(skip_empty=True),
            },
        ),
    )
    child_sessions: list[CliRuntimeSession[DefaultConfigCliState]] = []

    @child_app.callback()
    def child_callback(ctx: typer.Context) -> None:
        child_sessions.append(child_runtime.prepare(ctx, HaiuLikeOptions()))

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
    assert child_sessions[0].runtime_setup_skipped is True


def test_config_cli_runtime_runtime_command_help_skips_state_factory() -> None:
    APPRC_EXAMPLE_APP_KIT = build_apprc_example_app_kit()

    args = ["run", "--help"]
    app = typer.Typer()
    factory_calls: list[tuple[CliRuntimeContext, HaiuLikeOptions]] = []
    _install_haiu_like_runtime(
        app,
        APPRC_EXAMPLE_APP_KIT,
        args_provider=lambda: args,
        factory_calls=factory_calls,
    )

    @app.command()
    def run() -> None:
        typer.echo("should not run")

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    assert "Usage:" in result.output
    assert factory_calls == []


def test_config_cli_runtime_runtime_independent_paths_uses_context_only(
    tmp_path: Path,
) -> None:
    kit = build_storage_free_example_kit()
    first_env = tmp_path / "first.env"
    second_env = tmp_path / "second.env"
    first_env.write_text("STORAGE_FREE_APP_PROFILE=first\n", encoding="utf-8")
    second_env.write_text(
        "STORAGE_FREE_APP_PROFILE=second\n",
        encoding="utf-8",
    )
    args = [
        "--env-file",
        str(first_env),
        "--env-file",
        str(second_env),
        "--workdir-base",
        str(tmp_path),
        "settings",
        "paths",
        "--json",
    ]
    app = typer.Typer()
    factory_calls: list[tuple[CliRuntimeContext, HaiuLikeOptions]] = []
    _install_haiu_like_runtime(
        app,
        kit,
        args_provider=lambda: args,
        factory_calls=factory_calls,
        config_group_name="settings",
    )

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    assert factory_calls == []
    payload = json.loads(result.output)
    assert payload["writes"] == "none"
    assert payload["capabilities"]["app_wide"] == "default"


def test_config_cli_runtime_rejects_direct_config_policy_group_drift() -> None:
    kit = _build_storage_free_kit_with_shared_env()

    with pytest.raises(ValueError, match="config_group_name"):
        CliRuntime[HaiuLikeOptions, HaiuLikeState](
            kit,
            state_type=HaiuLikeState,
            state_factory=_empty_state_factory,
            config_group_name="settings",
            runtime_policy=ConfigRuntimePolicy(config_group_name="config"),
        )


def test_config_cli_runtime_direct_config_policy_controls_skip() -> None:
    kit = _build_storage_free_kit_with_shared_env()
    args = ["config", "paths", "--json"]
    app = typer.Typer()
    factory_calls: list[tuple[CliRuntimeContext, HaiuLikeOptions]] = []
    _install_haiu_like_runtime(
        app,
        kit,
        args_provider=lambda: args,
        factory_calls=factory_calls,
        runtime_policy=ConfigRuntimePolicy(
            runtime_independent_actions=(
                DEFAULT_CONFIG_RUNTIME_INDEPENDENT_ACTIONS - {"paths"}
            ),
        ),
    )

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    assert len(factory_calls) == 1


def test_config_cli_runtime_is_frozen() -> None:
    kit = _build_storage_free_kit_with_shared_env()
    runtime = CliRuntime[HaiuLikeOptions, HaiuLikeState](
        kit,
        state_type=HaiuLikeState,
        state_factory=_empty_state_factory,
    )

    with pytest.raises(FrozenInstanceError):
        setattr(runtime, "config_group_name", "settings")


def test_config_cli_runtime_runtime_independent_set_skips_state_factory(
    tmp_path: Path,
) -> None:
    kit = build_apprc_example_app_kit()
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    args = [
        "--storage",
        str(storage_root),
        "config",
        "set",
        "access_token",
        "secret-value",
        "--scope",
        "storage",
    ]
    app = typer.Typer()
    factory_calls: list[tuple[CliRuntimeContext, HaiuLikeOptions]] = []
    _install_haiu_like_runtime(
        app,
        kit,
        args_provider=lambda: args,
        factory_calls=factory_calls,
    )

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    assert factory_calls == []
    assert 'APPRC_EXAMPLE_APP_ACCESS_TOKEN="secret-value"\n' in (
        storage_root / ".env.apprc-storage"
    ).read_text(encoding="utf-8")


def test_config_cli_runtime_runtime_payload_receives_app_state() -> None:
    kit = _build_storage_free_kit_with_shared_env()
    args = ["--model-llm", "payload-model", "config", "show", "--json"]
    app = typer.Typer()
    factory_calls: list[tuple[CliRuntimeContext, HaiuLikeOptions]] = []

    def runtime_payload(state: HaiuLikeState) -> Mapping[str, Any]:
        return {
            "bootstrapped": state.env_bootstrap is not None,
            "model_llm": state.model_llm,
        }

    _install_haiu_like_runtime(
        app,
        kit,
        args_provider=lambda: args,
        factory_calls=factory_calls,
        runtime_payload=runtime_payload,
    )

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "bootstrapped": True,
        "model_llm": "payload-model",
    }
    assert len(factory_calls) == 1


def test_config_cli_runtime_state_factory_type_mismatch_raises() -> None:
    kit = _build_storage_free_kit_with_shared_env()
    app = typer.Typer()
    args = ["run"]
    factory_calls: list[tuple[CliRuntimeContext, HaiuLikeOptions]] = []

    def bad_factory(
        context: CliRuntimeContext,
        options: HaiuLikeOptions,
    ) -> Any:
        return DefaultConfigCliState(env_bootstrap=context.env_bootstrap)

    _install_haiu_like_runtime(
        app,
        kit,
        args_provider=lambda: args,
        factory_calls=factory_calls,
        state_factory=bad_factory,
    )

    @app.command()
    def run() -> None:
        typer.echo("should not run")

    with pytest.raises(RuntimeError, match="expected HaiuLikeState"):
        CliRunner().invoke(app, args, catch_exceptions=False)


def test_config_cli_runtime_mount_config_group_custom_name() -> None:
    kit = build_storage_free_example_kit()
    app = typer.Typer()
    args = ["settings", "paths", "--json"]
    factory_calls: list[tuple[CliRuntimeContext, HaiuLikeOptions]] = []
    _install_haiu_like_runtime(
        app,
        kit,
        args_provider=lambda: args,
        factory_calls=factory_calls,
        config_group_name="settings",
    )

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    assert "storage_free_app" in result.output


def test_config_cli_runtime_rejects_existing_config_group_name() -> None:
    kit = _build_storage_free_kit_with_shared_env()
    app = typer.Typer()
    app.add_typer(typer.Typer(), name="config")
    runtime = CliRuntime[HaiuLikeOptions, DefaultConfigCliState](kit)

    with pytest.raises(RuntimeError, match="already has a command or group"):
        runtime.mount_config_group(app)


def test_config_cli_runtime_runtimeful_config_requires_app_state() -> None:
    kit = _build_storage_free_kit_with_shared_env()
    args = ["config", "show", "--json"]
    app = typer.Typer()
    runtime = CliRuntime[HaiuLikeOptions, HaiuLikeState](
        kit,
        state_type=HaiuLikeState,
        state_factory=_empty_state_factory,
        args_provider=lambda: args,
    )

    @app.callback()
    def host_callback(ctx: typer.Context) -> None:
        runtime.prepare(ctx, HaiuLikeOptions())
        ctx.obj = object()

    runtime.mount_config_group(app)

    with pytest.raises(RuntimeError, match="CLI state is not initialized"):
        CliRunner().invoke(app, args, catch_exceptions=False)


def _ctx(command_name: str | None) -> typer.Context:
    return cast(typer.Context, _FakeContext(command_name))


def _build_storage_free_kit_with_shared_env() -> AppConfigKit:
    return AppConfigKit.app_wide_config(
        app_name="storage_free_app",
        display_name="Storage-Free App",
        config_package="apprc_storage_only_example.config",
        envs=(StorageFreeExampleEnv,),
        index_filename="storage_free_app.apprc.toml",
    )


def _haiu_policy(
    *,
    config_runtime_independent_actions: Collection[str] = (
        DEFAULT_CONFIG_RUNTIME_INDEPENDENT_ACTIONS
    ),
) -> CliRuntimePolicy:
    return CliRuntimePolicy(
        config_runtime_independent_actions=config_runtime_independent_actions,
        runtime_independent_commands={
            "tool": RuntimeIndependentCommand(skip_empty=True),
            "llm": RuntimeIndependentCommand(
                skip_empty=True,
                exact_actions={("benchmark",)},
            ),
            "rag": RuntimeIndependentCommand(
                skip_empty=True,
                action_prefixes={("cache",), ("benchmark",)},
            ),
        },
        extra_cli_flag_options={"--ignore-haiu-cache"},
        extra_cli_value_options=(
            {
                "--base-url",
                "--model-embed",
                "--model-llm",
                "--workdir-base",
            }
        ),
    )


def _empty_state_factory(
    context: CliRuntimeContext,
    options: HaiuLikeOptions,
) -> HaiuLikeState:
    return HaiuLikeState(env_bootstrap=context.env_bootstrap)


def _install_haiu_like_runtime(
    app: typer.Typer,
    kit: AppConfigKit,
    *,
    args_provider: CliArgvProvider,
    factory_calls: list[tuple[CliRuntimeContext, HaiuLikeOptions]],
    sessions: list[CliRuntimeSession[HaiuLikeState]] | None = None,
    config_group_name: str = "config",
    runtime_payload: Callable[[HaiuLikeState], Mapping[str, Any]] | None = None,
    state_factory: Callable[[CliRuntimeContext, HaiuLikeOptions], Any]
    | None = None,
    runtime_policy: ConfigRuntimePolicy | CliRuntimePolicy | None = (None),
) -> CliRuntime[HaiuLikeOptions, HaiuLikeState]:
    def default_state_factory(
        context: CliRuntimeContext,
        options: HaiuLikeOptions,
    ) -> HaiuLikeState:
        factory_calls.append((context, options))
        return HaiuLikeState(
            env_bootstrap=context.env_bootstrap,
            storage=options.storage,
            workdir_base=options.workdir_base,
            model_llm=options.model_llm,
            model_embed=options.model_embed,
            base_url=options.base_url,
            ignore_haiu_cache=options.ignore_haiu_cache,
        )

    resolved_state_factory = state_factory or default_state_factory
    runtime = CliRuntime[HaiuLikeOptions, HaiuLikeState](
        kit,
        state_type=HaiuLikeState,
        state_factory=resolved_state_factory,
        config_group_name=config_group_name,
        runtime_policy=runtime_policy or _haiu_policy(),
        args_provider=args_provider,
        runtime_payload=runtime_payload,
    )

    @app.callback()
    def host_callback(
        ctx: typer.Context,
        env_files: EnvFilesOption = None,
        env_file_overrides_os_environ: EnvFileOverridesOption = False,
        skip_dotenv_layers: SkipDotenvLayersOption = False,
        storage: StorageOption = None,
        log_level: LogLevelOption = None,
        workdir_base: Annotated[
            Path | None,
            typer.Option("--workdir-base"),
        ] = None,
        model_llm: Annotated[
            str | None,
            typer.Option("--model-llm"),
        ] = None,
        model_embed: Annotated[
            str | None,
            typer.Option("--model-embed"),
        ] = None,
        base_url: Annotated[
            str | None,
            typer.Option("--base-url"),
        ] = None,
        ignore_haiu_cache: Annotated[
            bool,
            typer.Option("--ignore-haiu-cache"),
        ] = False,
    ) -> None:
        options = HaiuLikeOptions(
            env_files=env_files,
            env_file_overrides_os_environ=(env_file_overrides_os_environ),
            load_dotenv_layers=not skip_dotenv_layers,
            storage=storage,
            log_level=log_level,
            workdir_base=workdir_base,
            model_llm=model_llm,
            model_embed=model_embed,
            base_url=base_url,
            ignore_haiu_cache=ignore_haiu_cache,
        )
        session = runtime.prepare(ctx, options)
        if sessions is not None:
            sessions.append(session)
        if session.runtime_setup_skipped:
            return

    runtime.mount_config_group(app)
    return runtime
