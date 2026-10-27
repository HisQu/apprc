"""Cache-only AppRC example CLI."""

from __future__ import annotations

import typer

import apprc as rc
from cache_only.config.app import MyRC


def build_app() -> typer.Typer:
    """Build the CLI demonstrating AppRC cache path initialization.

    :return: Grouped AppRC command application.
    """
    app = typer.Typer(
        help="Inspect and initialize AppRC cache paths.",
        no_args_is_help=True,
        pretty_exceptions_show_locals=False,
    )
    rc.cli.mount_app_cli(app, MyRC)
    return app


def main() -> None:
    """Run the cache-only example CLI."""
    app()


app = build_app()

if __name__ == "__main__":
    main()
