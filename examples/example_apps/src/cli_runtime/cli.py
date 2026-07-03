"""App-owned callback example using ``CliRuntime``."""

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
import apprc as rc
from cli_runtime.config import (
    CONFIG_SECTIONS,
    CliRuntimeExampleConfig,
    KIT,
)
from _example_apps_utils._support import (
    bootstrap_payload,
    config_values,
    run_isolated,
    setup_example_logging,
)


@dataclass(frozen=True, slots=True)
class RuntimeOptions:
    """App-owned options understood by the runtime example.

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
class RuntimeState(rc.cli.DefaultConfigCliState):
    """Runtime state built by the app callback after AppRC setup.

    :param workspace: Example app-specific workspace path.
    :param model: Example app-specific model name.
    :param dry_run: Example app-specific execution flag.
    """

    workspace: Path | None = None
    model: str | None = None
    dry_run: bool = False


def build_app(
    *,
    args_provider: rc.cli.CliArgvProvider | None = None,
    editor_app_cls: type[rc.cli.ConfigEditorApp] | None = None,
) -> typer.Typer:
    """Return the CLI runtime example app.

    :param args_provider: Optional command-token provider for tests.
    :param editor_app_cls: Optional editor replacement for tests.
    :return: Typer application.
    """
    app = typer.Typer(
        help="Exercise AppRC's CliRuntime app-callback integration.",
        no_args_is_help=True,
        pretty_exceptions_show_locals=False,
    )
    runtime = rc.cli.CliRuntime[RuntimeOptions, RuntimeState](
        KIT,
        state_type=RuntimeState,
        state_factory=_build_state,
        runtime_policy=rc.cli.CliRuntimePolicy(
            runtime_independent_commands={
                "status": rc.cli.RuntimeIndependentCommand(skip_empty=True),
            },
            extra_cli_flag_options={"--dry-run"},
            extra_cli_value_options={"--workspace", "--model"},
        ),
        args_provider=args_provider,
        runtime_payload=_runtime_payload,
        editor_app_cls=editor_app_cls,
        setup_logging=setup_example_logging,
    )

    @app.callback()
    def cli(
        ctx: typer.Context,
        env_files: rc.cli.EnvFilesOption = None,
        env_file_overrides_os_environ: (rc.cli.EnvFileOverridesOption) = False,
        skip_dotenv_layers: rc.cli.SkipDotenvLayersOption = False,
        storage: rc.cli.StorageOption = None,
        log_level: rc.cli.LogLevelOption = None,
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
        """Prepare AppRC plus app-specific CLI state."""
        options = RuntimeOptions(
            env_files=env_files,
            env_file_overrides_os_environ=env_file_overrides_os_environ,
            load_dotenv_layers=not skip_dotenv_layers,
            storage=storage,
            log_level=log_level,
            workspace=workspace,
            model=model,
            dry_run=dry_run,
        )
        session = runtime.prepare(ctx, options)
        if session.runtime_setup_skipped:
            return

    @app.command("status")
    def status_cmd() -> None:
        """Show a runtime-independent app-owned status command."""
        typer.echo("runtime_status: runtime-independent")

    @app.command("run")
    def run_cmd(ctx: typer.Context) -> None:
        """Print the runtime config resolved through the runtime."""
        state = _require_runtime_state(ctx)
        typer.echo(
            json.dumps(
                _runtime_payload(state),
                indent=2,
                sort_keys=True,
                default=str,
            )
        )

    runtime.mount_config_group(app)
    return app


def _build_state(
    context: rc.cli.CliRuntimeContext,
    options: RuntimeOptions,
) -> RuntimeState:
    """Build app-owned runtime state after AppRC setup.

    :param context: AppRC runtime context for this invocation.
    :param options: App-owned callback options.
    :return: Runtime example runtime state.
    """
    return RuntimeState(
        env_bootstrap=context.env_bootstrap,
        storage=options.storage,
        workspace=options.workspace,
        model=options.model,
        dry_run=options.dry_run,
    )


def _runtime_payload(state: RuntimeState) -> dict[str, object]:
    """Return JSON-friendly app runtime state.

    :param state: Runtime state created by the runtime callback.
    :return: Payload with app options, bootstrap paths, and redacted config.
    """
    config = CliRuntimeExampleConfig()
    return {
        "app_name": KIT.spec.app_name,
        "command_name": KIT.spec.config_command_name(),
        "display_name": KIT.spec.display_name,
        "bundle": type(config).__name__,
        "cli_options": {
            "workspace": str(state.workspace) if state.workspace else None,
            "model": state.model,
            "dry_run": state.dry_run,
        },
        "bootstrap": bootstrap_payload(state.env_bootstrap),
        "config": config_values(config.runtime),
    }


def _require_runtime_state(ctx: typer.Context) -> RuntimeState:
    """Return state from a command that needs runtime setup.

    :param ctx: Active Typer command context.
    :return: App runtime state.
    :raises RuntimeError: If runtime setup did not create state.
    """
    if isinstance(ctx.obj, RuntimeState):
        return ctx.obj
    raise RuntimeError("CLI runtime state was not initialized.")


def run_demo(root: Path) -> dict[str, object]:
    """Execute a compact runtime scenario without invoking a subprocess.

    :param root: Temporary run directory.
    :return: JSON-friendly scenario summary.
    """

    def scenario() -> dict[str, object]:
        """Run the demo after environment isolation is active."""
        storage_root = root / "runtime-storage"
        storage_root.mkdir(parents=True)
        rc.files.ensure_storage_env_file(storage_root)
        rc.files.set_storage_env_value(
            storage_root=storage_root,
            reference="api_token",
            raw_value="runtime-secret",
            owners=CONFIG_SECTIONS,
        )
        bootstrap = KIT.bootstrap(
            env_files=(),
            env_file_overrides_os_environ=False,
            load_dotenv_layers=True,
            storage=str(storage_root),
        )
        state = RuntimeState(
            env_bootstrap=bootstrap,
            storage=str(storage_root),
            workspace=root / "workspace",
            model="demo-model",
            dry_run=True,
        )
        return {
            "mode": "cli_runtime",
            "selected_storage_root": str(bootstrap.storage_root),
            "payload": _runtime_payload(state),
        }

    return run_isolated(
        root,
        env_prefixes=("APPRC_EXAMPLE_RUNTIME_",),
        scenario=scenario,
    )


def main() -> None:
    """Run the CLI runtime example."""
    app()


app = build_app()


if __name__ == "__main__":
    main()
