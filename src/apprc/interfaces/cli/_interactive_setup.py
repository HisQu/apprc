"""Interactive storage setup prompts with filesystem completion."""

from __future__ import annotations

# == Standard Library ===========================================
from pathlib import Path
from typing import Literal

# == 3rd Party ==================================================
import typer
from prompt_toolkit import prompt
from prompt_toolkit.completion import PathCompleter, WordCompleter

type StorageSetupChoice = Literal["default", "custom", "cancel"]


def prompt_storage_setup_root(*, suggested: Path) -> Path | None:
    """Ask whether to use the suggested root, enter another, or cancel.

    Empty input cancels. Custom path input completes directories on every
    supported platform through prompt-toolkit.

    :param suggested: Predictable default storage root.
    :return: Chosen path, or ``None`` when canceled.
    """
    typer.echo(f"Suggested storage directory: {suggested}")
    typer.echo("Choose [d]efault, [p]ath, or [c]ancel.")
    try:
        raw_choice = prompt(
            "Storage setup [c]: ",
            completer=WordCompleter(
                ["default", "path", "cancel"],
                ignore_case=True,
            ),
        )
    except (EOFError, KeyboardInterrupt):
        return None
    choice = _parse_storage_setup_choice(raw_choice)
    if choice == "cancel":
        return None
    if choice == "default":
        return suggested
    try:
        raw_path = prompt(
            "Storage path: ",
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


def _parse_storage_setup_choice(value: str) -> StorageSetupChoice:
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
