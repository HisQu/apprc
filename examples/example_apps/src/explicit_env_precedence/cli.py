"""Explicit env-file precedence AppRC example CLI."""

from __future__ import annotations

# == Standard Library ===========================================
import json

# == 3rd Party ==================================================
import typer

# == Internal ===================================================
import apprc as rc
from explicit_env_precedence.config import (
    ExplicitEnvPrecedenceExampleConfig,
    MyRC,
)


def build_app(
    *,
    args_provider: rc.cli.CliArgvProvider | None = None,
    editor_app_cls: type[rc.cli.ConfigEditorApp] | None = None,
) -> typer.Typer:
    """Return the explicit env precedence example CLI.

    :param args_provider: Optional command-token provider for tests.
    :param editor_app_cls: Optional editor replacement for tests.
    :return: Typer application.
    """
    app = typer.Typer(
        help="Exercise shell versus explicit dotenv precedence.",
        no_args_is_help=True,
        pretty_exceptions_show_locals=False,
    )
    MyRC.mount_cli(
        app,
        args_provider=args_provider,
        editor_app_cls=editor_app_cls,
        runtime_payload=_runtime_payload,
    )

    @app.command("run")
    def run_cmd(ctx: typer.Context) -> None:
        """Print the selected root and its resolved label."""
        typer.echo(json.dumps(_runtime_payload(_state(ctx)), indent=2))

    return app


def _runtime_payload(
    state: rc.cli.DefaultConfigCliState,
) -> dict[str, object]:
    """Return values that make the winning env layer visible."""
    config = ExplicitEnvPrecedenceExampleConfig().precedence
    bootstrap = state.env_bootstrap
    return {
        "app_id": MyRC.spec.app_id,
        "storage_name": bootstrap.storage_name if bootstrap else None,
        "storage_root": str(bootstrap.storage_root) if bootstrap else None,
        "label": config.label,
    }


def _state(ctx: typer.Context) -> rc.cli.DefaultConfigCliState:
    """Return runtime state after AppRC has prepared the command."""
    if isinstance(ctx.obj, rc.cli.DefaultConfigCliState):
        return ctx.obj
    raise RuntimeError("AppRC runtime state was not initialized.")


def main() -> None:
    """Run the explicit env precedence example CLI."""
    app()


app = build_app()


if __name__ == "__main__":
    main()
