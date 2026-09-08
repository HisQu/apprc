"""Interactive AppRC setup prompts with filesystem completion."""

from __future__ import annotations

# == Standard Library ===========================================
from pathlib import Path
from typing import Literal

# == 3rd Party ==================================================
import typer
from prompt_toolkit import prompt
from prompt_toolkit.completion import PathCompleter, WordCompleter

# == Internal ===================================================
from apprc.user_files.storage_roots.registry import StorageRegistry

type SetupDirectoryChoice = Literal["default", "custom", "cancel"]
type MigrationStorageChoice = tuple[Literal["add", "replace"], str | None]


def prompt_apprc_setup_dir(*, suggested: Path) -> Path | None:
    """Ask for the directory that will contain AppRC-managed files.

    :param suggested: Directory resolved from environment, declaration, or the
        cross-platform AppRC default.
    :return: Chosen path, or ``None`` when canceled.
    """
    return _prompt_setup_directory(subject="AppRC", suggested=suggested)


def prompt_storage_setup_root(*, suggested: Path) -> Path | None:
    """Ask whether to use the suggested root, enter another, or cancel.

    Empty input cancels. Custom path input completes directories on every
    supported platform through prompt-toolkit.

    :param suggested: Predictable default storage root.
    :return: Chosen path, or ``None`` when canceled.
    """
    return _prompt_setup_directory(subject="Storage", suggested=suggested)


def _prompt_setup_directory(
    *,
    subject: str,
    suggested: Path,
) -> Path | None:
    """Prompt for one directory using the shared three-way choice.

    :param subject: Human-facing directory owner.
    :param suggested: Predictable path accepted by the default choice.
    :return: Selected path, or ``None`` when canceled.
    """
    typer.echo(f"Suggested {subject} directory: {suggested}")
    typer.echo("Choose [d]efault, [p]ath, or [c]ancel.")
    try:
        raw_choice = prompt(
            f"{subject} setup [c]: ",
            completer=WordCompleter(
                ["default", "path", "cancel"],
                ignore_case=True,
            ),
        )
    except (EOFError, KeyboardInterrupt):
        return None
    choice = _parse_setup_directory_choice(raw_choice)
    if choice == "cancel":
        return None
    if choice == "default":
        return suggested
    try:
        raw_path = prompt(
            f"{subject} path: ",
            completer=PathCompleter(
                only_directories=True,
                expanduser=True,
            ),
        ).strip()
    except (EOFError, KeyboardInterrupt):
        return None
    return Path(raw_path).expanduser() if raw_path else None


def prompt_storage_registration_name(*, suggested: str) -> str | None:
    """Prompt for the registry name assigned to a direct storage path.

    :param suggested: Name shown as the default.
    :return: Entered name, the suggestion on empty input, or ``None`` when
        prompt-toolkit reports an interruption.
    """
    try:
        return prompt("Storage name: ", default=suggested).strip() or suggested
    except (EOFError, KeyboardInterrupt):
        return None


def prompt_storage_migration_root(*, selector_name: str) -> Path | None:
    """Ask for the existing directory behind an unregistered selector.

    :param selector_name: Bare storage name that migration must register.
    :return: Entered path, or ``None`` when canceled or left blank.
    """
    typer.echo(
        f"Storage selector {selector_name!r} needs an existing directory."
    )
    try:
        raw_path = prompt(
            f"Directory for {selector_name}: ",
            completer=PathCompleter(
                only_directories=True,
                expanduser=True,
            ),
        ).strip()
    except (EOFError, KeyboardInterrupt):
        return None
    return Path(raw_path).expanduser() if raw_path else None


def prompt_storage_migration_choice(
    *,
    selector_name: str,
    storage_root: Path,
    registry: StorageRegistry,
) -> MigrationStorageChoice | None:
    """Choose whether migration adds or replaces a registry entry.

    A root already registered under another name cannot gain a second alias.
    In that case the only useful migration is an explicitly confirmed rename.

    :param selector_name: Unregistered selector that must become runnable.
    :param storage_root: Existing directory supplied for that selector.
    :param registry: Current named-storage registry.
    :return: Add or replace choice, or ``None`` when canceled.
    """
    resolved_root = storage_root.expanduser().resolve()
    matching_names = [
        name
        for name, record in registry.storages.items()
        if record.root.expanduser().resolve() == resolved_root
    ]
    if matching_names:
        existing_name = matching_names[0]
        if typer.confirm(
            f"{storage_root} is registered as {existing_name!r}. Rename that "
            f"entry to {selector_name!r}?"
        ):
            return "replace", existing_name
        return None
    if not registry.storages:
        return "add", None

    typer.echo(f"Register {selector_name!r} at {storage_root}.")
    typer.echo("Choose [n]ew, [r]eplace an existing entry, or [c]ancel.")
    try:
        raw_choice = (
            prompt(
                "Storage mapping [c]: ",
                completer=WordCompleter(
                    ["new", "replace", "cancel"],
                    ignore_case=True,
                ),
            )
            .strip()
            .lower()
        )
    except (EOFError, KeyboardInterrupt):
        return None
    if raw_choice in {"n", "new"}:
        return "add", None
    if raw_choice not in {"r", "replace"}:
        return None

    names = sorted(registry.storages)
    for name in names:
        record = registry.storages[name]
        status = "exists" if record.root.is_dir() else "missing"
        typer.echo(f"  {name}: {record.root} ({status})")
    try:
        replace_name = prompt(
            "Replace storage: ",
            completer=WordCompleter(names),
        ).strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if replace_name not in registry.storages:
        typer.echo(f"Unknown storage {replace_name!r}.", err=True)
        return None
    if not typer.confirm(
        f"Rename and repoint {replace_name!r} to {selector_name!r} at "
        f"{storage_root}? No application data will be moved or deleted."
    ):
        return None
    return "replace", replace_name


def _parse_setup_directory_choice(value: str) -> SetupDirectoryChoice:
    """Normalize one short or full setup choice.

    :param value: Interactive input.
    :return: Supported choice, defaulting to cancellation.
    """
    normalized = value.strip().lower()
    if normalized in {"d", "default"}:
        return "default"
    if normalized in {"p", "path"}:
        return "custom"
    return "cancel"
