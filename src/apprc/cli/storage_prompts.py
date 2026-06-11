"""Shared CLI prompts for registering storage roots."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path

# == 3rd Party ===============================
from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
import typer

# == Internal ================================
from apprc.config.kit import AppConfigKit
import apprc.config.setup_flow as setup_flow


def print_directory_listing(storage_root: Path) -> None:
    """Print a sorted first-level listing for a storage root.

    :param storage_root: Existing directory whose children should be shown.
    """
    console = Console(soft_wrap=True)
    console.print(
        Text.assemble(
            ("contents of ", "dim"),
            (str(storage_root), "cyan"),
            (":", "dim"),
        )
    )
    for child in sorted(storage_root.iterdir(), key=lambda item: item.name):
        if child.is_dir():
            console.print(Text.assemble("  ", (f"{child.name}/", "cyan")))
        else:
            console.print(f"  {child.name}")


def confirm_existing_storage_root(
    kit: AppConfigKit,
    storage_root: Path,
    *,
    storage_name: str,
    make_default: bool,
) -> None:
    """Ask whether a non-empty existing storage root may be reused.

    :param kit: Application config facade.
    :param storage_root: Existing non-empty storage directory.
    :param storage_name: Registry selector that will point at the directory.
    :param make_default: Whether the selector will become the default.
    :raises typer.Exit: If the user refuses or input cannot be read.
    """
    console = Console(soft_wrap=True)
    apprc_tomls = Table.grid(padding=(0, 2))
    apprc_tomls.add_column(style="dim", no_wrap=True)
    apprc_tomls.add_column(style="cyan")
    apprc_tomls.add_row(
        "storage-local env",
        str(storage_root / kit.spec.local_env_filename),
    )
    apprc_tomls.add_row("user registry", str(kit.registry_path()))

    panel_lines: list[RenderableType] = [
        Text("Directory exists and is not empty.", style="yellow"),
        Text(""),
        Text("Path:", style="dim"),
        Text(str(storage_root), style="cyan"),
        Text(""),
        Text.assemble(
            kit.spec.display_name,
            " will reuse this directory for ",
            kit.spec.display_name,
            " storage ",
            (repr(storage_name), "bold"),
            ".",
        ),
        Text(""),
        Text("Config files to create or update:", style="dim"),
        apprc_tomls,
        Text(""),
        Text(
            "No existing files will be deleted, moved, or overwritten.",
            style="green",
        ),
    ]
    if make_default:
        panel_lines.extend(
            [
                Text(""),
                Text.assemble(
                    ("Default storage: ", "dim"),
                    (repr(storage_name), "bold"),
                ),
            ]
        )
    panel_lines.extend(
        [
            Text(""),
            Text.assemble(
                ("Choices: ", "dim"),
                ("y", "bold green"),
                " continue  ",
                ("n", "bold red"),
                " abort  ",
                ("l", "bold yellow"),
                " list first-level contents",
            ),
        ]
    )
    console.print(
        Panel(
            Group(*panel_lines),
            title="[bold yellow]Storage Root Already Exists[/]",
            border_style="yellow",
        )
    )
    while True:
        try:
            answer = typer.prompt(
                "Continue? [y/n/l]",
                default="",
                show_default=False,
            )
        except (EOFError, typer.Abort):
            typer.echo(
                "Refusing to register a non-empty storage root without "
                "confirmation. Re-run with --yes to continue.",
                err=True,
            )
            raise typer.Exit(code=1) from None
        normalized = answer.strip().lower()
        if normalized in {"y", "yes"}:
            return
        if normalized in {"n", "no"}:
            typer.echo("Aborted.")
            raise typer.Exit(code=1)
        if normalized in {"l", "list"}:
            print_directory_listing(storage_root)
            continue
        typer.echo("Answer y to continue, n to abort, or l to list.")


def guard_storage_root_init(
    kit: AppConfigKit,
    storage_root: Path,
    *,
    storage_name: str,
    make_default: bool,
    assume_yes: bool,
) -> Path:
    """Return a safe storage root path before registration writes.

    :param kit: Application config facade.
    :param storage_root: User-provided storage root path.
    :param storage_name: Registry selector that will point at the directory.
    :param make_default: Whether the selector will become the default.
    :param assume_yes: Whether to skip the non-empty directory confirmation.
    :return: Normalized storage root path.
    :raises typer.BadParameter: If the path cannot represent a directory.
    :raises typer.Exit: If the user declines reuse of a non-empty directory.
    """
    try:
        root = setup_flow.validate_storage_root_for_setup(
            kit,
            storage_root,
            storage_name=storage_name,
            make_default=make_default,
            allow_non_empty_storage=True,
        )
    except setup_flow.ConfigSetupError as exc:
        raise typer.BadParameter(
            str(exc),
            param_hint=exc.param_hint,
        ) from exc
    if not root.exists():
        return root
    if assume_yes:
        return root
    if any(root.iterdir()):
        confirm_existing_storage_root(
            kit,
            root,
            storage_name=storage_name,
            make_default=make_default,
        )
    return root
