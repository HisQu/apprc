"""Standalone Example App CLI for exercising AppRC config workflows."""

from __future__ import annotations

# == 3rd Party ===============================
import typer

# == Internal ================================
import apprc
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


def _example_app_state(
    context: apprc.CliBootstrapContext,
) -> ApprcExampleAppState:
    """Build Example App runtime state after AppRC bootstrap.

    :param context: AppRC bootstrap context for this invocation.
    :return: Example App state passed to runtime payload hooks.
    """
    return ApprcExampleAppState(
        env_bootstrap=context.env_bootstrap,
        storage=context.options.storage,
    )


config_app = apprc.mount_config_cli(
    app,
    APPRC_EXAMPLE_APP_KIT,
    state_type=ApprcExampleAppState,
    state_factory=_example_app_state,
    runtime_payload=apprc_example_app_config_payload,
    setup_logging=apprc.setup_logging,
)


def main() -> None:
    """Run the standalone AppRC Example App CLI."""
    app()


if __name__ == "__main__":
    main()
