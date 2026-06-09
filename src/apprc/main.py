"""Standalone demo CLI for exercising AppRC config workflows."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path
from typing import Annotated

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc_demo import (
    APPRC_DEMO_KIT,
    AppRcDemoState,
    demo_runtime_payload,
)
from apprc.cli import (
    COMMON_ROOT_VALUE_OPTIONS,
    args_after_command,
    bootstrap_cli_env,
    config_request_skips_bootstrap,
)
from apprc.logging import setup_logging


app = typer.Typer(
    help=(
        "Exercise AppRC's generated config CLI against a built-in demo "
        "application."
    ),
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)


@app.callback()
def root_cmd(
    ctx: typer.Context,
    env_file: Annotated[
        Path | None,
        typer.Option(
            "--env-file",
            help="Invocation-local dotenv file loaded after shared/local env.",
        ),
    ] = None,
    env_file_overrides_os_environ: Annotated[
        bool,
        typer.Option(
            "--env-file-overrides-os-environ",
            "-o",
            help="Let --env-file values override existing process env values.",
        ),
    ] = False,
    skip_dotenv_layers: Annotated[
        bool,
        typer.Option(
            "--skip-dotenv-layers",
            "-s",
            help="Select storage but do not merge dotenv values into env.",
        ),
    ] = False,
    storage: Annotated[
        str | None,
        typer.Option(
            "--storage",
            help="Registered demo storage selector to use for this command.",
        ),
    ] = None,
    log_level: Annotated[
        str | None,
        typer.Option(
            "--log-level",
            help="Configure AppRC logging before runtime bootstrap.",
        ),
    ] = None,
) -> None:
    """Bootstrap demo config state for commands that need runtime values."""
    state = AppRcDemoState(storage=storage)
    ctx.obj = state
    if _config_request_skips_runtime_bootstrap():
        return
    state.env_bootstrap = bootstrap_cli_env(
        APPRC_DEMO_KIT,
        env_file=env_file,
        env_file_overrides_os_environ=env_file_overrides_os_environ,
        load_dotenv_layers=not skip_dotenv_layers,
        registry_storage_name=storage,
        log_level=log_level,
        setup_logging=setup_logging,
    )


def _config_request_skips_runtime_bootstrap() -> bool:
    """Return whether the active ``config`` command can run pre-bootstrap."""
    config_args = args_after_command(
        "config",
        root_value_options=COMMON_ROOT_VALUE_OPTIONS,
    )
    if config_args is None:
        return False
    return config_request_skips_bootstrap(config_args)


config_app = APPRC_DEMO_KIT.typer_app(
    state_type=AppRcDemoState,
    runtime_payload=demo_runtime_payload,
)
app.add_typer(config_app, name="config")


def main() -> None:
    """Run the standalone AppRC demo CLI."""
    app()


if __name__ == "__main__":
    main()
