from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, cast

import pytest
import typer
from typer.testing import CliRunner

from apprc import AppConfigKit
from apprc.cli import (
    BootstraplessCommand,
    CliArgvProvider,
    CliBootstrapContext,
    ConfigBootstrapPolicy,
    ConfigCliBridge,
    ConfigCliSession,
    DEFAULT_CONFIG_BOOTSTRAPLESS_ACTIONS,
    DefaultConfigCliState,
    EnvFileOverridesOption,
    EnvFilesOption,
    HostCliBootstrapPolicy,
    LogLevelOption,
    SkipDotenvLayersOption,
    StorageOption,
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


def test_bootstrapless_command_matches_empty_and_declared_actions() -> None:
    command = BootstraplessCommand(
        skip_empty=True,
        actions={("cache",), ("benchmark",)},
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
    assert not command.matches(
        ["query"],
        flag_options=flag_options,
        value_options=value_options,
    )
    assert not BootstraplessCommand().matches(
        [],
        flag_options=flag_options,
        value_options=value_options,
    )


def test_host_cli_bootstrap_policy_handles_haiu_shaped_commands() -> None:
    policy = _haiu_policy()

    assert policy.request_skips_runtime_bootstrap(
        _ctx("tool"),
        tokens=["tool"],
    )
    assert policy.request_skips_runtime_bootstrap(
        _ctx("llm"),
        tokens=["llm", "benchmark"],
    )
    assert policy.request_skips_runtime_bootstrap(
        _ctx("rag"),
        tokens=[
            "--workdir-base",
            "/tmp/project",
            "rag",
            "--ignore-haiu-cache",
            "cache",
        ],
    )
    assert not policy.request_skips_runtime_bootstrap(
        _ctx("rag"),
        tokens=["rag", "query"],
    )
    assert not policy.request_skips_runtime_bootstrap(
        _ctx("run"),
        tokens=["run", "--text", "--help"],
    )


def test_host_cli_bootstrap_policy_delegates_config_policy() -> None:
    policy = _haiu_policy(
        config_policy=ConfigBootstrapPolicy(
            bootstrapless_actions=(
                DEFAULT_CONFIG_BOOTSTRAPLESS_ACTIONS - {"set"}
            ),
        ),
    )

    assert policy.request_skips_runtime_bootstrap(
        _ctx("config"),
        tokens=["config", "paths"],
    )
    assert not policy.request_skips_runtime_bootstrap(
        _ctx("config"),
        tokens=["config", "set", "profile", "demo"],
    )


def test_host_cli_bootstrap_policy_merges_standard_options() -> None:
    policy = HostCliBootstrapPolicy(
        host_flag_options={"--ignore-haiu-cache"},
        host_value_options={"--workdir-base"},
    )

    assert "--env-file-overrides-os-environ" in policy.host_flag_options
    assert "--ignore-haiu-cache" in policy.host_flag_options
    assert "--storage" in policy.host_value_options
    assert "--workdir-base" in policy.host_value_options
    assert policy.request_skips_runtime_bootstrap(
        _ctx("config"),
        tokens=[
            "--storage",
            "demo",
            "--workdir-base",
            "/tmp/project",
            "config",
            "paths",
        ],
    )


def test_host_cli_bootstrap_policy_preserves_supplied_config_policy() -> None:
    policy = HostCliBootstrapPolicy(
        config_policy=ConfigBootstrapPolicy(
            root_value_options={"--config-policy-value"},
        ),
        host_value_options={"--host-value"},
    )

    assert policy.request_skips_runtime_bootstrap(
        _ctx("config"),
        tokens=[
            "--config-policy-value",
            "demo",
            "config",
            "paths",
        ],
    )
    assert not policy.request_skips_runtime_bootstrap(
        _ctx("config"),
        tokens=["--storage", "demo", "config", "paths"],
    )


def test_host_cli_bootstrap_policy_rejects_config_policy_group_drift() -> None:
    with pytest.raises(ValueError, match="config_group_name"):
        HostCliBootstrapPolicy(
            config_group_name="settings",
            config_policy=ConfigBootstrapPolicy(config_group_name="config"),
        )


def test_config_cli_bridge_builds_state_for_host_command(
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
    factory_calls: list[tuple[CliBootstrapContext, HaiuLikeOptions]] = []
    sessions: list[ConfigCliSession[HaiuLikeState]] = []
    _install_haiu_like_bridge(
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
    assert isinstance(sessions[0], ConfigCliSession)
    assert sessions[0].state is not None
    assert sessions[0].state.model_llm == "gpt-test"
    assert not sessions[0].skipped_runtime_bootstrap


def test_config_cli_bridge_runtime_command_accepts_help_like_value() -> None:
    kit = _build_storage_free_kit_with_shared_env()
    args = ["run", "--text", "--help"]
    app = typer.Typer()
    factory_calls: list[tuple[CliBootstrapContext, HaiuLikeOptions]] = []
    _install_haiu_like_bridge(
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


def test_config_cli_bridge_bootstrapless_paths_uses_context_only(
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
    factory_calls: list[tuple[CliBootstrapContext, HaiuLikeOptions]] = []
    _install_haiu_like_bridge(
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


def test_config_cli_bridge_rejects_config_policy_group_drift() -> None:
    kit = _build_storage_free_kit_with_shared_env()

    with pytest.raises(ValueError, match="config_group_name"):
        ConfigCliBridge[HaiuLikeOptions, HaiuLikeState](
            kit,
            state_type=HaiuLikeState,
            state_factory=_empty_state_factory,
            config_group_name="settings",
            bootstrap_policy=ConfigBootstrapPolicy(config_group_name="config"),
        )


def test_config_cli_bridge_rejects_host_policy_group_drift() -> None:
    kit = _build_storage_free_kit_with_shared_env()

    with pytest.raises(ValueError, match="config_group_name"):
        ConfigCliBridge[HaiuLikeOptions, HaiuLikeState](
            kit,
            state_type=HaiuLikeState,
            state_factory=_empty_state_factory,
            config_group_name="settings",
            bootstrap_policy=HostCliBootstrapPolicy(config_group_name="config"),
        )


def test_config_cli_bridge_bootstrapless_set_skips_state_factory(
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
    factory_calls: list[tuple[CliBootstrapContext, HaiuLikeOptions]] = []
    _install_haiu_like_bridge(
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


def test_config_cli_bridge_runtime_payload_receives_app_state() -> None:
    kit = _build_storage_free_kit_with_shared_env()
    args = ["--model-llm", "payload-model", "config", "show", "--json"]
    app = typer.Typer()
    factory_calls: list[tuple[CliBootstrapContext, HaiuLikeOptions]] = []

    def runtime_payload(state: HaiuLikeState) -> Mapping[str, Any]:
        return {
            "bootstrapped": state.env_bootstrap is not None,
            "model_llm": state.model_llm,
        }

    _install_haiu_like_bridge(
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


def test_config_cli_bridge_state_factory_type_mismatch_raises() -> None:
    kit = _build_storage_free_kit_with_shared_env()
    app = typer.Typer()
    args = ["run"]
    factory_calls: list[tuple[CliBootstrapContext, HaiuLikeOptions]] = []

    def bad_factory(
        context: CliBootstrapContext,
        options: HaiuLikeOptions,
    ) -> Any:
        return DefaultConfigCliState(env_bootstrap=context.env_bootstrap)

    _install_haiu_like_bridge(
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


def test_config_cli_bridge_mount_config_group_custom_name() -> None:
    kit = build_storage_free_example_kit()
    app = typer.Typer()
    args = ["settings", "paths", "--json"]
    factory_calls: list[tuple[CliBootstrapContext, HaiuLikeOptions]] = []
    _install_haiu_like_bridge(
        app,
        kit,
        args_provider=lambda: args,
        factory_calls=factory_calls,
        config_group_name="settings",
    )

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    assert "storage_free_app" in result.output


def _ctx(command_name: str | None) -> typer.Context:
    return cast(typer.Context, _FakeContext(command_name))


def _build_storage_free_kit_with_shared_env() -> AppConfigKit:
    return AppConfigKit.app_wide_config(
        app_name="storage_free_app",
        display_name="Storage-Free App",
        config_package="apprc_example_app.config",
        envs=(StorageFreeExampleEnv,),
        index_filename="storage_free_app.apprc.toml",
    )


def _haiu_policy(
    *,
    config_group_name: str = "config",
    config_policy: ConfigBootstrapPolicy | None = None,
) -> HostCliBootstrapPolicy:
    return HostCliBootstrapPolicy(
        config_group_name=config_group_name,
        config_policy=config_policy,
        bootstrapless_commands={
            "tool": BootstraplessCommand(skip_empty=True),
            "llm": BootstraplessCommand(
                skip_empty=True,
                actions={("benchmark",)},
            ),
            "rag": BootstraplessCommand(
                skip_empty=True,
                actions={("cache",), ("benchmark",)},
            ),
        },
        host_flag_options={"--ignore-haiu-cache"},
        host_value_options=(
            {
                "--base-url",
                "--model-embed",
                "--model-llm",
                "--workdir-base",
            }
        ),
    )


def _empty_state_factory(
    context: CliBootstrapContext,
    options: HaiuLikeOptions,
) -> HaiuLikeState:
    return HaiuLikeState(env_bootstrap=context.env_bootstrap)


def _install_haiu_like_bridge(
    app: typer.Typer,
    kit: AppConfigKit,
    *,
    args_provider: CliArgvProvider,
    factory_calls: list[tuple[CliBootstrapContext, HaiuLikeOptions]],
    sessions: list[ConfigCliSession[HaiuLikeState]] | None = None,
    config_group_name: str = "config",
    runtime_payload: Callable[[HaiuLikeState], Mapping[str, Any]] | None = None,
    state_factory: Callable[[CliBootstrapContext, HaiuLikeOptions], Any]
    | None = None,
) -> ConfigCliBridge[HaiuLikeOptions, HaiuLikeState]:
    def default_state_factory(
        context: CliBootstrapContext,
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
    bridge = ConfigCliBridge[HaiuLikeOptions, HaiuLikeState](
        kit,
        state_type=HaiuLikeState,
        state_factory=resolved_state_factory,
        config_group_name=config_group_name,
        bootstrap_policy=_haiu_policy(config_group_name=config_group_name),
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
        session = bridge.prepare(ctx, options)
        if sessions is not None:
            sessions.append(session)
        if session.skipped_runtime_bootstrap:
            return

    bridge.mount_config_group(app)
    return bridge
