"""Configuration CLI for the importable client example."""

from __future__ import annotations

import json

import typer

import apprc as rc
from library_client import LibraryClient
from library_client.config.app import MyRC
from library_client.config.bundle import LibraryClientConfig


def build_app(
    *,
    args_provider: rc.cli.CliArgvProvider | None = None,
    editor_app_cls: type[rc.tui.ConfigEditorApp] | None = None,
) -> typer.Typer:
    """Return a CLI for editing and exercising the library's settings.

    :param args_provider: Optional command-token provider for tests.
    :param editor_app_cls: Optional editor replacement for tests.
    :return: Typer application.
    """
    app = typer.Typer(
        help="Configure an importable AppRC client.", no_args_is_help=True
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
        """Print the timeout the importable client would use."""
        typer.echo(json.dumps(_runtime_payload(_state(ctx)), indent=2))

    return app


def _runtime_payload(state: rc.cli.DefaultConfigCliState) -> dict[str, object]:
    """Build a client from the CLI's already-resolved source snapshot."""
    assert state.resolved is not None
    settings = state.resolved.build(LibraryClientConfig).client
    client = LibraryClient(settings=settings)
    return {
        "app_id": MyRC.schema.app_id,
        "request_timeout": client.request_timeout,
    }


def _state(ctx: typer.Context) -> rc.cli.DefaultConfigCliState:
    """Return the state prepared by AppRC's mounted CLI callback."""
    if isinstance(ctx.obj, rc.cli.DefaultConfigCliState):
        return ctx.obj
    raise RuntimeError("AppRC runtime state was not initialized.")


def main() -> None:
    """Run the importable client example CLI."""
    app()


app = build_app()


if __name__ == "__main__":
    main()
