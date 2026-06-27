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
from apprc.runtime_config.kit import AppConfigKit
from apprc.runtime_config.storage.loading import index_path_for_create
from apprc.runtime_config.storage.paths import (
    StorageRootPathError,
    normalize_storage_root_path,
)


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
) -> None:
    """Ask whether a non-empty existing storage root may be reused.

    :param kit: Application config facade.
    :param storage_root: Existing non-empty storage directory.
    :param storage_name: Registry selector that will point at the directory.
    :raises typer.Exit: If the user refuses or input cannot be read.
    """
    console = Console(soft_wrap=True)
    managed_files = Table.grid(padding=(0, 2))
    managed_files.add_column(style="dim", no_wrap=True)
    managed_files.add_column(style="cyan")
    managed_files.add_row(
        "storage env",
        str(storage_root / kit.spec.storage_env_filename),
    )
    managed_files.add_row(
        "named-storage index",
        str(index_path_for_create(kit.spec)),
    )

    panel_lines: list[RenderableType] = [
        Text("Storage root exists and is not empty.", style="yellow"),
        Text(""),
        Text("Storage root:", style="dim"),
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
        Text("AppRC-managed files to create or update:", style="dim"),
        managed_files,
        Text(""),
        Text(
            "Existing files inside the storage root will not be deleted, "
            "moved, or overwritten.",
            style="green",
        ),
    ]
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
            title="[bold yellow]Storage Root Not Empty[/]",
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
    assume_yes: bool,
) -> Path:
    """Return a safe storage root path before registration writes.

    :param kit: Application config facade.
    :param storage_root: User-provided storage root path.
    :param storage_name: Registry selector that will point at the directory.
    :param assume_yes: Whether to skip the non-empty directory confirmation.
    :return: Normalized storage root path.
    :raises typer.BadParameter: If the path cannot represent a directory.
    :raises typer.Exit: If the user declines reuse of a non-empty directory.
    """
    try:
        root = normalize_storage_root_path(storage_root)
    except StorageRootPathError as exc:
        raise typer.BadParameter(
            str(exc),
            param_hint="PATH",
        ) from exc
    if root.exists() and not root.is_dir():
        raise typer.BadParameter(
            f"Storage root exists but is not a directory: {root}",
            param_hint="PATH",
        )
    if not root.exists():
        return root
    if assume_yes:
        return root
    if any(root.iterdir()):
        confirm_existing_storage_root(
            kit,
            root,
            storage_name=storage_name,
        )
    return root
