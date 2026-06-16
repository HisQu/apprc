"""Standalone Example App CLI for exercising AppRC config workflows."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path
from typing import Annotated

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.cli import (
    COMMON_ROOT_VALUE_OPTIONS,
    args_after_command,
    bootstrap_cli_env,
    config_request_skips_bootstrap,
)
from apprc.logging import setup_logging
from apprc_example_app import (
    APPRC_EXAMPLE_APP_KIT,
    ApprcExampleAppState,
    apprc_example_app_config_payload,
)


app = typer.Typer(
    help=(
        "Exercise AppRC's generated config CLI against a built-in example "
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
            help="Example App storage path or registered selector for this command.",
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
    """Bootstrap Example App config state for commands that need runtime values."""
    state = ApprcExampleAppState(storage=storage)
    ctx.obj = state
    config_args = args_after_command(
        "config",
        root_value_options=COMMON_ROOT_VALUE_OPTIONS,
    )
    if config_args is not None:
        if config_request_skips_bootstrap(config_args):
            return
    state.env_bootstrap = bootstrap_cli_env(
        APPRC_EXAMPLE_APP_KIT,
        env_file=env_file,
        env_file_overrides_os_environ=env_file_overrides_os_environ,
        load_dotenv_layers=not skip_dotenv_layers,
        storage=storage,
        log_level=log_level,
        setup_logging=setup_logging,
    )


config_app = APPRC_EXAMPLE_APP_KIT.typer_app(
    state_type=ApprcExampleAppState,
    runtime_payload=apprc_example_app_config_payload,
)
app.add_typer(config_app, name="config")


def main() -> None:
    """Run the standalone AppRC Example App CLI."""
    app()


if __name__ == "__main__":
    main()
