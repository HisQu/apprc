from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import typer
from typer.testing import CliRunner

from apprc import AppConfigKit
from apprc.cli import (
    DEFAULT_CONFIG_BOOTSTRAPLESS_ACTIONS,
    CliArgvProvider,
    CliBootstrapContext,
    CliBootstrapOptions,
    ConfigBootstrapPolicy,
    ConfigCliBridge,
    DefaultConfigCliState,
    EnvFileOverridesOption,
    EnvFilesOption,
    LogLevelOption,
    SkipDotenvLayersOption,
    StorageOption,
    apprc_context_from,
    apprc_options_to_args,
    build_config_doctor_payload,
    mount_config_cli,
    prepare_typer_context,
)
from tests.support_config import (
    StorageFreeExampleEnv,
    build_apprc_example_app_kit,
    build_storage_free_example_kit,
)


def _build_storage_free_kit_with_shared_env() -> AppConfigKit:
    """Return a storage-free kit whose package includes ``.env.shared``."""
    return AppConfigKit.app_wide_config(
        app_name="storage_free_app",
        display_name="Storage-Free App",
        config_package="apprc_example_app.config",
        envs=(StorageFreeExampleEnv,),
        index_filename="storage_free_app.apprc.toml",
    )


def test_cli_bootstrap_options_normalize_and_forward_repeated_env_files(
    tmp_path: Path,
) -> None:
    first_env = tmp_path / "first.env"
    second_env = tmp_path / "second.env"

    options = CliBootstrapOptions.from_typer(
        env_files=[first_env, second_env],
        env_file_overrides_os_environ=True,
        load_dotenv_layers=False,
        storage="alpha",
        log_level="DEBUG",
    )

    assert options.env_files == (first_env, second_env)
    assert apprc_options_to_args(options) == [
        "--log-level",
        "DEBUG",
        "--env-file",
        str(first_env),
        "--env-file",
        str(second_env),
        "--env-file-overrides-os-environ",
        "--skip-dotenv-layers",
        "--storage",
        "alpha",
    ]


def test_cli_bootstrap_options_accept_option_like_none_env_files() -> None:
    @dataclass(frozen=True, slots=True)
    class OptionLike:
        """Option object mirroring a Typer callback with no env files."""

        env_files: list[Path] | None = None
        env_file_overrides_os_environ: bool = False
        load_dotenv_layers: bool = True
        storage: str | None = None
        log_level: str | None = None

    options = CliBootstrapOptions.from_options(OptionLike())

    assert options.env_files == ()


