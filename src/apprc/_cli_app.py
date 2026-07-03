"""Command-line entrypoint for AppRC development helpers."""

# == Standard Library ========================
from pathlib import Path
from typing import Annotated

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.scaffold import (
    ConfigScaffoldMode,
    ConfigScaffoldRequest,
    scaffold_config_package,
)

app = typer.Typer(
    help="Developer tools for AppRC-enabled applications.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)
scaffold_app = typer.Typer(
    help="Generate AppRC integration files.",
    no_args_is_help=True,
)
app.add_typer(scaffold_app, name="scaffold")


@scaffold_app.command("config")
def scaffold_config_cmd(
    package: Annotated[
        str,
        typer.Option(
            "--package",
            help="Import package that receives config/, for example myapp.",
        ),
    ],
    mode: Annotated[
        ConfigScaffoldMode,
        typer.Option(
            "--mode",
            help=(
                "AppRC mode: env-only, storage-only, app-wide-config, "
                "or app-wide-storage."
            ),
        ),
    ],
    app_name: Annotated[
        str,
        typer.Option("--app-name", help="Stable AppRC application name."),
    ],
    display_name: Annotated[
        str | None,
        typer.Option(
            "--display-name",
            help="Human-readable application name.",
        ),
    ] = None,
    storage_env_key: Annotated[
        str | None,
        typer.Option(
            "--storage-env-key",
            help="Full storage selector env key for storage modes.",
        ),
    ] = None,
    env_prefix: Annotated[
        str | None,
        typer.Option(
            "--env-prefix",
            help="Full env prefix for the generated AppSection.",
        ),
    ] = None,
    target: Annotated[
        Path,
        typer.Option(
            "--target",
            help="Source root that contains the package.",
        ),
    ] = Path("src"),
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Replace existing generated config files.",
        ),
    ] = False,
) -> None:
    """Generate AppRC's standard ``X.config`` package layout."""
    try:
        result = scaffold_config_package(
            ConfigScaffoldRequest(
                package=package,
                mode=mode,
                app_name=app_name,
                display_name=display_name,
                target=target,
                storage_env_key=storage_env_key,
                env_prefix=env_prefix,
                force=force,
            )
        )
    except (FileExistsError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    typer.echo(f"Created AppRC config package: {result.config_package_dir}")
    for path in result.written_files:
        typer.echo(f"- {path}")


def main() -> None:
    """Run the AppRC command-line application."""
    app()
