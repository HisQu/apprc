"""User-dotenv AppRC example CLI."""

from __future__ import annotations

import json

import typer

import apprc as rc
from user_dotenv.config.app import MyRC
from user_dotenv.config.bundle import UserDotenvExampleConfig


def build_app(
    *,
    args_provider: rc.cli.CliArgvProvider | None = None,
    editor_app_cls: type[rc.tui.ConfigEditorApp] | None = None,
) -> typer.Typer:
    """Return the user-dotenv example CLI.

    :param args_provider: Optional command-token provider for tests.
    :param editor_app_cls: Optional editor replacement for tests.
    :return: Typer application.
    """
    app = typer.Typer(
        help="Exercise AppRC with one managed user dotenv.",
        no_args_is_help=True,
        pretty_exceptions_show_locals=False,
    )
    rc.cli.mount_config_cli(
        app,
        MyRC,
        args_provider=args_provider,
        editor_app_cls=editor_app_cls,
        runtime_payload=_runtime_payload,
    )

    @app.command("run")
    def run_cmd(ctx: typer.Context) -> None:
        """Print the config resolved for this process."""
        typer.echo(json.dumps(_runtime_payload(_state(ctx)), indent=2))

    return app


def _runtime_payload(
    state: rc.cli.DefaultConfigCliState,
) -> dict[str, object]:
    """Return values that this example application would use."""
    assert state.resolved is not None
    config = state.resolved.build(UserDotenvExampleConfig).app
    return {
        "app_id": MyRC.schema.app_id,
        "config": {"profile": config.profile, "debug": config.debug},
    }


def _state(ctx: typer.Context) -> rc.cli.DefaultConfigCliState:
    """Return runtime state after AppRC has prepared the command."""
    if isinstance(ctx.obj, rc.cli.DefaultConfigCliState):
        return ctx.obj
    raise RuntimeError("AppRC runtime state was not initialized.")


def main() -> None:
    """Run the user-dotenv example CLI."""
    app()


app = build_app()


if __name__ == "__main__":
    main()
