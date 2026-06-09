"""Shared CLI prompts for registering storage roots."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.config.kit import AppConfigKit
from apprc.config.paths import StorageRootPathError, normalize_storage_root_path


def print_directory_listing(storage_root: Path) -> None:
    """Print a sorted first-level listing for a storage root.

    :param storage_root: Existing directory whose children should be shown.
    """
    typer.echo(f"contents of {storage_root}:")
    for child in sorted(storage_root.iterdir(), key=lambda item: item.name):
        suffix = "/" if child.is_dir() else ""
        typer.echo(f"  {child.name}{suffix}")


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
    typer.echo(f"Storage root already exists and is not empty: {storage_root}")
    typer.echo(
        f"{kit.spec.display_name} will reuse this directory for "
        f"{kit.spec.display_name} storage {storage_name!r}."
    )
    typer.echo("It will create or update only these config files:")
    typer.echo(
        f"  - storage-local env: {storage_root / kit.spec.local_env_filename}"
    )
    typer.echo(f"  - user registry: {kit.registry_path()}")
    typer.echo(
        "Existing files in the storage root will not be deleted, moved, "
        "or overwritten."
    )
    if make_default:
        typer.echo(
            f"It will also mark {storage_name!r} as the default storage."
        )
    typer.echo("Answer l to list first-level contents before deciding.")
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
        root = normalize_storage_root_path(storage_root)
    except StorageRootPathError as exc:
        raise typer.BadParameter(
            str(exc),
            param_hint="STORAGE_ROOT",
        ) from exc
    if not root.exists():
        return root
    resolved_root = root.resolve()
    if not resolved_root.is_dir():
        raise typer.BadParameter(
            f"Storage root exists but is not a directory: {resolved_root}",
            param_hint="STORAGE_ROOT",
        )
    if assume_yes:
        return resolved_root
    if any(resolved_root.iterdir()):
        confirm_existing_storage_root(
            kit,
            resolved_root,
            storage_name=storage_name,
            make_default=make_default,
        )
    return resolved_root
