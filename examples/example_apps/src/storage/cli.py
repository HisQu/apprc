"""Storage-only AppRC example CLI."""

from __future__ import annotations

import json

import typer

import apprc as rc
from storage.config.app import MyRC
from storage.config.bundle import StorageExampleConfig


def build_app(
    *,
    args_provider: rc.cli.CliArgvProvider | None = None,
    editor_app_cls: type[rc.tui.ConfigEditorApp] | None = None,
) -> typer.Typer:
    """Return the storage example CLI.

    :param args_provider: Optional command-token provider for tests.
    :param editor_app_cls: Optional editor replacement for tests.
    :return: Typer application.
    """
    app = typer.Typer(
        help="Exercise AppRC storage without a user dotenv.",
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
    config = state.resolved.build(StorageExampleConfig).app
    selection = state.resolved.selection if state.resolved is not None else None
    return {
        "app_id": MyRC.schema.app_id,
        "storage_name": selection.storage_name if selection else None,
        "storage_root": str(selection.root) if selection else None,
        "config": {
            "profile": config.profile,
            "api_token": "<redacted>",
        },
    }


def _state(ctx: typer.Context) -> rc.cli.DefaultConfigCliState:
    """Return runtime state after AppRC has prepared the command."""
    if isinstance(ctx.obj, rc.cli.DefaultConfigCliState):
        return ctx.obj
    raise RuntimeError("AppRC runtime state was not initialized.")


def main() -> None:
    """Run the storage example CLI."""
    app()


app = build_app()


if __name__ == "__main__":
    main()