def test_prepare_typer_context_stores_metadata_without_ctx_obj(
    tmp_path: Path,
) -> None:
    kit = build_storage_free_example_kit()
    env_file = tmp_path / "explicit.env"
    env_file.write_text(
        "STORAGE_FREE_APP_PROFILE=from-file\n", encoding="utf-8"
    )
    app = typer.Typer()

    @app.callback()
    def root_cmd(
        ctx: typer.Context,
        env_files: EnvFilesOption = None,
        env_file_overrides_os_environ: EnvFileOverridesOption = False,
        skip_dotenv_layers: SkipDotenvLayersOption = False,
        storage: StorageOption = None,
        log_level: LogLevelOption = None,
    ) -> None:
        """Store only AppRC metadata, leaving ``ctx.obj`` app-owned."""
        options = CliBootstrapOptions.from_typer(
            env_files=env_files,
            env_file_overrides_os_environ=env_file_overrides_os_environ,
            load_dotenv_layers=not skip_dotenv_layers,
            storage=storage,
            log_level=log_level,
        )
        prepare_typer_context(ctx, kit, options, skip_bootstrap=True)

    @app.command()
    def inspect(ctx: typer.Context) -> None:
        """Print the metadata seen by a child command."""
        context = apprc_context_from(ctx)
        if context is None:
            raise RuntimeError("AppRC context missing.")
        typer.echo(
            json.dumps(
                {
                    "env_files": [
                        str(path) for path in context.options.env_files
                    ],
                    "overrides": (
                        context.options.env_file_overrides_os_environ
                    ),
                    "load_dotenv_layers": (context.options.load_dotenv_layers),
                    "storage": context.options.storage,
                    "log_level": context.options.log_level,
                    "skipped": context.skipped_runtime_bootstrap,
                },
                sort_keys=True,
            )
        )

    result = CliRunner().invoke(
        app,
        [
            "--env-file",
            str(env_file),
            "--env-file-overrides-os-environ",
            "--skip-dotenv-layers",
            "--storage",
            "alpha",
            "--log-level",
            "INFO",
            "inspect",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "env_files": [str(env_file)],
        "load_dotenv_layers": False,
        "log_level": "INFO",
        "overrides": True,
        "skipped": True,
        "storage": "alpha",
    }


def test_mount_config_cli_bootstraps_simple_storage_free_app(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("STORAGE_FREE_APP_PROFILE", raising=False)
    kit = _build_storage_free_kit_with_shared_env()
    first_env = tmp_path / "first.env"
    second_env = tmp_path / "second.env"
    first_env.write_text(
        "STORAGE_FREE_APP_PROFILE=first\n",
        encoding="utf-8",
    )
    second_env.write_text(
        "STORAGE_FREE_APP_PROFILE=second\n",
        encoding="utf-8",
    )
    app = typer.Typer()
    mount_config_cli(app, kit)

    @app.command()
    def run() -> None:
        """Print a value populated by AppRC bootstrap."""
        typer.echo(StorageFreeExampleEnv().profile)

    runner = CliRunner()
    loaded = runner.invoke(
        app,
        [
            "--env-file",
            str(first_env),
            "--env-file",
            str(second_env),
            "--env-file-overrides-os-environ",
            "run",
        ],
    )
    os.environ.pop("STORAGE_FREE_APP_PROFILE", None)
    skipped = runner.invoke(
        app,
        [
            "--env-file",
            str(second_env),
            "--skip-dotenv-layers",
            "run",
        ],
    )

    assert loaded.exit_code == 0, loaded.output
    assert loaded.output.strip() == "second"
    assert skipped.exit_code == 0, skipped.output
    assert skipped.output.strip() == "default"


def test_mount_config_cli_passes_storage_to_default_config_show(
    tmp_path: Path,
) -> None:
    from apprc_example_app import APPRC_EXAMPLE_APP_KIT

    kit = APPRC_EXAMPLE_APP_KIT
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    app = typer.Typer()
    mount_config_cli(app, kit)

    result = CliRunner().invoke(
        app,
        [
            "--storage",
            str(storage_root),
            "config",
            "show",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["storage_root"] == str(storage_root.resolve())


def test_config_cli_bridge_default_policy_renders_storage_required_help() -> (
    None
):
    kit = build_apprc_example_app_kit()
    args = ["run", "--help"]
    bridge = ConfigCliBridge(kit, args_provider=lambda: args)
    app = typer.Typer()
    sessions: list[bool] = []

    @app.callback()
    def host_callback(
        ctx: typer.Context,
        storage: StorageOption = None,
    ) -> None:
        session = bridge.prepare(
            ctx,
            CliBootstrapOptions.from_typer(storage=storage),
        )
        sessions.append(session.skipped_runtime_bootstrap)

    @app.command()
    def run() -> None:
        typer.echo("should not run")

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    assert "Usage:" in result.output
    assert sessions == [True]


def test_mount_config_cli_default_policy_renders_storage_required_help() -> (
    None
):
    kit = build_apprc_example_app_kit()
    args = ["run", "--help"]
    app = typer.Typer()
    mount_config_cli(app, kit, args_provider=lambda: args)

    @app.command()
    def run() -> None:
        typer.echo("should not run")

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    assert "Usage:" in result.output
    assert "APPRC_EXAMPLE_APP_STORAGE is required" not in result.output


def test_mount_config_cli_separator_help_is_runtime_argument() -> None:
    kit = _build_storage_free_kit_with_shared_env()
    args = ["run", "--", "--help"]
    app = typer.Typer()
    mount_config_cli(app, kit, args_provider=lambda: args)

    @app.command()
    def run(ctx: typer.Context, text: str) -> None:
        typer.echo(
            json.dumps(
                {
                    "state": isinstance(ctx.obj, DefaultConfigCliState),
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


def test_mount_config_cli_state_factory_builds_app_state_for_runtime_command(
    tmp_path: Path,
) -> None:
    kit = _build_storage_free_kit_with_shared_env()
    app = typer.Typer()

    @dataclass(slots=True)
    class CustomState(DefaultConfigCliState):
        payload_marker: str = "factory-state"

    def state_factory(context: CliBootstrapContext) -> CustomState:
        """Return app-owned state after runtime bootstrap."""
        return CustomState(
            env_bootstrap=context.env_bootstrap,
            storage=context.options.storage,
        )

    mount_config_cli(
        app,
        kit,
        state_type=CustomState,
        state_factory=state_factory,
    )

    @app.command()
    def run(ctx: typer.Context) -> None:
        """Print the state type created by the mount helper."""
        state = ctx.obj
        if not isinstance(state, CustomState):
            raise RuntimeError("custom state missing")
        typer.echo(
            json.dumps(
                {
                    "marker": state.payload_marker,
                    "bootstrapped": state.env_bootstrap is not None,
                },
                sort_keys=True,
            )
        )

    result = CliRunner().invoke(app, ["run"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "bootstrapped": True,
        "marker": "factory-state",
    }


def test_mount_config_cli_bootstrapless_set_uses_context_not_app_hooks(
    tmp_path: Path,
) -> None:
    from apprc_example_app import APPRC_EXAMPLE_APP_KIT

    kit = APPRC_EXAMPLE_APP_KIT
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
    factory_calls: list[CliBootstrapContext] = []
    hook_calls: list[DefaultConfigCliState] = []

    @dataclass(slots=True)
    class CustomState(DefaultConfigCliState):
        payload_marker: str = "factory-state"

    def state_factory(context: CliBootstrapContext) -> CustomState:
        """Record unexpected runtime bootstrap for a bootstrapless command."""
        factory_calls.append(context)
        return CustomState(env_bootstrap=context.env_bootstrap)

    def active_storage_root(state: CustomState) -> Path | None:
        """Record whether app hooks see bootstrapless generic state."""
        hook_calls.append(state)
        raise RuntimeError(
            "app hook should not run for bootstrapless config set"
        )

    app = typer.Typer()
    mount_config_cli(
        app,
        kit,
        state_type=CustomState,
        state_factory=state_factory,
        args_provider=lambda: args,
        active_storage_root=active_storage_root,
    )

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    assert factory_calls == []
    assert hook_calls == []
    assert 'APPRC_EXAMPLE_APP_ACCESS_TOKEN="secret-value"\n' in (
        storage_root / ".env.apprc-storage"
    ).read_text(encoding="utf-8")


def test_mount_config_cli_runtime_payload_receives_factory_state(
    tmp_path: Path,
) -> None:
    from apprc_example_app import APPRC_EXAMPLE_APP_KIT

    kit = APPRC_EXAMPLE_APP_KIT
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    args = ["--storage", str(storage_root), "config", "show", "--json"]

    @dataclass(slots=True)
    class CustomState(DefaultConfigCliState):
        payload_marker: str = "factory-state"

    def state_factory(context: CliBootstrapContext) -> CustomState:
        """Return state that custom runtime payloads may inspect."""
        return CustomState(
            env_bootstrap=context.env_bootstrap,
            storage=context.options.storage,
        )

    def payload(state: CustomState) -> dict[str, Any]:
        """Return state details proving the payload received app state."""
        return {
            "marker": state.payload_marker,
            "bootstrapped": state.env_bootstrap is not None,
            "storage": state.storage,
        }

    app = typer.Typer()
    mount_config_cli(
        app,
        kit,
        state_type=CustomState,
        state_factory=state_factory,
        args_provider=lambda: args,
        runtime_payload=payload,
    )

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "bootstrapped": True,
        "marker": "factory-state",
        "storage": str(storage_root),
    }


def test_mount_config_cli_requires_factory_for_custom_state_type() -> None:
    kit = _build_storage_free_kit_with_shared_env()
    app = typer.Typer()

    @dataclass(slots=True)
    class CustomState(DefaultConfigCliState):
        payload_marker: str = "custom-state"

    with pytest.raises(TypeError, match="state_factory"):
        mount_config_cli(app, kit, state_type=CustomState)


def test_mount_config_cli_args_provider_controls_skip_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    kit = build_storage_free_example_kit()
    args = ["config", "paths", "--json"]
    factory_calls: list[CliBootstrapContext] = []

    def state_factory(context: CliBootstrapContext) -> DefaultConfigCliState:
        """Record runtime bootstrap when skip policy does not match."""
        factory_calls.append(context)
        return DefaultConfigCliState(env_bootstrap=context.env_bootstrap)

    app = typer.Typer()
    mount_config_cli(
        app,
        kit,
        state_factory=state_factory,
        args_provider=lambda: args,
    )

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    assert factory_calls == []


def test_mount_config_cli_bootstrap_policy_can_force_config_set_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    kit = _build_storage_free_kit_with_shared_env()
    args = ["config", "set", "profile", "forced"]
    factory_calls: list[CliBootstrapContext] = []

    def state_factory(context: CliBootstrapContext) -> DefaultConfigCliState:
        factory_calls.append(context)
        return DefaultConfigCliState(env_bootstrap=context.env_bootstrap)

    app = typer.Typer()
    mount_config_cli(
        app,
        kit,
        state_factory=state_factory,
        args_provider=lambda: args,
        bootstrap_policy=ConfigBootstrapPolicy(
            bootstrapless_actions=(
                DEFAULT_CONFIG_BOOTSTRAPLESS_ACTIONS - {"set"}
            ),
        ),
    )

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    assert len(factory_calls) == 1


def test_mount_config_cli_custom_config_group_name_appears_in_guidance(
    tmp_path: Path,
) -> None:
    from apprc_example_app import APPRC_EXAMPLE_APP_KIT

    kit = APPRC_EXAMPLE_APP_KIT
    storage_root = tmp_path / "storage"
    current_args: list[str] = []
    app = typer.Typer()
    mount_config_cli(
        app,
        kit,
        config_group_name="settings",
        args_provider=lambda: current_args,
    )

    setup_args = [
        "settings",
        "setup",
        "--yes",
        "--storage-root",
        str(storage_root),
    ]
    current_args = setup_args
    setup = CliRunner().invoke(app, setup_args)
    current_args = [
        "settings",
        "set",
        "app.profile",
        "demo",
        "--scope",
        "app",
    ]
    inactive_scope = CliRunner().invoke(
        app,
        current_args,
    )

    assert setup.exit_code == 0, setup.output
    assert "apprc settings doctor" in setup.output
    assert inactive_scope.exit_code != 0
    assert "settings app init" in " ".join(inactive_scope.output.split())


def test_config_doctor_payload_custom_config_group_name_next_steps(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from apprc_example_app import APPRC_EXAMPLE_APP_KIT

    kit = APPRC_EXAMPLE_APP_KIT
    monkeypatch.delenv(kit.spec.require_storage_env_key(), raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))

    payload = build_config_doctor_payload(
        kit,
        storage=None,
        config_group_name="settings",
    )

    assert any(
        step.startswith("apprc settings setup")
        for step in payload["next_steps"]
    )
    assert all("apprc config" not in step for step in payload["next_steps"])


def test_mount_config_cli_rejects_existing_root_callback() -> None:
    kit = _build_storage_free_kit_with_shared_env()
    app = typer.Typer()

    @app.callback()
    def root_cmd() -> None:
        """Existing callback owned by the host app."""

    with pytest.raises(RuntimeError, match="already has a callback"):
        mount_config_cli(app, kit)


def test_mount_config_cli_rejects_existing_config_group_name() -> None:
    kit = _build_storage_free_kit_with_shared_env()
    app = typer.Typer()

    @app.command()
    def config() -> None:
        """Host command that would collide with the generated config group."""

    with pytest.raises(RuntimeError, match="already has a command or group"):
        mount_config_cli(app, kit)


def test_cli_argv_provider_alias_accepts_token_provider() -> None:
    def provide_args() -> list[str]:
        """Return command tokens without the program name."""
        return ["config", "paths"]

    provider: CliArgvProvider = provide_args

    assert provider() == ["config", "paths"]


def test_generated_config_set_uses_context_without_ctx_obj(
    tmp_path: Path,
) -> None:
    from apprc_example_app import APPRC_EXAMPLE_APP_KIT

    kit = APPRC_EXAMPLE_APP_KIT
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    app = typer.Typer()

    @app.callback()
    def root_cmd(
        ctx: typer.Context,
        storage: StorageOption = None,
    ) -> None:
        """Provide AppRC context without application runtime state."""
        options = CliBootstrapOptions.from_typer(
            load_dotenv_layers=False,
            storage=storage,
        )
        prepare_typer_context(ctx, kit, options, skip_bootstrap=True)

    app.add_typer(kit.typer_app(), name="config")

    result = CliRunner().invoke(
        app,
        [
            "--storage",
            str(storage_root),
            "config",
            "set",
            "access_token",
            "secret-value",
            "--scope",
            "storage",
        ],
    )

    assert result.exit_code == 0, result.output
    assert 'APPRC_EXAMPLE_APP_ACCESS_TOKEN="secret-value"\n' in (
        storage_root / ".env.apprc-storage"
    ).read_text(encoding="utf-8")


def test_config_bootstrap_policy_can_force_config_set_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    kit = build_storage_free_example_kit()
    bootstrapped_commands: list[str | None] = []
    policy = ConfigBootstrapPolicy(
        bootstrapless_actions=DEFAULT_CONFIG_BOOTSTRAPLESS_ACTIONS - {"set"},
    )
    app = typer.Typer()

    @dataclass(slots=True)
    class HaiuShapedState(DefaultConfigCliState):
        payload_marker: str = "haiu-shaped"

    @app.callback()
    def root_cmd(
        ctx: typer.Context,
        env_files: EnvFilesOption = None,
        env_file_overrides_os_environ: EnvFileOverridesOption = False,
        skip_dotenv_layers: SkipDotenvLayersOption = False,
        storage: StorageOption = None,
    ) -> None:
        """Bootstrap only when the policy says this command needs runtime."""
        options = CliBootstrapOptions.from_typer(
            env_files=env_files,
            env_file_overrides_os_environ=env_file_overrides_os_environ,
            load_dotenv_layers=not skip_dotenv_layers,
            storage=storage,
        )
        context = prepare_typer_context(
            ctx,
            kit,
            options,
            skip_bootstrap=policy.request_skips_runtime_bootstrap(),
        )
        if context.skipped_runtime_bootstrap:
            return
        bootstrapped_commands.append(ctx.invoked_subcommand)
        ctx.obj = HaiuShapedState(env_bootstrap=context.env_bootstrap)

    def payload(state: HaiuShapedState) -> dict[str, Any]:
        """Return a tiny custom payload proving app state remains supported."""
        return {
            "payload_marker": state.payload_marker,
            "bootstrapped": state.env_bootstrap is not None,
        }

    app.add_typer(
        kit.typer_app(
            state_type=HaiuShapedState,
            runtime_payload=payload,
        ),
        name="config",
    )
    runner = CliRunner()
    set_args = ["--skip-dotenv-layers", "config", "set", "profile", "forced"]
    doctor_args = ["--skip-dotenv-layers", "config", "doctor", "--json"]

    monkeypatch.setattr(sys, "argv", ["apprc-test", *set_args])
    set_result = runner.invoke(app, set_args)
    monkeypatch.setattr(sys, "argv", ["apprc-test", *doctor_args])
    doctor_result = runner.invoke(app, doctor_args)

    assert set_result.exit_code == 0, set_result.output
    assert bootstrapped_commands == ["config"]
    assert doctor_result.exit_code == 0, doctor_result.output
    assert len(bootstrapped_commands) == 1
