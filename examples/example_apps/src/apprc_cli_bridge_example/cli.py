"""Host-owned callback example using ``ConfigCliBridge``."""

from __future__ import annotations

# == Standard Library ========================
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

# == 3rd Party ===============================
import typer

# == Internal ================================
import apprc
from apprc_cli_bridge_example.config import BridgeConfig, KIT, OWNERS
from apprc_example_apps._support import (
    bootstrap_payload,
    config_values,
    setup_example_logging,
)


@dataclass(frozen=True, slots=True)
class BridgeOptions:
    """Host-owned options understood by the bridge example.

    :param env_files: Explicit dotenv files passed to AppRC.
    :param env_file_overrides_os_environ: Whether explicit dotenv values beat
        current process env values.
    :param load_dotenv_layers: Whether AppRC should merge dotenv layers.
    :param storage: Optional active storage selector.
    :param log_level: Optional logging level.
    :param workspace: Example app-specific workspace path.
    :param model: Example app-specific model name.
    :param dry_run: Example app-specific execution flag.
    """

    env_files: Sequence[Path] | None = None
    env_file_overrides_os_environ: bool = False
    load_dotenv_layers: bool = True
    storage: str | None = None
    log_level: str | None = None
    workspace: Path | None = None
    model: str | None = None
    dry_run: bool = False


@dataclass(slots=True)
class BridgeState(apprc.DefaultConfigCliState):
    """Runtime state built by the host callback after AppRC bootstrap.

    :param workspace: Example app-specific workspace path.
    :param model: Example app-specific model name.
    :param dry_run: Example app-specific execution flag.
    """

    workspace: Path | None = None
    model: str | None = None
    dry_run: bool = False


def build_app(
    *,
    args_provider: apprc.CliArgvProvider | None = None,
    editor_app_cls: type[apprc.ConfigEditorApp] | None = None,
) -> typer.Typer:
    """Return the CLI bridge example app.

    :param args_provider: Optional command-token provider for tests.
    :param editor_app_cls: Optional editor replacement for tests.
    :return: Typer application.
    """
    app = typer.Typer(
        help="Exercise AppRC's ConfigCliBridge host-callback integration.",
        no_args_is_help=True,
        pretty_exceptions_show_locals=False,
    )
    bridge = apprc.ConfigCliBridge[BridgeOptions, BridgeState](
        KIT,
        state_type=BridgeState,
        state_factory=_build_state,
        bootstrap_policy=apprc.HostCliBootstrapPolicy(
            bootstrapless_commands={
                "status": apprc.BootstraplessCommand(skip_empty=True),
            },
            extra_host_flag_options={"--dry-run"},
            extra_host_value_options={"--workspace", "--model"},
        ),
        args_provider=args_provider,
        runtime_payload=_runtime_payload,
        editor_app_cls=editor_app_cls,
        setup_logging=setup_example_logging,
    )

    @app.callback()
    def cli(
        ctx: typer.Context,
        env_files: apprc.EnvFilesOption = None,
        env_file_overrides_os_environ: (apprc.EnvFileOverridesOption) = False,
        skip_dotenv_layers: apprc.SkipDotenvLayersOption = False,
        storage: apprc.StorageOption = None,
        log_level: apprc.LogLevelOption = None,
        workspace: Annotated[
            Path | None,
            typer.Option("--workspace", help="Example app workspace path."),
        ] = None,
        model: Annotated[
            str | None,
            typer.Option("--model", help="Example app model name."),
        ] = None,
        dry_run: Annotated[
            bool,
            typer.Option("--dry-run", help="Run without side effects."),
        ] = False,
    ) -> None:
        """Prepare AppRC plus app-specific host state."""
        options = BridgeOptions(
            env_files=env_files,
            env_file_overrides_os_environ=env_file_overrides_os_environ,
            load_dotenv_layers=not skip_dotenv_layers,
            storage=storage,
            log_level=log_level,
            workspace=workspace,
            model=model,
            dry_run=dry_run,
        )
        session = bridge.prepare(ctx, options)
        if session.skipped_runtime_bootstrap:
            return

    @app.command("status")
    def status_cmd() -> None:
        """Show a bootstrapless host-owned status command."""
        typer.echo("bridge_status: bootstrapless")

    @app.command("run")
    def run_cmd(ctx: typer.Context) -> None:
        """Print the runtime config resolved through the bridge."""
        state = _require_bridge_state(ctx)
        typer.echo(
            json.dumps(
                _runtime_payload(state),
                indent=2,
                sort_keys=True,
                default=str,
            )
        )

    bridge.mount_config_group(app)
    return app


def _build_state(
    context: apprc.CliBootstrapContext,
    options: BridgeOptions,
) -> BridgeState:
    """Build app-owned runtime state after AppRC bootstrap.

    :param context: AppRC bootstrap context for this invocation.
    :param options: Host-owned callback options.
    :return: Bridge example runtime state.
    """
    return BridgeState(
        env_bootstrap=context.env_bootstrap,
        storage=options.storage,
        workspace=options.workspace,
        model=options.model,
        dry_run=options.dry_run,
    )


def _runtime_payload(state: BridgeState) -> dict[str, object]:
    """Return JSON-friendly bridge runtime state.

    :param state: Runtime state created by the bridge callback.
    :return: Payload with app options, bootstrap paths, and redacted config.
    """
    config = BridgeConfig()
    return {
        "app_name": KIT.spec.app_name,
        "command_name": KIT.spec.config_command_name(),
        "display_name": KIT.spec.display_name,
        "host_options": {
            "workspace": str(state.workspace) if state.workspace else None,
            "model": state.model,
            "dry_run": state.dry_run,
        },
        "bootstrap": bootstrap_payload(state.env_bootstrap),
        "config": config_values(config),
    }


def _require_bridge_state(ctx: typer.Context) -> BridgeState:
    """Return bridge state from a runtimeful command context.

    :param ctx: Active Typer command context.
    :return: Bridge runtime state.
    :raises RuntimeError: If runtime bootstrap did not create state.
    """
    if isinstance(ctx.obj, BridgeState):
        return ctx.obj
    raise RuntimeError("Bridge runtime state was not initialized.")


def run_demo(root: Path) -> dict[str, object]:
    """Execute a compact bridge scenario without invoking a subprocess.

    :param root: Temporary run directory.
    :return: JSON-friendly scenario summary.
    """
    storage_root = root / "bridge-storage"
    storage_root.mkdir(parents=True)
    apprc.ensure_storage_env_file(storage_root)
    apprc.set_storage_env_value(
        storage_root=storage_root,
        reference="api_token",
        raw_value="bridge-secret",
        owners=OWNERS,
    )
    bootstrap = KIT.bootstrap(
        env_files=(),
        env_file_overrides_os_environ=False,
        load_dotenv_layers=True,
        storage=str(storage_root),
    )
    state = BridgeState(
        env_bootstrap=bootstrap,
        storage=str(storage_root),
        workspace=root / "workspace",
        model="demo-model",
        dry_run=True,
    )
    return {
        "mode": "cli_bridge",
        "selected_storage_root": str(bootstrap.storage_root),
        "payload": _runtime_payload(state),
    }


def main() -> None:
    """Run the CLI bridge example."""
    app()


app = build_app()


if __name__ == "__main__":
    main()
